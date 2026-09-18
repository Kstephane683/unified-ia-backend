"""
Abonnements au push navigateur — interface publique (P3-PUSH).

CE QUE CE MODULE RACCORDE
-------------------------
La tâche 6.5 (`notifications.py`) sait déjà ENVOYER un Web Push : elle attend
une liste d'abonnements et des clés VAPID. La tâche 6.4 a un service worker qui
sait RECEVOIR un push et ouvrir l'application au clic. Entre les deux, il
manquait l'enregistrement : c'est ici, et dans les deux routes publiques de
`backend/api/routes/chatbot.py`.

DEUX SOURCES D'ABONNEMENTS, UN SEUL ENVOI
-----------------------------------------
`chatbot_push_subscriptions` (tâche 6.5) porte les abonnements créés par la
route d'administration ; `push_subscriptions` (ce module) porte ceux créés par
le widget, c'est-à-dire par le navigateur d'un visiteur. Les deux tables
existent parce que `create_all()` — l'initialisation qui tourne au boot — crée
les tables absentes mais n'ajoute jamais une colonne à une table existante :
modifier le modèle de 6.5 aurait annoncé à l'ORM des colonnes que la production
n'a pas. Le détail est en tête de `models.PushSubscription`.

`abonnements_actifs()` lit donc LES DEUX tables et dédoublonne sur `endpoint`,
pour qu'un même navigateur inscrit des deux côtés ne reçoive qu'un envoi.

LE PIÈGE `ANY(:liste)` DU PROJET
--------------------------------
Ce module n'écrit aucune requête `= ANY(:liste)` : sous psycopg2, lier une liste
Python à ce paramètre échoue. Il n'y en a pas besoin — les abonnements sont lus
par un simple filtre `actif IS TRUE`, et l'horodatage d'utilisation est écrit
sur les objets ORM déjà tenus en main, sans `IN (...)` ni `ANY (...)`.

LE PIÈGE DES COLONNES JSON
--------------------------
La table `push_subscriptions` n'a AUCUNE colonne JSON, volontairement : sur une
colonne JSON, SQLAlchemy compare `new == old` au flush, et une mutation en place
n'est jamais écrite sans `flag_modified()`. Le motif est déjà appliqué ailleurs
(`admin_chatbot.set_metadata`) ; ne pas avoir de JSON ici supprime le problème
au lieu de le contourner.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError

from .models import ChatbotPushSubscription, PushSubscription

# ============================================================
# ENDPOINTS ACCEPTÉS
# ============================================================
#
# POURQUOI UNE LISTE BLANCHE DE FOURNISSEURS, ET PAS UN SIMPLE `https://`
# ------------------------------------------------------------------------
# L'endpoint est FOURNI PAR LE NAVIGATEUR DU VISITEUR et l'abonnement est
# PUBLIC : n'importe qui peut donc enregistrer l'URL qu'il veut. Or c'est à
# cette URL que le serveur enverra une requête HTTP au moment de la
# notification. Accepter n'importe quelle URL transforme l'endpoint public en
# relais vers le réseau interne (le cas classique : l'adresse de métadonnées du
# hébergeur, qui rend des jetons d'instance). Le contrôle est donc fait ICI,
# à l'entrée, sur le domaine exact — pas seulement sur le schéma.
#
# Les quatre suffixes ci-dessous couvrent les navigateurs réels : Chrome,
# Chromium, Edge, Brave, Opera et Samsung Internet passent par FCM ; Firefox par
# son propre service ; Safari par APNs ; Edge sous Windows par le WNS.
FOURNISSEURS_PAR_DEFAUT: Tuple[str, ...] = (
    "fcm.googleapis.com",          # Chrome, Chromium, Edge, Brave, Opera, Samsung
    "push.services.mozilla.com",   # Firefox (updates.push.services.mozilla.com)
    "push.apple.com",              # Safari (web.push.apple.com)
    "notify.windows.com",          # Edge sous Windows (wns2-xxx.notify.windows.com)
)

#: Longueur maximale d'un endpoint. Les endpoints réels font 100 à 500
#: caractères ; borner évite qu'une valeur démesurée casse l'index unique de la
#: colonne (un index btree PostgreSQL refuse les entrées trop longues) et
#: transforme un 500 en 422.
LONGUEUR_ENDPOINT_MAX = 2048

#: base64url, éventuellement avec du remplissage. Les clés Web Push sont des
#: blobs base64url non remplis ; on tolère le remplissage plutôt que de refuser
#: un navigateur qui en ajoute.
_MOTIF_CLE = re.compile(r"^[A-Za-z0-9_\-]+=*$")

#: Longueurs minimales. Les valeurs réelles : p256dh = 87 caractères (point
#: P-256 non compressé), auth = 22 caractères (16 octets). Les minima sont
#: volontairement très en dessous : ils écartent une valeur vide ou tronquée
#: sans risquer de refuser un navigateur légitime.
LONGUEUR_MIN_P256DH = 40
LONGUEUR_MIN_AUTH = 20


def fournisseurs_autorises() -> Tuple[str, ...]:
    """Suffixes de domaine acceptés pour un endpoint de push.

    `PUSH_ENDPOINTS_AUTORISES` (séparé par des virgules) ajoute des domaines
    sans toucher au code — pour un service de push auto-hébergé ou un
    fournisseur nouvellement apparu. Aucun joker `*` n'est accepté : une
    variable d'environnement ne doit pas pouvoir désactiver un contrôle de
    sécurité en une valeur.
    """
    supplement = [
        element.strip().lower().lstrip(".")
        for element in (os.getenv("PUSH_ENDPOINTS_AUTORISES") or "").split(",")
        if element.strip()
    ]
    return tuple(dict.fromkeys(FOURNISSEURS_PAR_DEFAUT + tuple(supplement)))


def _domaine_autorise(hote: str) -> Optional[str]:
    """Renvoie le suffixe qui autorise cet hôte, sinon None.

    La comparaison exige une frontière sur un point : `fcm.googleapis.com` et
    `x.fcm.googleapis.com` passent, `xfcm.googleapis.com` non. Sans cette
    frontière, un domaine fabriqué comme `evilfcm.googleapis.com` serait accepté.
    """
    for suffixe in fournisseurs_autorises():
        if hote == suffixe or hote.endswith("." + suffixe):
            return suffixe
    return None


def valider_endpoint(endpoint: str) -> str:
    """Valide l'URL du service de push et renvoie sa forme nettoyée.

    Lève `ValueError` avec un motif lisible — la couche Pydantic la transforme
    en 422, jamais en 500.
    """
    valeur = (endpoint or "").strip()
    if not valeur:
        raise ValueError("endpoint manquant")
    if len(valeur) > LONGUEUR_ENDPOINT_MAX:
        raise ValueError(
            f"endpoint trop long ({len(valeur)} caractères, maximum "
            f"{LONGUEUR_ENDPOINT_MAX})"
        )

    parties = urlsplit(valeur)
    if parties.scheme != "https":
        raise ValueError("endpoint : le schéma doit être https")
    if "@" in (parties.netloc or ""):
        raise ValueError("endpoint : identifiants interdits dans l'URL")

    hote = (parties.hostname or "").lower()
    if not hote:
        raise ValueError("endpoint : domaine illisible")

    suffixe = _domaine_autorise(hote)
    if suffixe is None:
        raise ValueError(
            "endpoint : domaine non autorisé "
            f"« {hote} » — les services de push connus sont "
            f"{', '.join(fournisseurs_autorises())}. Un autre fournisseur "
            "s'ajoute par la variable d'environnement PUSH_ENDPOINTS_AUTORISES."
        )
    return valeur


def valider_cle(valeur: str, nom: str, longueur_min: int) -> str:
    """Valide une clé p256dh ou auth. Lève `ValueError` sinon."""
    propre = (valeur or "").strip()
    if not propre:
        raise ValueError(f"keys.{nom} manquant")
    if len(propre) < longueur_min:
        raise ValueError(
            f"keys.{nom} trop court ({len(propre)} caractères, minimum "
            f"{longueur_min})"
        )
    if not _MOTIF_CLE.match(propre):
        raise ValueError(f"keys.{nom} : base64url attendu")
    return propre


def tronquer_endpoint(endpoint: str, longueur: int = 48) -> str:
    """Forme courte d'un endpoint, pour les réponses et les journaux.

    Un endpoint est une capacité : qui le connaît peut viser ce navigateur. On
    ne le recopie donc pas en entier dans une réponse ni dans un journal quand
    la forme courte suffit à identifier la ligne.
    """
    valeur = endpoint or ""
    return valeur if len(valeur) <= longueur else valeur[:longueur] + "…"


# ============================================================
# ABONNEMENT PRÊT À L'ENVOI
# ============================================================


@dataclass(frozen=True)
class AbonnementPush:
    """Un abonnement tel que l'envoi 6.5 le consomme.

    L'envoi (`notifications._envoyer_webpush`) lit `.endpoint`, `.cle_p256dh`
    et `.cle_auth`. Cette forme normalisée lui rend les deux tables
    interchangeables sans modifier une ligne de la tâche 6.5.
    """

    endpoint: str
    cle_p256dh: str
    cle_auth: str
    #: 'public' (widget) ou 'admin' (route d'administration de la tâche 6.5).
    source: str
    identifiant: Optional[int] = None
    conversation_id: Optional[str] = None
    site_id: Optional[str] = None


def _depuis_publique(ligne: PushSubscription) -> AbonnementPush:
    return AbonnementPush(
        endpoint=ligne.endpoint,
        cle_p256dh=ligne.keys_p256dh,
        cle_auth=ligne.keys_auth,
        source="public",
        identifiant=ligne.id,
        conversation_id=ligne.conversation_id,
        site_id=ligne.site_id,
    )


def _depuis_admin(ligne: ChatbotPushSubscription) -> AbonnementPush:
    return AbonnementPush(
        endpoint=ligne.endpoint,
        cle_p256dh=ligne.cle_p256dh,
        cle_auth=ligne.cle_auth,
        source="admin",
        identifiant=ligne.id,
        site_id=ligne.site_id,
    )


def abonnements_actifs(db, site_id: Optional[str] = None) -> List[AbonnementPush]:
    """Tous les abonnements actifs, les deux tables confondues, dédoublonnés.

    En cas de doublon sur `endpoint`, la ligne PUBLIQUE gagne : c'est celle que
    le navigateur met à jour lui-même, donc la plus récente.

    Ne lève jamais : une table absente ou illisible donne une liste vide
    (l'envoi dira alors « aucun abonnement actif », ce qui est un état, pas une
    panne).
    """
    trouves: List[AbonnementPush] = []
    vus: set = set()

    try:
        lignes = (
            db.query(PushSubscription)
            .filter(PushSubscription.actif.is_(True))
            .order_by(PushSubscription.id.asc())
            .all()
        )
        for ligne in lignes:
            if site_id and ligne.site_id and ligne.site_id != site_id:
                continue
            trouves.append(_depuis_publique(ligne))
            vus.add(ligne.endpoint)
    except Exception:  # pragma: no cover - filet : table absente en production
        db.rollback()

    try:
        lignes_admin = (
            db.query(ChatbotPushSubscription)
            .filter(ChatbotPushSubscription.est_actif.is_(True))
            .order_by(ChatbotPushSubscription.id.asc())
            .all()
        )
        for ligne in lignes_admin:
            if ligne.endpoint in vus:
                continue
            if site_id and ligne.site_id and ligne.site_id != site_id:
                continue
            trouves.append(_depuis_admin(ligne))
            vus.add(ligne.endpoint)
    except Exception:  # pragma: no cover - filet
        db.rollback()

    return trouves


# ============================================================
# ENREGISTREMENT ET DÉSABONNEMENT
# ============================================================


def enregistrer(
    db,
    *,
    endpoint: str,
    cle_p256dh: str,
    cle_auth: str,
    conversation_id: Optional[str] = None,
    site_id: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[PushSubscription, bool]:
    """Enregistre un abonnement. Renvoie (ligne, créée ?).

    Un même `endpoint` réabonné MET À JOUR sa ligne au lieu d'en créer une
    seconde : `endpoint` est unique en base, un doublon ferait échouer
    l'insertion. C'est aussi ce qui répare le cas normal du navigateur qui
    régénère ses clés, et celui du visiteur qui se réabonne après s'être
    désabonné (la ligne passe de nouveau à `actif = vrai`).

    `date_creation` n'est jamais réécrite : c'est la date du PREMIER
    abonnement. Le suivi de la vie de l'abonnement, c'est
    `date_derniere_utilisation`.
    """
    existant = (
        db.query(PushSubscription)
        .filter(PushSubscription.endpoint == endpoint)
        .first()
    )
    if existant is not None:
        _mettre_a_jour(existant, cle_p256dh, cle_auth, conversation_id, site_id, user_agent)
        db.commit()
        db.refresh(existant)
        return existant, False

    ligne = PushSubscription(
        endpoint=endpoint,
        keys_p256dh=cle_p256dh,
        keys_auth=cle_auth,
        conversation_id=conversation_id,
        site_id=site_id,
        user_agent=user_agent,
        actif=True,
    )
    db.add(ligne)
    try:
        db.commit()
    except IntegrityError:
        # Deux abonnements du même endpoint ont été traités en parallèle : le
        # premier a gagné, le second met à jour la ligne gagnante. Sans ce
        # rattrapage, une simple course produirait un 500.
        db.rollback()
        existant = (
            db.query(PushSubscription)
            .filter(PushSubscription.endpoint == endpoint)
            .first()
        )
        if existant is None:
            raise
        _mettre_a_jour(existant, cle_p256dh, cle_auth, conversation_id, site_id, user_agent)
        db.commit()
        db.refresh(existant)
        return existant, False

    db.refresh(ligne)
    return ligne, True


def _mettre_a_jour(
    ligne: PushSubscription,
    cle_p256dh: str,
    cle_auth: str,
    conversation_id: Optional[str],
    site_id: Optional[str],
    user_agent: Optional[str],
) -> None:
    """Applique un réabonnement à une ligne existante.

    Les champs de contexte ne sont écrasés que s'ils sont FOURNIS : un
    réabonnement qui ne transmet pas de `conversation_id` ne doit pas effacer
    celui qui permet de rattacher l'abonnement à un échange.
    """
    ligne.keys_p256dh = cle_p256dh
    ligne.keys_auth = cle_auth
    if conversation_id:
        ligne.conversation_id = conversation_id
    if site_id:
        ligne.site_id = site_id
    if user_agent:
        ligne.user_agent = user_agent
    ligne.actif = True


def desabonner(
    db,
    *,
    endpoint: str,
    conversation_id: Optional[str] = None,
) -> Tuple[int, int]:
    """Désabonne un endpoint. Renvoie (désactivés publics, désactivés admin).

    La ligne passe à `actif = faux`, elle n'est PAS supprimée : la trace sert au
    diagnostic. L'opération est idempotente — un second appel ne change rien et
    ne lève pas.

    `conversation_id` est une condition SUPPLÉMENTAIRE optionnelle, jamais un
    moyen de viser l'abonnement d'un autre : sans l'`endpoint` exact, aucune
    ligne n'est touchée.

    Les deux tables sont traitées : si le même navigateur a une ligne des deux
    côtés, se désabonner d'un seul laisserait le visiteur recevoir encore des
    notifications — c'est-à-dire exactement ce qu'il a demandé d'arrêter.
    """
    publics = 0
    try:
        requete = db.query(PushSubscription).filter(
            PushSubscription.endpoint == endpoint,
            PushSubscription.actif.is_(True),
        )
        if conversation_id:
            requete = requete.filter(PushSubscription.conversation_id == conversation_id)
        for ligne in requete.all():
            ligne.actif = False
            publics += 1
    except Exception:  # pragma: no cover - filet
        db.rollback()

    admins = 0
    try:
        requete = db.query(ChatbotPushSubscription).filter(
            ChatbotPushSubscription.endpoint == endpoint,
            ChatbotPushSubscription.est_actif.is_(True),
        )
        for ligne in requete.all():
            ligne.est_actif = False
            admins += 1
    except Exception:  # pragma: no cover - filet
        db.rollback()

    db.commit()
    return publics, admins


def marquer_utilisation(db, abonnements: Iterable[AbonnementPush]) -> int:
    """Horodate `date_derniere_utilisation` des abonnements PUBLICS tentés.

    Appelé après un envoi qui a abouti au moins une fois. La tâche 6.5 ne dit
    pas QUEL abonnement a reçu le message (elle rend un total) : la date marque
    donc les abonnements effectivement présentés à un envoi qui a abouti, et non
    ceux dont la livraison est prouvée. C'est suffisant pour repérer un
    abonnement qui ne sert plus, et c'est exactement ce qu'on lui demande.

    La table d'administration n'est pas touchée : elle a ses propres colonnes et
    la tâche 6.5 n'y écrit pas — on ne modifie pas un comportement livré.
    """
    horodatage = datetime.utcnow()
    identifies: List[int] = [
        abonnement.identifiant
        for abonnement in abonnements
        if abonnement.source == "public" and abonnement.identifiant is not None
    ]
    if not identifies:
        return 0

    # `in_()` sur une liste : SQLAlchemy développe la liste en paramètres liés
    # (`IN (%s, %s, …)`), ce que psycopg2 accepte. C'est le `= ANY(:liste)` en
    # SQL brut qui échoue — d'où l'absence de SQL brut ici.
    lignes = (
        db.query(PushSubscription)
        .filter(PushSubscription.id.in_(identifies))
        .all()
    )
    for ligne in lignes:
        ligne.date_derniere_utilisation = horodatage
    if lignes:
        db.commit()
    return len(lignes)


def compter_actifs(db) -> Tuple[int, int]:
    """(abonnements publics actifs, abonnements admin actifs). Jamais d'erreur."""
    from sqlalchemy import func

    publics = 0
    admins = 0
    try:
        publics = (
            db.query(func.count(PushSubscription.id))
            .filter(PushSubscription.actif.is_(True))
            .scalar()
            or 0
        )
    except Exception:  # pragma: no cover - filet : table absente
        db.rollback()
    try:
        admins = (
            db.query(func.count(ChatbotPushSubscription.id))
            .filter(ChatbotPushSubscription.est_actif.is_(True))
            .scalar()
            or 0
        )
    except Exception:  # pragma: no cover - filet
        db.rollback()
    return publics, admins


def vers_api(ligne: PushSubscription) -> dict:
    """Forme publique d'une ligne. Ni l'endpoint complet, ni les clés."""
    return {
        "id": ligne.id,
        "endpoint_tronque": tronquer_endpoint(ligne.endpoint),
        "conversation_id": ligne.conversation_id,
        "site_id": ligne.site_id,
        "actif": bool(ligne.actif),
        "date_creation": ligne.date_creation.isoformat() if ligne.date_creation else None,
        "date_derniere_utilisation": (
            ligne.date_derniere_utilisation.isoformat()
            if ligne.date_derniere_utilisation
            else None
        ),
        "user_agent": (ligne.user_agent or None),
    }


#: Types exportés pour les tests et les routes.
__all__: Sequence[str] = (
    "AbonnementPush",
    "FOURNISSEURS_PAR_DEFAUT",
    "LONGUEUR_ENDPOINT_MAX",
    "LONGUEUR_MIN_AUTH",
    "LONGUEUR_MIN_P256DH",
    "abonnements_actifs",
    "compter_actifs",
    "desabonner",
    "enregistrer",
    "fournisseurs_autorises",
    "marquer_utilisation",
    "tronquer_endpoint",
    "valider_cle",
    "valider_endpoint",
    "vers_api",
)

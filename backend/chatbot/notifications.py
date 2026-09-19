"""
Notifications du chatbot Mia — tâche 6.5.

PRINCIPE DIRECTEUR : RIEN NE DOIT POUVOIR EMPÊCHER LE DÉMARRAGE
---------------------------------------------------------------
Le backend a déjà subi une panne de production à cause d'un import manquant.
Ce module est donc écrit pour qu'un canal absent, une clé absente, une
bibliothèque absente ou un fournisseur injoignable ne puissent produire qu'UNE
chose : un état lisible. Aucune exception ne remonte, aucun import optionnel
n'est fait au chargement du module.

Règles appliquées, sans exception :
  1. Aucun import de bibliothèque optionnelle au niveau du module. `pywebpush`
     (push navigateur) est importé À L'INTÉRIEUR de la fonction qui en a besoin,
     et son absence est un état, pas une erreur.
  2. Aucun appel réseau au chargement. Rien n'est testé au démarrage : les
     états sont calculés à la demande, sur la seule présence des variables
     d'environnement — pas en joignant le fournisseur.
  3. Chaque envoi est TRACÉ en base (canal, destinataire, date, succès/échec,
     code et message d'erreur). C'est la trace qui permettra de diagnostiquer
     un envoi perdu, ce que le propriétaire ne peut pas faire aujourd'hui.

ÉTAT RÉEL DES CANAUX, MESURÉ LE 2026-09-18 (détail dans le rapport de tâche)
---------------------------------------------------------------------------
  · Telegram      : CONFIGURÉ et VÉRIFIÉ EN FONCTIONNEMENT. `getMe` sur le
                    jeton de production répond HTTP 200 (bot « ePerformance
                    système »). C'est le canal d'envoi réellement utilisable
                    aujourd'hui.
  · E-mail (Brevo): CONFIGURÉ mais EN ÉCHEC depuis cette machine. La clé est
                    présente en production, mais Brevo refuse l'adresse IP
                    émettrice : HTTP 401 « unrecognised IP address ». C'est le
                    cas « configuré mais l'envoi échoue » — tracé, jamais fatal.
  · Push navigateur: NON CONFIGURÉ. Aucune clé VAPID en production et la
                    bibliothèque `pywebpush` n'est pas installée. C'est le cas
                    « non configuré » : les endpoints répondent un état
                    explicite et rien ne plante.
  · WhatsApp      : CONFIGURÉ (jeton d'accès présent) mais non vérifié ici.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================
# DÉLAIS ET LIMITES
# ============================================================

#: Délai d'un appel à un fournisseur. Court : une notification qui met 30 s à
#: échouer est une notification qui bloque un humain.
DELAI_ENVOI = float(os.getenv("NOTIF_TIMEOUT", "15"))
#: Longueur maximale du corps conservé dans la trace (la trace n'est pas une
#: archive de contenu : elle dit CE QUI a été envoyé et SI c'est parti).
TRACE_CORPS_MAX = int(os.getenv("NOTIF_TRACE_CORPS", "500"))

#: Canaux connus. L'ordre est celui de la préférence par défaut. `rcs` est
#: pré-implémenté (interface abstraite texte + cartes) mais INACTIF par
#: défaut : sans RCS_ENABLED=true, le canal répond « désactivé » et tout
#: envoi renvoie un état explicite — aucune exception, aucun appel réseau
#: (fondations d'extensibilité, Missions 3-4).
CANAUX = ("telegram", "email", "webpush", "whatsapp", "rcs")

#: Templates WhatsApp structurés (Métier : notifications proactives = OBLIGE
#: à passer par des templates pré-approuvés dans Meta Business Manager —
#: catégorie UTILITY pour le transactionnel). L'activation du canal est
#: portée par WHATSAPP_ENABLED ; ces templates ne servent qu'une fois le
#: canal actif. Les noms doivent correspondre à des templates créés et
#: approuvés côté Meta (guide : backend/communication/providers/
#: whatsapp_provider.py — la référence d'implémentation du canal reste CE
#: module, voir la note d'héritage dans le provider).
TEMPLATES_WHATSAPP: Dict[str, Dict[str, str]] = {
    "nouveau_lead": {
        "nom": "mia_nouveau_lead",
        "langue": "fr",
        "categorie": "UTILITY",
        "description": "Nouveau lead capturé par Mia sur le site du propriétaire",
        "variables": ["nom du visiteur", "nom du site", "résumé de la demande"],
    },
    "escalade": {
        "nom": "mia_escalade",
        "langue": "fr",
        "categorie": "UTILITY",
        "description": "Escalade : un visiteur demande à parler à un humain",
        "variables": ["nom du site", "nom du visiteur", "sujet"],
    },
}


def template_whatsapp(type_evenement: str, variables: List[str]) -> Dict:
    """
    Construit le paramètre `template` de `envoyer(canal="whatsapp", …)` pour
    un événement connu (nouveau_lead, escalade). Lève ValueError pour un type
    inconnu — c'est un défaut d'appel, pas un état d'envoi.
    """
    spec = TEMPLATES_WHATSAPP.get(type_evenement)
    if spec is None:
        raise ValueError(
            f"template WhatsApp inconnu : « {type_evenement} ». Connus : "
            f"{', '.join(sorted(TEMPLATES_WHATSAPP))}"
        )
    return {"nom": spec["nom"], "langue": spec["langue"], "variables": list(variables or [])}


# ============================================================
# ÉTAT D'UN CANAL
# ============================================================


@dataclass
class EtatCanal:
    """État d'un canal : configuré ou non, et pourquoi — en clair."""

    canal: str
    configure: bool
    raison: str
    #: Détail non sensible, pour le diagnostic (jamais de clé, jamais de secret).
    detail: Dict[str, str] = field(default_factory=dict)

    def pour_api(self) -> Dict:
        return {
            "canal": self.canal,
            "configure": self.configure,
            "raison": self.raison,
            "detail": self.detail,
        }


def _variable(nom: str) -> str:
    return (os.getenv(nom) or "").strip()


def etat_canal(canal: str) -> EtatCanal:
    """État d'un canal, calculé SANS aucun appel réseau.

    On ne teste pas la validité de la clé ici : un état « configuré » signifie
    « les variables sont là », pas « le fournisseur répond ». Confondre les
    deux ferait échouer un endpoint de diagnostic quand le fournisseur est
    lent, ce qui est exactement le défaut qu'on veut éviter.
    """
    if canal == "telegram":
        jeton = _variable("TELEGRAM_BOT_TOKEN")
        destinataire = _variable("TELEGRAM_ADMIN_CHAT_ID")
        if jeton and destinataire:
            return EtatCanal(
                "telegram",
                True,
                "configuré (jeton et destinataire présents)",
                {"destinataire_par_defaut": "oui"},
            )
        manquantes = [
            nom
            for nom, valeur in (
                ("TELEGRAM_BOT_TOKEN", jeton),
                ("TELEGRAM_ADMIN_CHAT_ID", destinataire),
            )
            if not valeur
        ]
        return EtatCanal(
            "telegram",
            False,
            f"non configuré : {', '.join(manquantes)} manquant(s)",
        )

    if canal == "email":
        cle = _variable("BREVO_API_KEY")
        expediteur = _variable("BREVO_SENDER_EMAIL")
        if cle and expediteur:
            return EtatCanal(
                "email",
                True,
                "configuré (clé Brevo et expéditeur présents)",
                {"expediteur": expediteur},
            )
        manquantes = [
            nom
            for nom, valeur in (
                ("BREVO_API_KEY", cle),
                ("BREVO_SENDER_EMAIL", expediteur),
            )
            if not valeur
        ]
        return EtatCanal(
            "email",
            False,
            f"non configuré : {', '.join(manquantes)} manquant(s)",
        )

    if canal == "webpush":
        publique = _variable("VAPID_PUBLIC_KEY")
        privee = _variable("VAPID_PRIVATE_KEY")
        contact = _variable("VAPID_CONTACT") or _variable("BREVO_SENDER_EMAIL")
        manquantes = [
            nom
            for nom, valeur in (
                ("VAPID_PUBLIC_KEY", publique),
                ("VAPID_PRIVATE_KEY", privee),
            )
            if not valeur
        ]
        if manquantes:
            return EtatCanal(
                "webpush",
                False,
                "non configuré : "
                f"{', '.join(manquantes)} manquant(s) — le propriétaire n'a pas "
                "encore créé les clés VAPID du push navigateur",
            )
        # Clés présentes : reste à savoir si la bibliothèque est là. On le
        # vérifie par une recherche de spécification, qui n'importe RIEN.
        import importlib.util

        if importlib.util.find_spec("pywebpush") is None:
            return EtatCanal(
                "webpush",
                False,
                "clés présentes mais bibliothèque absente : ajouter "
                "'pywebpush' à requirements.txt puis redéployer",
            )
        return EtatCanal(
            "webpush",
            True,
            "configuré (clés VAPID et bibliothèque présentes)",
            {"contact": contact or "non renseigné"},
        )

    if canal == "whatsapp":
        # FONDATIONS (Mission 3) : le canal est pré-implémenté (Meta Cloud
        # API) mais INACTIF PAR DÉFAUT — tant que WHATSAPP_ENABLED n'est pas
        # à `true`, l'état est « désactivé » et tout envoi renvoie cet état
        # SANS appel réseau, même si les clés sont présentes. Poser les clés
        # ET basculer le flag active le canal sans aucun changement de code.
        if _variable("WHATSAPP_ENABLED").lower() != "true":
            return EtatCanal(
                "whatsapp",
                False,
                "non configuré : canal DÉSACTIVÉ — WHATSAPP_ENABLED n'est pas "
                "à true (pré-implémenté, Meta Cloud API, inactif par défaut ; "
                "activation : clés + flag, cf. docs/refonte-app-mia/"
                "EXTENSIBILITE.md)",
            )
        jeton = _variable("WHATSAPP_ACCESS_TOKEN")
        numero = _variable("WHATSAPP_PHONE_NUMBER_ID")
        if jeton and numero:
            return EtatCanal("whatsapp", True, "configuré (WHATSAPP_ENABLED=true, jeton et numéro présents)")
        manquantes = [
            nom
            for nom, valeur in (
                ("WHATSAPP_ACCESS_TOKEN", jeton),
                ("WHATSAPP_PHONE_NUMBER_ID", numero),
            )
            if not valeur
        ]
        return EtatCanal(
            "whatsapp",
            False,
            f"non configuré : {', '.join(manquantes)} manquant(s) "
            "(WHATSAPP_ENABLED=true mais clés absentes)",
        )

    if canal == "rcs":
        # FONDATIONS (Mission 4) : interface abstraite pré-implémentée
        # (texte + cartes riches en JSON), INACTIVE par défaut. Aucun accès
        # Google n'existe encore : les variables restent vides, l'état est
        # explicite, le fallback SMS est DÉCLARATIF (RCS_FALLBACK_SMS).
        if _variable("RCS_ENABLED").lower() != "true":
            return EtatCanal(
                "rcs",
                False,
                "non configuré : canal DÉSACTIVÉ — RCS_ENABLED n'est pas à "
                "true (pré-implémenté : texte + cartes riches, inactif par "
                "défaut ; fallback SMS déclaratif via RCS_FALLBACK_SMS)",
            )
        agent = _variable("RCS_AGENT_ID")
        url = _variable("RCS_API_URL")
        cle = _variable("RCS_API_KEY")
        manquantes = [
            nom
            for nom, valeur in (
                ("RCS_AGENT_ID", agent),
                ("RCS_API_URL", url),
                ("RCS_API_KEY", cle),
            )
            if not valeur
        ]
        if manquantes:
            return EtatCanal(
                "rcs",
                False,
                f"non configuré : {', '.join(manquantes)} manquant(s) "
                "(RCS_ENABLED=true mais accès Google absent)",
            )
        return EtatCanal(
            "rcs",
            True,
            "configuré (RCS_ENABLED=true, agent et API présents)",
            {"fallback_sms": "déclaratif" if _variable("RCS_FALLBACK_SMS").lower() == "true" else "non déclaré"},
        )

    return EtatCanal(canal, False, f"canal inconnu : {canal}")


def etat_canaux() -> List[EtatCanal]:
    """État de tous les canaux connus — jamais d'exception."""
    etats = []
    for canal in CANAUX:
        try:
            etats.append(etat_canal(canal))
        except Exception as exc:  # pragma: no cover - filet
            logger.warning("État du canal %s illisible (%s)", canal, exc)
            etats.append(EtatCanal(canal, False, f"état illisible : {type(exc).__name__}"))
    return etats


# ============================================================
# RÉSULTAT D'UN ENVOI
# ============================================================


@dataclass
class ResultatEnvoi:
    """Ce qu'un envoi a produit, quel qu'il soit — jamais une exception."""

    canal: str
    succes: bool
    statut: str  # 'envoye' | 'echec' | 'non_configure'
    destinataire: str
    messages_envoyes: int = 0
    identifiant_fournisseur: Optional[str] = None
    code_erreur: Optional[str] = None
    erreur: Optional[str] = None
    duree_ms: int = 0

    def pour_api(self) -> Dict:
        return {
            "canal": self.canal,
            "succes": self.succes,
            "statut": self.statut,
            "destinataire": self.destinataire,
            "messages_envoyes": self.messages_envoyes,
            "identifiant_fournisseur": self.identifiant_fournisseur,
            "code_erreur": self.code_erreur,
            "erreur": self.erreur,
            "duree_ms": self.duree_ms,
        }


def _extrait(texte: str, longueur: int = TRACE_CORPS_MAX) -> str:
    texte = texte or ""
    return texte if len(texte) <= longueur else texte[:longueur] + " […]"


# ============================================================
# ENVOIS — UNE FONCTION PAR CANAL, AUCUNE DÉPENDANCE AU CHARGEMENT
# ============================================================


def _envoyer_telegram(destinataire: str, sujet: str, message: str) -> ResultatEnvoi:
    """Envoi Telegram (API Bot, HTTP JSON). Vérifié en fonctionnement."""
    import requests  # dépendance du projet, pas optionnelle

    jeton = _variable("TELEGRAM_BOT_TOKEN")
    cible = destinataire or _variable("TELEGRAM_ADMIN_CHAT_ID")
    texte = f"{sujet}\n\n{message}" if sujet else message

    reponse = requests.post(
        f"https://api.telegram.org/bot{jeton}/sendMessage",
        json={"chat_id": cible, "text": texte, "disable_web_page_preview": True},
        timeout=DELAI_ENVOI,
    )
    donnees = {}
    try:
        donnees = reponse.json()
    except Exception:
        donnees = {}

    if reponse.status_code == 200 and donnees.get("ok"):
        return ResultatEnvoi(
            canal="telegram",
            succes=True,
            statut="envoye",
            destinataire=cible,
            messages_envoyes=1,
            identifiant_fournisseur=str((donnees.get("result") or {}).get("message_id")),
        )

    # Telegram met le motif dans `description` : on le remonte tel quel, c'est
    # ce qui permettra de comprendre un refus (« chat not found », etc.).
    motif = donnees.get("description") or f"HTTP {reponse.status_code}"
    return ResultatEnvoi(
        canal="telegram",
        succes=False,
        statut="echec",
        destinataire=cible,
        code_erreur=str(reponse.status_code),
        erreur=motif,
    )


def _envoyer_email(destinataire: str, sujet: str, message: str) -> ResultatEnvoi:
    """Envoi e-mail par l'API Brevo (v3, HTTP JSON)."""
    import requests

    cle = _variable("BREVO_API_KEY")
    expediteur = _variable("BREVO_SENDER_EMAIL")
    nom_expediteur = _variable("BREVO_SENDER_NAME") or "ePerformance"

    # RÉPARÉ LE 19/09 : sans destinataire explicite, le payload partait avec
    # `to: [{"email": ""}]` et Brevo répondait 400 « email is missing in to » —
    # présenté comme un 502 « échec » alors que la configuration était incomplète,
    # pas fausse. Le destinataire par défaut est BREVO_NOTIF_EMAIL ; sans lui,
    # le canal répond « non configuré » (même philosophie que les autres canaux) :
    # un état explicite vaut mieux qu'un échec d'envoi qui ne dit pas sa cause.
    if not destinataire:
        destinataire = _variable("BREVO_NOTIF_EMAIL")
    if not destinataire:
        return ResultatEnvoi(
            canal="email",
            succes=False,
            statut="non_configure",
            destinataire="",
            code_erreur=None,
            erreur="aucun destinataire : passez `destinataire` ou définissez BREVO_NOTIF_EMAIL",
        )

    corps_html = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    corps_html = corps_html.replace("\n", "<br>")
    corps_html = (
        '<div style="font-family:system-ui,sans-serif;font-size:15px;'
        f'line-height:1.6">{corps_html}</div>'
    )

    reponse = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={
            "accept": "application/json",
            "api-key": cle,
            "content-type": "application/json",
        },
        data=json.dumps(
            {
                "sender": {"email": expediteur, "name": nom_expediteur},
                "to": [{"email": destinataire}],
                "subject": sujet or "Notification ePerformance",
                "htmlContent": corps_html,
            }
        ).encode("utf-8"),
        timeout=DELAI_ENVOI,
    )

    if reponse.status_code in (200, 201, 202):
        identifiant = None
        try:
            identifiant = (reponse.json() or {}).get("messageId")
        except Exception:
            pass
        return ResultatEnvoi(
            canal="email",
            succes=True,
            statut="envoye",
            destinataire=destinataire,
            messages_envoyes=1,
            identifiant_fournisseur=identifiant,
        )

    motif = f"HTTP {reponse.status_code}"
    try:
        donnees = reponse.json() or {}
        # Brevo renvoie {"message": "...", "code": "..."} : le message est
        # l'information utile (ici : « unrecognised IP address »).
        motif = f"{donnees.get('code', '')} {donnees.get('message', '')}".strip() or motif
    except Exception:
        pass
    return ResultatEnvoi(
        canal="email",
        succes=False,
        statut="echec",
        destinataire=destinataire,
        code_erreur=str(reponse.status_code),
        erreur=_extrait(motif, 300),
    )


def _envoyer_webpush(destinataire: str, sujet: str, message: str, abonnements=None) -> ResultatEnvoi:
    """Push navigateur (Web Push, chiffrement RFC 8291 via `pywebpush`).

    `pywebpush` n'est PAS importé au chargement du module : c'est la règle qui
    évite la panne de démarrage déjà connue sur ce backend. Ici, l'import est
    tenté à l'usage ; son échec est un résultat, pas une exception.

    Le jour où le propriétaire fournira des clés VAPID, il faudra aussi ajouter
    `pywebpush` à requirements.txt — les deux conditions sont nécessaires, et
    l'état du canal le dit explicitement.
    """
    # Import TARDIF, volontairement dans un try : une bibliothèque absente ne
    # doit pas empêcher le backend de démarrer.
    try:
        from pywebpush import webpush, WebPushException  # type: ignore
    except Exception:
        return ResultatEnvoi(
            canal="webpush",
            succes=False,
            statut="non_configure",
            destinataire=destinataire,
            erreur=(
                "bibliothèque 'pywebpush' absente : ajouter la dépendance à "
                "requirements.txt puis redéployer"
            ),
        )

    publique = _variable("VAPID_PUBLIC_KEY")
    privee = _variable("VAPID_PRIVATE_KEY")
    contact = _variable("VAPID_CONTACT") or _variable("BREVO_SENDER_EMAIL")
    if not (publique and privee):
        return ResultatEnvoi(
            canal="webpush",
            succes=False,
            statut="non_configure",
            destinataire=destinataire,
            erreur="clés VAPID absentes (VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY)",
        )

    cibles = list(abonnements or [])
    if not cibles:
        return ResultatEnvoi(
            canal="webpush",
            succes=False,
            statut="echec",
            destinataire=destinataire,
            erreur="aucun abonnement actif à notifier",
        )

    charge = json.dumps({"title": sujet or "ePerformance", "body": message})
    envoyes = 0
    erreurs: List[str] = []
    for abonnement in cibles:
        try:
            webpush(
                subscription_info={
                    "endpoint": abonnement.endpoint,
                    "keys": {"p256dh": abonnement.cle_p256dh, "auth": abonnement.cle_auth},
                },
                data=charge,
                vapid_private_key=privee,
                vapid_claims={"sub": f"mailto:{contact}"},
                timeout=DELAI_ENVOI,
            )
            envoyes += 1
        except WebPushException as exc:  # type: ignore
            # Un abonnement expiré (404/410) est normal : il sera désactivé par
            # l'appelant, il ne doit pas faire échouer les autres.
            erreurs.append(_extrait(str(exc), 200))
        except Exception as exc:  # pragma: no cover - filet
            erreurs.append(_extrait(f"{type(exc).__name__}: {exc}", 200))

    if envoyes:
        return ResultatEnvoi(
            canal="webpush",
            succes=True,
            statut="envoye",
            destinataire=destinataire or f"{envoyes} abonnement(s)",
            messages_envoyes=envoyes,
            erreur="; ".join(erreurs) if erreurs else None,
        )
    return ResultatEnvoi(
        canal="webpush",
        succes=False,
        statut="echec",
        destinataire=destinataire,
        erreur="; ".join(erreurs) or "aucun envoi n'a abouti",
    )


def _envoyer_whatsapp(
    destinataire: str,
    sujet: str,
    message: str,
    template: Optional[Dict] = None,
) -> ResultatEnvoi:
    """Envoi WhatsApp (API Cloud de Meta) — texte libre ou template structuré.

    RÉFÉRENCE UNIQUE DU CANAL (fondations, Mission 3) : la notification Mia
    passe par ICI. Le provider historique de la Phase 1
    (backend/communication/providers/whatsapp_provider.py) est conservé pour
    le service de communication existant mais n'est plus une deuxième
    implémentation d'envoi pour Mia — deux implémentations du même canal
    seraient un défaut silencieux.

    · Template structuré (template = {"nom", "langue", "variables"}) :
      notification PROACTIVE — Meta impose des templates pré-approuvés
      (catégorie UTILITY) hors de la fenêtre de 24 h ;
    · Texte libre : uniquement dans la fenêtre de 24 h après un message du
      destinataire.

    Le destinataire par défaut est WHATSAPP_NOTIF_DESTINATAIRE (même motif
    que BREVO_NOTIF_EMAIL pour l'e-mail) : sans lui, le canal répond
    « non configuré » — un état explicite vaut mieux qu'un échec d'envoi qui
    ne dit pas sa cause.
    """
    import requests

    jeton = _variable("WHATSAPP_ACCESS_TOKEN")
    numero = _variable("WHATSAPP_PHONE_NUMBER_ID")

    if not destinataire:
        destinataire = _variable("WHATSAPP_NOTIF_DESTINATAIRE")
    if not destinataire:
        return ResultatEnvoi(
            canal="whatsapp",
            succes=False,
            statut="non_configure",
            destinataire="",
            code_erreur=None,
            erreur="aucun destinataire : passez `destinataire` ou définissez "
                   "WHATSAPP_NOTIF_DESTINATAIRE",
        )

    if template:
        # Payload template Meta Cloud API (variables numérotées {{1}}, {{2}}…).
        charge = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": destinataire.lstrip("+"),
            "type": "template",
            "template": {
                "name": template.get("nom"),
                "language": {"code": template.get("langue", "fr")},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": str(valeur)}
                            for valeur in template.get("variables", [])
                        ],
                    }
                ],
            },
        }
    else:
        texte = f"{sujet}\n\n{message}" if sujet else message
        charge = {
            "messaging_product": "whatsapp",
            "to": destinataire,
            "type": "text",
            "text": {"body": texte},
        }

    reponse = requests.post(
        f"https://graph.facebook.com/v21.0/{numero}/messages",
        headers={
            "Authorization": f"Bearer {jeton}",
            "Content-Type": "application/json",
        },
        data=json.dumps(charge).encode("utf-8"),
        timeout=DELAI_ENVOI,
    )

    if reponse.status_code in (200, 201):
        identifiant = None
        try:
            identifiant = (
                ((reponse.json() or {}).get("messages") or [{}])[0].get("id")
            )
        except Exception:
            pass
        return ResultatEnvoi(
            canal="whatsapp",
            succes=True,
            statut="envoye",
            destinataire=destinataire,
            messages_envoyes=1,
            identifiant_fournisseur=identifiant,
        )

    motif = f"HTTP {reponse.status_code}"
    try:
        donnees = reponse.json() or {}
        erreur = donnees.get("error") or {}
        motif = erreur.get("message") or erreur.get("code") or motif
    except Exception:
        pass
    return ResultatEnvoi(
        canal="whatsapp",
        succes=False,
        statut="echec",
        destinataire=destinataire,
        code_erreur=str(reponse.status_code),
        erreur=_extrait(str(motif), 300),
    )


def _charge_rcs(sujet: str, message: str, cartes: Optional[List[Dict]]) -> Dict:
    """
    Structure JSON de message RCS — INTERFACE ABSTRAITE, indépendante du
    fournisseur final (le choix Google RBM / autre n'est pas fait ; l'URL et
    l'agent sont configurables). Texte + cartes riches, structure déclarée :

        {"texte": str, "cartes": [{"titre", "sous_titre", "media_url",
                                   "suggestions": [{"type", "texte", "valeur"}]}]}

    C'est cette structure que l'appelant produit ; l'adaptateur fournisseur
    (à écrire à l'activation) la traduit au format réel — un seul endroit à
    toucher, cf. docs/refonte-app-mia/EXTENSIBILITE.md.
    """
    return {
        "texte": f"{sujet}\n\n{message}" if sujet else message,
        "cartes": list(cartes or []),
    }


def _envoyer_rcs(
    destinataire: str,
    sujet: str,
    message: str,
    cartes: Optional[List[Dict]] = None,
) -> ResultatEnvoi:
    """
    Envoi RCS (interface abstraite : texte + cartes riches, Mission 4).

    Le canal est INACTIF PAR DÉFAUT (RCS_ENABLED) : `envoyer()` contrôle
    l'état AVANT d'appeler cette fonction, donc sans clés il n'y a AUCUN
    appel réseau et AUCUNE exception — le canal répond « non configuré ».

    FALLBACK SMS DÉCLARATIF : si RCS_FALLBACK_SMS=true et que l'envoi
    échoue, le résultat le NOTE explicitement. La bascule d'envoi effective
    vers SMS est déclarée dans la structure mais NON implémentée tant que le
    fournisseur final n'est pas choisi — jamais de réussite annoncée à tort.
    """
    import requests

    agent = _variable("RCS_AGENT_ID")
    url = _variable("RCS_API_URL")
    cle = _variable("RCS_API_KEY")
    fallback_declare = _variable("RCS_FALLBACK_SMS").lower() == "true"

    charge = {
        "agent_id": agent,
        "destinataire": destinataire,
        "message": _charge_rcs(sujet, message, cartes),
    }

    reponse = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {cle}",
            "Content-Type": "application/json",
        },
        data=json.dumps(charge).encode("utf-8"),
        timeout=DELAI_ENVOI,
    )

    if reponse.status_code in (200, 201, 202):
        identifiant = None
        try:
            identifiant = (reponse.json() or {}).get("message_id")
        except Exception:
            pass
        return ResultatEnvoi(
            canal="rcs",
            succes=True,
            statut="envoye",
            destinataire=destinataire,
            messages_envoyes=1,
            identifiant_fournisseur=identifiant,
        )

    motif = f"HTTP {reponse.status_code}"
    try:
        motif = str((reponse.json() or {}).get("error") or motif)
    except Exception:
        pass
    if fallback_declare:
        motif += " — fallback SMS DÉCLARÉ (RCS_FALLBACK_SMS=true) mais la "
        motif += "bascule d'envoi n'est pas implémentée tant que le fournisseur "
        motif += "final n'est pas choisi (cf. EXTENSIBILITE.md)"
    return ResultatEnvoi(
        canal="rcs",
        succes=False,
        statut="echec",
        destinataire=destinataire,
        code_erreur=str(reponse.status_code),
        erreur=_extrait(motif, 300),
    )


# ============================================================
# POINT D'ENTRÉE UNIQUE
# ============================================================

_ENVOYEURS = {
    "telegram": _envoyer_telegram,
    "email": _envoyer_email,
    "whatsapp": _envoyer_whatsapp,
    "rcs": _envoyer_rcs,
}


def envoyer(
    canal: str,
    destinataire: str,
    sujet: str,
    message: str,
    abonnements=None,
    template: Optional[Dict] = None,
    cartes: Optional[List[Dict]] = None,
) -> ResultatEnvoi:
    """Envoie une notification sur un canal. NE LÈVE JAMAIS.

    Renvoie toujours un `ResultatEnvoi` — succès, échec ou non configuré. La
    route HTTP qui appelle cette fonction n'a donc aucun cas d'erreur à gérer
    et ne peut pas renvoyer 500 à cause d'un fournisseur.

    · `template` (whatsapp) : envoi PROACTIF par template pré-approuvé Meta
      — produit par template_whatsapp(type_evenement, variables) ;
    · `cartes` (rcs) : cartes riches en structure JSON déclarative — cf.
      _charge_rcs.
    """
    debut = time.time()
    canal = (canal or "").strip().lower()

    def _finaliser(resultat: ResultatEnvoi) -> ResultatEnvoi:
        resultat.duree_ms = int((time.time() - debut) * 1000)
        return resultat

    if canal not in CANAUX:
        return _finaliser(
            ResultatEnvoi(
                canal=canal or "?",
                succes=False,
                statut="non_configure",
                destinataire=destinataire,
                erreur=f"canal inconnu : « {canal} ». Canaux acceptés : {', '.join(CANAUX)}",
            )
        )

    # 1. Le canal est-il configuré ? On le dit AVANT d'essayer, avec le motif.
    #    Pour whatsapp/rcs, « désactivé » (flag OFF) est capté ici : aucun
    #    appel réseau, aucune exception — l'état dit exactement pourquoi.
    etat = etat_canal(canal)
    if not etat.configure:
        return _finaliser(
            ResultatEnvoi(
                canal=canal,
                succes=False,
                statut="non_configure",
                destinataire=destinataire,
                erreur=etat.raison,
            )
        )

    # 2. Envoi réel. Toute exception devient un échec tracé.
    try:
        if canal == "webpush":
            return _finaliser(
                _envoyer_webpush(destinataire, sujet, message, abonnements=abonnements)
            )
        if canal == "whatsapp":
            return _finaliser(
                _envoyer_whatsapp(destinataire, sujet, message, template=template)
            )
        if canal == "rcs":
            return _finaliser(
                _envoyer_rcs(destinataire, sujet, message, cartes=cartes)
            )
        return _finaliser(_ENVOYEURS[canal](destinataire, sujet, message))
    except Exception as exc:
        logger.warning("Notification %s : échec (%s)", canal, exc, exc_info=True)
        return _finaliser(
            ResultatEnvoi(
                canal=canal,
                succes=False,
                statut="echec",
                destinataire=destinataire,
                code_erreur=type(exc).__name__,
                erreur=_extrait(str(exc), 300),
            )
        )


# ============================================================
# TRACE EN BASE
# ============================================================


def tracer(db, resultat: ResultatEnvoi, sujet: str, message: str, auteur: Optional[str] = None):
    """Écrit la trace d'un envoi (succès, échec ou non configuré).

    La trace est écrite dans TOUS les cas, y compris « non configuré » : c'est
    précisément ce cas qu'on veut pouvoir constater après coup, quand le
    propriétaire se demandera pourquoi aucune notification n'est partie.

    Ne lève jamais : une trace impossible ne doit pas transformer un échec
    d'envoi en erreur HTTP.
    """
    try:
        from .models import ChatbotNotificationLog

        ligne = ChatbotNotificationLog(
            canal=resultat.canal,
            destinataire=resultat.destinataire,
            sujet=_extrait(sujet, 200),
            corps=_extrait(message),
            statut=resultat.statut,
            succes=resultat.succes,
            code_erreur=resultat.code_erreur,
            erreur=_extrait(resultat.erreur or "", 1000) or None,
            identifiant_fournisseur=resultat.identifiant_fournisseur,
            auteur=auteur,
            duree_ms=resultat.duree_ms,
            envoye_le=datetime.utcnow(),
        )
        db.add(ligne)
        db.commit()
        return ligne
    except Exception as exc:  # pragma: no cover - filet
        logger.error("Notification : trace non écrite (%s)", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return None

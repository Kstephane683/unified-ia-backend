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

#: Canaux connus. L'ordre est celui de la préférence par défaut.
CANAUX = ("telegram", "email", "webpush", "whatsapp")


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
        jeton = _variable("WHATSAPP_ACCESS_TOKEN")
        numero = _variable("WHATSAPP_PHONE_NUMBER_ID")
        if jeton and numero:
            return EtatCanal("whatsapp", True, "configuré (jeton et numéro présents)")
        return EtatCanal(
            "whatsapp",
            False,
            "non configuré : WHATSAPP_ACCESS_TOKEN ou WHATSAPP_PHONE_NUMBER_ID manquant",
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


def _envoyer_whatsapp(destinataire: str, sujet: str, message: str) -> ResultatEnvoi:
    """Envoi WhatsApp (API Cloud de Meta, message texte)."""
    import requests

    jeton = _variable("WHATSAPP_ACCESS_TOKEN")
    numero = _variable("WHATSAPP_PHONE_NUMBER_ID")
    texte = f"{sujet}\n\n{message}" if sujet else message

    reponse = requests.post(
        f"https://graph.facebook.com/v21.0/{numero}/messages",
        headers={
            "Authorization": f"Bearer {jeton}",
            "Content-Type": "application/json",
        },
        data=json.dumps(
            {
                "messaging_product": "whatsapp",
                "to": destinataire,
                "type": "text",
                "text": {"body": texte},
            }
        ).encode("utf-8"),
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


# ============================================================
# POINT D'ENTRÉE UNIQUE
# ============================================================

_ENVOYEURS = {
    "telegram": _envoyer_telegram,
    "email": _envoyer_email,
    "whatsapp": _envoyer_whatsapp,
}


def envoyer(
    canal: str,
    destinataire: str,
    sujet: str,
    message: str,
    abonnements=None,
) -> ResultatEnvoi:
    """Envoie une notification sur un canal. NE LÈVE JAMAIS.

    Renvoie toujours un `ResultatEnvoi` — succès, échec ou non configuré. La
    route HTTP qui appelle cette fonction n'a donc aucun cas d'erreur à gérer
    et ne peut pas renvoyer 500 à cause d'un fournisseur.
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

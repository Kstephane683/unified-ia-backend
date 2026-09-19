"""
Déclencheurs de notification du propriétaire — refonte app Mia (chantier B4).

LE CONTRAT DE CE MODULE
-----------------------
Un événement métier (nouveau lead, escalade humaine, nouveau visiteur) doit
prévenir le propriétaire du site SANS jamais :
  · ralentir le visiteur — les envois partent en ARRIÈRE-PLAN (thread daemon),
    la notification in-app seule est écrite dans la transaction courante ;
  · faire échouer la conversation — toute exception est absorbée et journalisée ;
  · laisser un canal mal configuré passer pour un succès — chaque envoi passe
    par `notifications.envoyer()`, qui trace `envoye | echec | non_configure`
    dans TOUS les cas (tâche 6.5), et par les réglages par type du site.

QUI EST PRÉVENU
---------------
  · notification IN-APP (table `client_notifications`) : TOUJOURS, quel que
    soient les réglages — c'est le filet qui ne dépend d'aucune clé ;
  · webpush : les abonnements ACTIFS DU SITE (`push_subscriptions.site_id` +
    table admin, dédoublonnés — voir push_abonnements.abonnements_actifs) ;
  · e-mail : destinataires du site (`notification_recipients`, sinon le compte
    provisioné du site, sinon la valeur par défaut du canal) ;
  · Telegram : destinataire du site s'il est renseigné, sinon le chat admin
    par défaut du canal (ePerformance opère le système).

LES RÉGLAGES PAR TYPE
---------------------
`ChatbotSite.notification_settings` (JSON) : {type: {push, email, telegram}}.
Défauts sensibles : lead et escalade PRÉVENUS, nouveau visiteur SILENCIEUX
(prévenir d'une simple visite serait du bruit, pas de l'information).
Un réglage incomplet est complété par les défauts — jamais de KeyError.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.chatbot import notifications, push_abonnements
from backend.chatbot.models import ChatbotSite, ClientNotification

logger = logging.getLogger(__name__)

# Types d'événements (valeur de `client_notifications.type`).
TYPE_NOUVEAU_LEAD = "nouveau_lead"
TYPE_ESCALADE = "escalade"
TYPE_NOUVEAU_VISITEUR = "nouveau_visiteur"

TYPES_EVENEMENTS = (TYPE_NOUVEAU_LEAD, TYPE_ESCALADE, TYPE_NOUVEAU_VISITEUR)

# Défauts sensibles (consigne B4) : lead et escalade activés, visiteur désactivé.
DEFAUTS_REGLAGES: Dict[str, Dict[str, bool]] = {
    TYPE_NOUVEAU_LEAD: {"push": True, "email": True, "telegram": True},
    TYPE_ESCALADE: {"push": True, "email": True, "telegram": True},
    TYPE_NOUVEAU_VISITEUR: {"push": False, "email": False, "telegram": False},
}


def reglages_effectifs(site: Optional[ChatbotSite]) -> Dict[str, Dict[str, bool]]:
    """
    Réglages par type pour un site, complétés par les défauts.

    Le JSON stocké peut être partiel, mal typé ou absent : chaque valeur lue
    est convertie en booléen, chaque canal manquant reprend le défaut. Jamais
    d'exception pour une donnée de configuration malformée.
    """
    effectifs: Dict[str, Dict[str, bool]] = {}
    stockes = {}
    if site is not None and isinstance(site.notification_settings, dict):
        stockes = site.notification_settings
    for type_evenement, defaut in DEFAUTS_REGLAGES.items():
        cru = stockes.get(type_evenement) if isinstance(stockes.get(type_evenement), dict) else {}
        effectifs[type_evenement] = {
            canal: bool(cru.get(canal, defaut[canal]))
            for canal in ("push", "email", "telegram")
        }
    return effectifs


def _destinataires_email(site: Optional[ChatbotSite], db: Session) -> List[str]:
    """
    Destinataires e-mail du site. Ordre de priorité :
      1. `notification_recipients` — liste d'e-mails, ou dict {"email": [...]};
      2. le(s) compte(s) provisioné(s) sur ce site (B1) ;
      3. vide — le canal retombe alors sur sa valeur par défaut
         (BREVO_NOTIF_EMAIL), comme le fait déjà la tâche 6.5.
    """
    crus = (site.notification_recipients if site is not None else None) or []
    if isinstance(crus, dict):
        adresses = crus.get("email") or []
    elif isinstance(crus, list):
        adresses = crus
    else:
        adresses = []
    propres = [str(a).strip() for a in adresses if str(a or "").strip()]
    if propres:
        return propres
    try:
        from backend.core.models import User
        comptes = (
            db.query(User)
            .filter(User.site_id == (site.site_id if site else None))
            .filter(User.role_client.isnot(None))
            .all()
        )
        return [u.email for u in comptes if u.email]
    except Exception as exc:  # pragma: no cover - filet
        logger.warning("Destinataires e-mail illisibles (%s)", exc)
        return []


def _destinataire_telegram(site: Optional[ChatbotSite]) -> str:
    """Chat Telegram du site s'il est renseigné, sinon le canal garde son défaut."""
    crus = (site.notification_recipients if site is not None else None) or []
    if isinstance(crus, dict):
        for valeur in crus.get("telegram") or []:
            if str(valeur or "").strip():
                return str(valeur).strip()
    return ""


def _envoyer_sur_canaux(
    site_id: str,
    type_evenement: str,
    sujet: str,
    corps: str,
    reglages: Dict[str, bool],
    telegram_enabled_site: bool,
    email_enabled_site: bool,
    destinataires_email: List[str],
    destinataire_telegram: str,
    fabrique_session,
) -> None:
    """
    Envois d'UN événement sur les canaux demandés, chacun tracé dans TOUS les
    cas (succès, échec, non configuré). Exécuté en arrière-plan : cette
    fonction ne touche PAS la session du visiteur.
    """
    session: Optional[Session] = None
    try:
        session = fabrique_session()

        # --- Webpush : abonnements ACTIFS DU SITE uniquement.
        if reglages.get("push"):
            abonnements = push_abonnements.abonnements_actifs(session, site_id=site_id)
            resultat = notifications.envoyer(
                "webpush", "", sujet, corps, abonnements=abonnements
            )
            notifications.tracer(session, resultat, sujet=sujet, message=corps)
            if resultat.succes and abonnements:
                push_abonnements.marquer_utilisation(session, abonnements)

        # --- E-mail : réglage par type ET interrupteur du site. Sans
        # destinataire propre au site, UN envoi part avec un destinataire vide
        # : le canal résout alors sa valeur par défaut (BREVO_NOTIF_EMAIL) ou
        # renvoie non_configure — dans tous les cas l'envoi est TRACÉ, ce qui
        # est le contrat de la tâche 6.5.
        if reglages.get("email") and email_enabled_site:
            for adresse in (destinataires_email or [""]):
                resultat = notifications.envoyer("email", adresse, sujet, corps)
                notifications.tracer(session, resultat, sujet=sujet, message=corps)

        # --- Telegram : réglage par type ET interrupteur du site.
        if reglages.get("telegram") and telegram_enabled_site:
            resultat = notifications.envoyer(
                "telegram", destinataire_telegram, sujet, corps
            )
            notifications.tracer(session, resultat, sujet=sujet, message=corps)

    except Exception as exc:  # pragma: no cover - filet : rien ne remonte
        logger.error(
            "[B4] envoi arrière-plan échoué (site=%s type=%s) : %s",
            site_id, type_evenement, exc,
        )
        try:
            if session is not None:
                session.rollback()
        except Exception:
            pass
    finally:
        try:
            if session is not None:
                session.close()
        except Exception:
            pass


def notifier_evenement(
    db: Session,
    site_id: str,
    type_evenement: str,
    titre: str,
    corps: str,
    conversation_id: Optional[str] = None,
    arriere_plan: bool = True,
    fabrique_session=None,
) -> Dict[str, Any]:
    """
    Point d'entrée B4 : prévenir le propriétaire d'un événement de son site.

    1. écrit la notification in-app (TOUJOURS, quel que soit le canal) dans la
       transaction COURANTE — visible même si aucun canal n'est configuré ;
    2. déclenche les envois canaux en arrière-plan (thread daemon, session
       propre) selon les réglages du site.

    NE LÈVE JAMAIS et ne bloque jamais le visiteur : la seule écriture
    synchrone est un INSERT unique. `arriere_plan=False` (tests, diagnostic)
    exécute les envois de façon synchrone dans le thread appelant.

    Renvoie un résumé lisible (types et canaux retenus) — jamais un secret.
    """
    resume: Dict[str, Any] = {
        "site_id": site_id,
        "type": type_evenement,
        "in_app": False,
        "canaux_declenches": [],
        "arriere_plan": arriere_plan,
    }
    try:
        site = db.query(ChatbotSite).filter(ChatbotSite.site_id == site_id).first()
        if site is None:
            # Site inconnu : rien à prévenir, rien à faire. État, pas une erreur.
            resume["raison"] = "site_inconnu"
            return resume

        # 1. Notification in-app — le filet qui ne dépend d'aucune clé.
        try:
            db.add(
                ClientNotification(
                    site_id=site_id,
                    type=type_evenement,
                    titre=(titre or "")[:200],
                    corps=corps,
                    conversation_id=conversation_id,
                    lu=False,
                )
            )
            resume["in_app"] = True
        except Exception as exc:  # pragma: no cover - filet
            logger.error("[B4] notification in-app non écrite : %s", exc)
            try:
                db.rollback()
            except Exception:
                pass

        # 2. Envois canaux, selon les réglages par type et les interrupteurs.
        effectifs = reglages_effectifs(site)
        reglages = effectifs.get(type_evenement) or {}
        resume["canaux_declenches"] = [
            canal for canal, actif in reglages.items() if actif
        ]

        # Les destinataires sont résolus ICI, dans le thread appelant (la
        # session du visiteur n'est PAS utilisable depuis le thread
        # d'arrière-plan — seule une session fraîche l'est).
        destinataires_email = _destinataires_email(site, db)
        destinataire_telegram = _destinataire_telegram(site)
        telegram_actif = bool(site.notification_telegram_enabled)
        email_actif = bool(site.notification_email_enabled)

        def _travail() -> None:
            if fabrique_session is None:
                from backend.core.database import SessionLocal as _SL
                fabrique = _SL
            else:
                fabrique = fabrique_session
            _envoyer_sur_canaux(
                site_id=site_id,
                type_evenement=type_evenement,
                sujet=titre,
                corps=corps,
                reglages=reglages,
                telegram_enabled_site=telegram_actif,
                email_enabled_site=email_actif,
                destinataires_email=destinataires_email,
                destinataire_telegram=destinataire_telegram,
                fabrique_session=fabrique,
            )

        if arriere_plan:
            thread = threading.Thread(target=_travail, name=f"notif-{type_evenement}", daemon=True)
            thread.start()
        else:
            _travail()

        return resume
    except Exception as exc:  # pragma: no cover - filet
        logger.error("[B4] notifier_evenement a échoué (%s) : %s", type_evenement, exc)
        resume["raison"] = f"erreur_interne: {type(exc).__name__}"
        return resume


def traiter_apres_message(
    db: Session,
    site_id: str,
    conversation_id: str,
    est_nouvelle_conversation: bool,
    lead_captured_avant: bool,
    statut_avant: Optional[str],
    actions: Optional[List[Dict[str, Any]]] = None,
    arriere_plan: bool = True,
    fabrique_session=None,
) -> List[Dict[str, Any]]:
    """
    Appelé par le pipeline `POST /message` APRÈS traitement (étape 10 du
    service) — déduit les événements du message et prévient le propriétaire.

    Détection, choisie pour être ROBUSTE :
      · nouveau lead : le résultat d'action `lead_capture` est un succès, OU
        `conversation.lead_captured` est passé de faux à vrai pendant le message
        (les deux chemins existent dans le pipeline) ;
      · escalade : le résultat d'action `escalate_to_human` est un succès, OU
        le statut est passé à `escalated` (prise de main côté pipeline) ;
      · nouveau visiteur : première conversation — réglable par type, désactivé
        par défaut.

    Aucun nom d'agent n'apparaît jamais dans les notifications (règle produit).
    Renvoie la liste des résumés (diagnostic).
    """
    resumes: List[Dict[str, Any]] = []
    try:
        actions = actions or []
        action_reussie = {
            (a.get("action") or a.get("type") or ""): bool(a.get("success"))
            for a in actions
            if isinstance(a, dict)
        }

        lead_capte = action_reussie.get("lead_capture", False)
        if not lead_capte:
            try:
                from backend.chatbot.models import ChatbotConversation
                conversation = (
                    db.query(ChatbotConversation)
                    .filter(ChatbotConversation.conversation_id == conversation_id)
                    .first()
                )
                lead_capte = bool(conversation and conversation.lead_captured) and not lead_captured_avant
            except Exception as exc:  # pragma: no cover - filet
                logger.warning("[B4] relecture lead impossible : %s", exc)

        escalade = action_reussie.get("escalate_to_human", False)
        if not escalade and statut_avant is not None:
            try:
                from backend.chatbot.models import ChatbotConversation
                conversation = (
                    db.query(ChatbotConversation)
                    .filter(ChatbotConversation.conversation_id == conversation_id)
                    .first()
                )
                escalade = bool(
                    conversation and conversation.status == "escalated"
                    and statut_avant != "escalated"
                )
            except Exception as exc:  # pragma: no cover - filet
                logger.warning("[B4] relecture statut impossible : %s", exc)

        if lead_capte:
            resumes.append(notifier_evenement(
                db, site_id, TYPE_NOUVEAU_LEAD,
                "Nouveau lead capturé par Mia",
                "Un visiteur a laissé ses coordonnées. Ouvrez vos conversations pour le rappeler.",
                conversation_id=conversation_id,
                arriere_plan=arriere_plan,
                fabrique_session=fabrique_session,
            ))

        if escalade:
            resumes.append(notifier_evenement(
                db, site_id, TYPE_ESCALADE,
                "Escalade : un visiteur demande un humain",
                "Mia a transmis la conversation. Prenez la main depuis la boîte de réception.",
                conversation_id=conversation_id,
                arriere_plan=arriere_plan,
                fabrique_session=fabrique_session,
            ))

        if est_nouvelle_conversation:
            resumes.append(notifier_evenement(
                db, site_id, TYPE_NOUVEAU_VISITEUR,
                "Nouveau visiteur sur votre site",
                "Une conversation vient de commencer. Réglable dans Notifications.",
                conversation_id=conversation_id,
                arriere_plan=arriere_plan,
                fabrique_session=fabrique_session,
            ))
    except Exception as exc:  # pragma: no cover - filet
        logger.error("[B4] traiter_apres_message a échoué : %s", exc)
    return resumes

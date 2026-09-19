"""
API client v1 — refonte app Mia (chantier B3).

À QUI S'ADRESSE CE ROUTER
-------------------------
Aux PROPRIÉTAIRES des sites clients (app Mia), pas aux visiteurs du widget ni
à la console ePerformance. Toutes les routes sont scopées par site via
`require_site_owner` (B2) : un propriétaire ne peut JAMAIS lire les données
d'un autre site — la réponse est 404 (et non 403) pour ne pas révéler
l'existence des autres sites. Voir backend/core/auth.py.

RÈGLES PRODUIT APPLIQUÉES ICI (non négociables)
-----------------------------------------------
· Mia seule : aucun nom d'agent, aucun compteur d'agents, aucun détail
  interne de routage (agent_used, assigned_agent, llm_*) ne sort dans les
  réponses — le propriétaire parle des « compétences de Mia » ;
· ne jamais vendre ce qui n'existe pas : /orders répond un état explicite
  200 (pas branché), pas une erreur et pas une liste vide trompeuse ;
· le system_prompt est géré par ePerformance : lisible via /settings,
  l'écriture est refusée avec la raison ;
· RGPD : export et suppression d'une conversation visiteur sont exposés au
  propriétaire, tracés dans le journal d'audit.

Versionnement : préfixe /api/client/v1 — toute rupture future ira en v2.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from backend.core.audit import tracer_audit
from backend.core.auth import (
    ROLE_CLIENT_ADMIN,
    ROLE_CLIENT_OPERATOR,
    ROLE_CLIENT_READER,
    compte_client_authentifie,
    get_current_user,
    get_password_hash,
    require_site_owner,
    verify_password,
)
from backend.core.database import get_db
from backend.core.models import User
from backend.chatbot import conversations_service
from backend.chatbot.competences_noyau import SECTEURS_CORE
from backend.chatbot.models import (
    ChatbotConversation,
    ChatbotLead,
    ChatbotMessage,
    ChatbotSite,
    ClientNotification,
)
from backend.chatbot.declencheurs import (
    DEFAUTS_REGLAGES,
    TYPES_EVENEMENTS,
)

router = APIRouter(prefix="/api/client/v1", tags=["Client v1 (app Mia)"])


# ============================================================
# Helpers
# ============================================================

def _ip_appelant(request: Request) -> str:
    """IP de l'appelant (X-Forwarded-For derrière le proxy Railway)."""
    transmis = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if transmis:
        return transmis
    return request.client.host if request.client else "inconnue"


def _charger_compte(db: Session, current_user: dict, exiger_actif: bool = True) -> User:
    """
    Charge le compte EN BASE depuis le JWT, sans la contrainte
    must_change_password (utilisée par /me et /password, qui doivent rester
    accessibles pendant le changement forcé).
    """
    utilisateur = db.query(User).filter(User.email == current_user["email"]).first()
    if utilisateur is None:
        raise HTTPException(status_code=401, detail="Compte introuvable")
    if exiger_actif and not utilisateur.is_active:
        raise HTTPException(status_code=403, detail="Compte désactivé")
    return utilisateur


def _ecrire_json(site: ChatbotSite, champ: str, valeur: Any) -> None:
    """
    Écrit une colonne JSON en RÉASSIGNANT + flag_modified (piège du projet :
    SQLAlchemy compare new == old au flush, une mutation en place d'un dict
    égal n'est jamais écrite).
    """
    setattr(site, champ, valeur)
    flag_modified(site, champ)


def _conversation_du_site(db: Session, site_id: str, conversation_id: str) -> ChatbotConversation:
    """
    Renvoie la conversation SI elle appartient au site. Sinon 404 — le filtre
    porte sur le site, donc une conversation d'un AUTRE site ne peut pas être
    distinguée d'une conversation inexistante : exactement l'isolement voulu.
    """
    conversation = (
        db.query(ChatbotConversation)
        .filter(
            ChatbotConversation.conversation_id == conversation_id,
            ChatbotConversation.site_id == site_id,
        )
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation non trouvée")
    return conversation


# ============================================================
# Schemas
# ============================================================

class ChangementMotDePasseRequest(BaseModel):
    ancien_mot_de_passe: str = Field(..., min_length=1, max_length=200)
    nouveau_mot_de_passe: str = Field(..., min_length=8, max_length=200,
                                      description="8 caractères minimum")


class Code2FARequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=8,
                      description="Code à 6 chiffres de l'application "
                                  "d'authentification (TOTP)")


class Desactivation2FARequest(BaseModel):
    mot_de_passe: str = Field(..., min_length=1, max_length=200,
                              description="Le mot de passe est exigé pour "
                                          "désactiver la 2FA")


class MessageHumainRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class LectureNotificationsRequest(BaseModel):
    ids: Optional[List[int]] = None
    toutes: bool = False


class ReglagesParType(BaseModel):
    """
    Réglages d'UN type de notification, comme envoyés par l'app.

    Les champs sont Optional[bool]=None VOLONTAIREMENT : un canal absent de la
    requête reprend le DÉFAUT SENSIBLE du type (DEFAUTS_REGLAGES, ex.
    nouveau_visiteur silencieux) au moment de la normalisation — et non la
    valeur par défaut de ce modèle, qui écraserait les défauts du produit.
    """

    push: Optional[bool] = None
    email: Optional[bool] = None
    telegram: Optional[bool] = None


class ReglagesSiteRequest(BaseModel):
    """
    Ce que le client peut régler lui-même (PUT /settings).

    HORS PÉRIMÈTRE CLIENT (décisions produit) :
    · system_prompt — géré par ePerformance ; s'il est envoyé, la route le
      refuse explicitement (400) au lieu de l'ignorer silencieusement ;
    · sector — déterminé à la création du site ;
    · theme_config / features_enabled — évolutions ultérieures.
    """
    welcome_message: Optional[str] = Field(None, max_length=2000)
    system_prompt: Optional[str] = Field(
        None,
        description="Refusé : le prompt système est géré par ePerformance",
    )
    notification_telegram_enabled: Optional[bool] = None
    notification_email_enabled: Optional[bool] = None
    notification_recipients: Optional[Union[List[str], Dict[str, List[str]]]] = None
    notification_settings: Optional[Dict[str, ReglagesParType]] = Field(
        None,
        description="Réglages par type : nouveau_lead, escalade, "
                    "nouveau_visiteur × push/email/telegram",
    )
    rate_limit_messages_per_minute: Optional[int] = Field(None, ge=1, le=120)
    rate_limit_conversations_per_day: Optional[int] = Field(None, ge=1, le=10000)
    horaires: Optional[Dict[str, Any]] = Field(
        None,
        description="Horaires et disponibilités (structure libre, cf. doc §8)",
    )
    competences: Optional[List[str]] = Field(
        None,
        description="Compétences de Mia actives (thèmes FAQ du secteur) — "
                    "stocké dans allowed_intents ; null = toutes",
    )


# ============================================================
# Compte (account-level) — /me, /password, /2fa
# ============================================================

@router.get("/me")
async def mon_profil(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Profil du compte connecté : sites gérés, rôle, état 2FA et
    must_change_password. Reste accessible pendant le changement forcé du mot
    de passe (c'est l'app qui décide de l'écran à afficher grâce à cette route).

    Aucun nom d'agent, aucune donnée d'un autre site — la liste `sites` ne
    contient que le site du compte.
    """
    utilisateur = _charger_compte(db, current_user)
    site = None
    if utilisateur.site_id:
        site = db.query(ChatbotSite).filter(ChatbotSite.site_id == utilisateur.site_id).first()
    return {
        "user_id": utilisateur.id,
        "email": utilisateur.email,
        "nom": utilisateur.nom,
        "role": utilisateur.role,
        "role_client": utilisateur.role_client,
        "must_change_password": bool(utilisateur.must_change_password),
        "sites": (
            [{
                "site_id": site.site_id,
                "site_name": site.site_name,
                "site_url": site.site_url,
                "secteur": site.sector,
                "is_active": bool(site.is_active),
            }]
            if site is not None else []
        ),
        "tfa": {
            "active": bool(utilisateur.totp_enabled),
            # Obligatoire pour client_admin (audit préalable C5) — l'app
            # affiche l'écran de configuration tant qu'elle est inactive.
            "requise": utilisateur.role_client == ROLE_CLIENT_ADMIN,
        },
    }


@router.post("/password")
async def changer_mot_de_passe(
    corps: ChangementMotDePasseRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Change le mot de passe (vérifie l'ancien) et lève must_change_password.

    SEULE route client accessible tant que must_change_password est vrai —
    elle est précisément celle qui le lève. Tracée dans le journal d'audit.
    """
    utilisateur = _charger_compte(db, current_user)

    if not verify_password(corps.ancien_mot_de_passe, utilisateur.password_hash):
        raise HTTPException(status_code=400, detail="Ancien mot de passe incorrect")

    utilisateur.password_hash = get_password_hash(corps.nouveau_mot_de_passe)
    utilisateur.must_change_password = False
    db.commit()

    tracer_audit(
        db,
        "changement_mot_de_passe",
        user_id=utilisateur.id,
        user_email=utilisateur.email,
        site_id=utilisateur.site_id,
        ip=_ip_appelant(request),
    )
    db.commit()

    return {
        "ok": True,
        "must_change_password": False,
        "message": "Mot de passe changé. Toutes les fonctions de l'app sont "
                   "désormais accessibles.",
    }


@router.post("/2fa/setup")
async def configurer_2fa(
    db: Session = Depends(get_db),
    utilisateur: User = Depends(compte_client_authentifie),
):
    """
    Génère le secret TOTP et renvoie l'URI otpauth (B2).

    Le secret est stocké CHIFFRÉ (Fernet, clé dérivée de SECRET_KEY) dès le
    setup ; il ne devient actif qu'après /2fa/activate. Le secret et l'URI
    sont renvoyés UNE SEULE FOIS ici — l'app génère le QR côté client.
    Refus (400) si la 2FA est déjà active : passer par /2fa/disable d'abord.
    """
    import pyotp  # import paresseux volontaire (règle du projet)
    from backend.core.auth import chiffrer_secret_totp, ChiffrementIndisponible

    if utilisateur.totp_enabled:
        raise HTTPException(
            status_code=400,
            detail="2FA déjà activée : désactivez-la d'abord (avec mot de passe)",
        )

    secret = pyotp.random_base32()
    try:
        utilisateur.totp_secret = chiffrer_secret_totp(secret)
    except ChiffrementIndisponible as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    db.commit()

    totp = pyotp.TOTP(secret)
    return {
        "secret": secret,  # une seule fois, pour saisie manuelle
        "otpauth_uri": totp.provisioning_uri(
            name=utilisateur.email, issuer_name="Mia ePerformance"
        ),
        "message": "Scannez l'URI (ou saisissez le secret) dans votre "
                   "application d'authentification, puis confirmez par "
                   "POST /2fa/activate avec un code.",
    }


@router.post("/2fa/activate")
async def activer_2fa(
    corps: Code2FARequest,
    request: Request,
    db: Session = Depends(get_db),
    utilisateur: User = Depends(compte_client_authentifie),
):
    """Vérifie un code TOTP et active la 2FA (B2). Tracé en audit."""
    from backend.core.auth import verifier_secret_totp, ChiffrementIndisponible

    if utilisateur.totp_enabled:
        raise HTTPException(status_code=400, detail="2FA déjà activée")
    if not utilisateur.totp_secret:
        raise HTTPException(
            status_code=400,
            detail="Aucun secret en attente : commencez par POST /2fa/setup",
        )

    try:
        valide = verifier_secret_totp(utilisateur.totp_secret, corps.code)
    except ChiffrementIndisponible as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if not valide:
        raise HTTPException(status_code=400, detail="Code 2FA invalide")

    utilisateur.totp_enabled = True
    db.commit()

    tracer_audit(
        db,
        "activation_2fa",
        user_id=utilisateur.id,
        user_email=utilisateur.email,
        site_id=utilisateur.site_id,
        ip=_ip_appelant(request),
    )
    db.commit()

    return {"ok": True, "tfa_active": True}


@router.post("/2fa/disable")
async def desactiver_2fa(
    corps: Desactivation2FARequest,
    request: Request,
    db: Session = Depends(get_db),
    utilisateur: User = Depends(compte_client_authentifie),
):
    """
    Désactive la 2FA — exige le mot de passe (B2). Tracé en audit.

    Un client_admin qui désactive sa 2FA retrouve la contrainte
    « 2FA obligatoire » sur les routes de son site : c'est assumé, la
    désactivation est un choix explicite et authentifié.
    """
    from backend.core.auth import verify_password

    if not utilisateur.totp_enabled:
        raise HTTPException(status_code=400, detail="2FA non activée")

    if not verify_password(corps.mot_de_passe, utilisateur.password_hash):
        raise HTTPException(status_code=400, detail="Mot de passe incorrect")

    utilisateur.totp_enabled = False
    utilisateur.totp_secret = None
    db.commit()

    tracer_audit(
        db,
        "desactivation_2fa",
        user_id=utilisateur.id,
        user_email=utilisateur.email,
        site_id=utilisateur.site_id,
        ip=_ip_appelant(request),
    )
    db.commit()

    return {"ok": True, "tfa_active": False}


# ============================================================
# Conversations du site (scopées)
# ============================================================

def _resume_conversation(db: Session, conv: ChatbotConversation) -> dict:
    """Item de liste : sans nom d'agent, sans IP ni infos internes visiteur."""
    dernier = (
        db.query(ChatbotMessage)
        .filter(ChatbotMessage.conversation_id == conv.conversation_id)
        .order_by(ChatbotMessage.id.desc())
        .first()
    )
    lead = (
        db.query(ChatbotLead)
        .filter(ChatbotLead.conversation_id == conv.conversation_id)
        .first()
    )
    meta = conv.conversation_metadata or {}
    non_lu = bool(dernier is not None and dernier.role == "user")
    return {
        "conversation_id": conv.conversation_id,
        "site_id": conv.site_id,
        "status": conv.status,
        "human_active": bool(meta.get("human_active")),
        "lead_captured": bool(conv.lead_captured),
        "visitor_name": conv.visitor_name or (lead.name if lead else None),
        "visitor_phone": conv.visitor_phone or (lead.phone if lead else None),
        "message_count": conv.message_count,
        "non_lu": non_lu,
        "last_message": dernier.content[:120] if dernier else None,
        "last_message_role": dernier.role if dernier else None,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
    }


@router.get("/sites/{site_id}/conversations")
async def conversations_du_site(
    site_id: str,
    page: int = Query(1, ge=1, description="Page (1-based)"),
    page_size: int = Query(20, ge=1, le=100),
    non_lu: bool = Query(False, description="Seulement celles qui attendent une réponse"),
    escalade: bool = Query(False, description="Seulement les escaladées"),
    avec_lead: bool = Query(False, description="Seulement celles avec un lead"),
    q: str = Query("", max_length=200, description="Recherche (nom, e-mail, contenu)"),
    db: Session = Depends(get_db),
    utilisateur: User = Depends(require_site_owner()),
):
    """
    Boîte de réception du site (pagination + filtres + recherche).

    Définition de « non lu » : le DERNIER message est celui du visiteur —
    la conversation attend une réponse humaine. (La conversation n'a pas de
    notion de lecture par compte : c'est l'état de la boîte, pas un accusé.)
    """
    query = db.query(ChatbotConversation).filter(ChatbotConversation.site_id == site_id)

    if escalade:
        query = query.filter(ChatbotConversation.status == "escalated")
    if avec_lead:
        query = query.filter(ChatbotConversation.lead_captured.is_(True))
    if non_lu:
        dernier_message_par_conv = (
            db.query(
                ChatbotMessage.conversation_id.label("cid"),
                func.max(ChatbotMessage.id).label("mid"),
            )
            .group_by(ChatbotMessage.conversation_id)
            .subquery()
        )
        query = (
            query.join(dernier_message_par_conv,
                       ChatbotConversation.conversation_id == dernier_message_par_conv.c.cid)
            .join(ChatbotMessage, ChatbotMessage.id == dernier_message_par_conv.c.mid)
            .filter(ChatbotMessage.role == "user")
        )
    if q.strip():
        terme = f"%{q.strip()}%"
        # Recherche dans l'identité du visiteur ET le contenu des messages
        # (EXISTS corrélé : une conversation remonte si UN message correspond).
        contenu_correspondant = (
            db.query(ChatbotMessage.id)
            .filter(
                ChatbotMessage.conversation_id == ChatbotConversation.conversation_id,
                ChatbotMessage.content.ilike(terme),
            )
            .exists()
        )
        query = query.filter(or_(
            ChatbotConversation.visitor_name.ilike(terme),
            ChatbotConversation.visitor_email.ilike(terme),
            ChatbotConversation.visitor_phone.ilike(terme),
            contenu_correspondant,
        ))

    total = query.count()
    conversations = (
        query.order_by(ChatbotConversation.last_message_at.desc().nullslast(),
                       ChatbotConversation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "conversations": [_resume_conversation(db, c) for c in conversations],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/sites/{site_id}/conversations/{conversation_id}")
async def detail_conversation(
    site_id: str,
    conversation_id: str,
    db: Session = Depends(get_db),
    utilisateur: User = Depends(require_site_owner()),
):
    """
    Détail complet : conversation + messages + lead du visiteur.

    Volontairement SANS `agent_used` ni `assigned_agent` : l'identité des
    agents internes est un détail d'implémentation ePerformance, jamais exposé
    au client (règle produit « Mia seule »).
    """
    conversation = _conversation_du_site(db, site_id, conversation_id)
    messages = (
        db.query(ChatbotMessage)
        .filter(ChatbotMessage.conversation_id == conversation.conversation_id)
        .order_by(ChatbotMessage.created_at.asc(), ChatbotMessage.id.asc())
        .all()
    )
    lead = (
        db.query(ChatbotLead)
        .filter(ChatbotLead.conversation_id == conversation.conversation_id)
        .first()
    )
    meta = conversation.conversation_metadata or {}

    return {
        "conversation": {
            "conversation_id": conversation.conversation_id,
            "site_id": conversation.site_id,
            "status": conversation.status,
            "human_active": bool(meta.get("human_active")),
            "lead_captured": bool(conversation.lead_captured),
            "message_count": conversation.message_count,
            "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
            "last_message_at": conversation.last_message_at.isoformat() if conversation.last_message_at else None,
        },
        "visitor": {
            "name": conversation.visitor_name or (lead.name if lead else None),
            "email": conversation.visitor_email or (lead.email if lead else None),
            "phone": conversation.visitor_phone or (lead.phone if lead else None),
        },
        "lead": (
            {
                "id": lead.id,
                "lead_type": lead.lead_type,
                "status": lead.status,
                "intent": lead.intent,
                "message": lead.message,
                "created_at": lead.created_at.isoformat() if lead.created_at else None,
            }
            if lead else None
        ),
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "human": bool((m.context_data or {}).get("human")),
                "human_name": (m.context_data or {}).get("human_name"),
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@router.post("/sites/{site_id}/conversations/{conversation_id}/reply")
async def repondre_conversation(
    site_id: str,
    conversation_id: str,
    corps: MessageHumainRequest,
    db: Session = Depends(get_db),
    utilisateur: User = Depends(require_site_owner(ROLE_CLIENT_OPERATOR)),
):
    """
    Message humain dans la conversation (rôle operator minimum).

    Réutilise la mécanique existante `human_active` : répondre PREND LA MAIN
    (le LLM se met en pause) — sinon Mia répondrait par-dessus le message.
    Pour rendre la main à Mia : POST .../release.
    """
    conversation = _conversation_du_site(db, site_id, conversation_id)
    contenu = (corps.content or "").strip()
    if not contenu:
        raise HTTPException(status_code=400, detail="Empty message")

    meta = conversation.conversation_metadata or {}
    if not meta.get("human_active"):
        conversations_service.prendre_la_main(
            db, conversation,
            email_conseiller=utilisateur.email,
            nom_conseiller=utilisateur.nom,
        )

    message = conversations_service.message_humain(
        db, conversation, contenu, nom_conseiller=utilisateur.nom,
    )
    return {
        "ok": True,
        "message_id": message.id,
        "human_active": True,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


@router.post("/sites/{site_id}/conversations/{conversation_id}/takeover")
async def prendre_la_main(
    site_id: str,
    conversation_id: str,
    db: Session = Depends(get_db),
    utilisateur: User = Depends(require_site_owner(ROLE_CLIENT_OPERATOR)),
):
    """L'humain prend la main : Mia se met en pause (operator minimum)."""
    conversation = _conversation_du_site(db, site_id, conversation_id)
    conversations_service.prendre_la_main(
        db, conversation,
        email_conseiller=utilisateur.email,
        nom_conseiller=utilisateur.nom,
    )
    meta = conversation.conversation_metadata or {}
    return {
        "conversation_id": conversation.conversation_id,
        "status": conversation.status,
        "human_active": bool(meta.get("human_active")),
    }


@router.post("/sites/{site_id}/conversations/{conversation_id}/release")
async def rendre_la_main(
    site_id: str,
    conversation_id: str,
    db: Session = Depends(get_db),
    utilisateur: User = Depends(require_site_owner(ROLE_CLIENT_OPERATOR)),
):
    """Rend la main à Mia : elle reprend avec tout l'historique (operator minimum)."""
    conversation = _conversation_du_site(db, site_id, conversation_id)
    conversations_service.rendre_la_main(db, conversation)
    return {
        "conversation_id": conversation.conversation_id,
        "status": conversation.status,
        "human_active": False,
    }


# ============================================================
# Analytics, leads, commandes
# ============================================================

@router.get("/sites/{site_id}/analytics")
async def analytics_du_site(
    site_id: str,
    period_days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    utilisateur: User = Depends(require_site_owner()),
):
    """
    Métriques du site (écran Analytics) — réutilise EXACTEMENT le calcul de
    `GET /api/chatbot/analytics/{site_id}` (même agrégation, même forme de
    réponse), simplement sous scope client.
    """
    from backend.api.routes.chatbot import get_site_analytics

    return await get_site_analytics(site_id=site_id, period_days=period_days, db=db)


@router.get("/sites/{site_id}/leads")
async def leads_du_site(
    site_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    utilisateur: User = Depends(require_site_owner()),
):
    """Leads capturés par Mia sur ce site (les plus récents d'abord)."""
    requete = db.query(ChatbotLead).filter(ChatbotLead.site_id == site_id)
    total = requete.count()
    leads = (
        requete.order_by(ChatbotLead.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "leads": [
            {
                "id": l.id,
                "conversation_id": l.conversation_id,
                "name": l.name,
                "email": l.email,
                "phone": l.phone,
                "company": l.company,
                "lead_type": l.lead_type,
                "status": l.status,
                "intent": l.intent,
                "message": l.message,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in leads
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/sites/{site_id}/orders")
async def commandes_du_site(
    site_id: str,
    utilisateur: User = Depends(require_site_owner()),
):
    """
    Commandes — ÉTAT EXPLICITE (règle produit : ne jamais vendre ce qui
    n'existe pas). L'intégration e-commerce n'est pas branchée (roadmap
    « Mia exécute ») : la réponse est 200 avec `disponible: false`, PAS une
    erreur et PAS une liste vide qui laisserait croire à un catalogue vide.
    """
    return {
        "disponible": False,
        "raison": "l'intégration e-commerce n'est pas branchée (roadmap)",
        "orders": [],
    }


# ============================================================
# Réglages du site (écrans 7 et 9 de l'app)
# ============================================================

def _vue_settings(site: ChatbotSite) -> dict:
    """Forme de la configuration vue par le client (GET et PUT)."""
    return {
        "site_id": site.site_id,
        "site_name": site.site_name,
        "secteur": site.sector,
        # Lisible mais NON modifiable par le client (décision produit) :
        # le prompt est la voix de Mia, ePerformance le tient à jour.
        "system_prompt": site.system_prompt,
        "system_prompt_modifiable": False,
        "welcome_message": site.welcome_message,
        "notifications": {
            "telegram_active": bool(site.notification_telegram_enabled),
            "email_active": bool(site.notification_email_enabled),
            "destinataires": site.notification_recipients,
            "par_type": site.notification_settings or DEFAUTS_REGLAGES,
        },
        "rate_limits": {
            "messages_per_minute": site.rate_limit_messages_per_minute,
            "conversations_per_day": site.rate_limit_conversations_per_day,
        },
        "horaires": site.horaires,
        "competences": site.allowed_intents,
    }


@router.get("/sites/{site_id}/settings")
async def lire_reglages(
    site_id: str,
    db: Session = Depends(get_db),
    utilisateur: User = Depends(require_site_owner()),
):
    """Configuration du site (écran 7). Le system_prompt est lisible, jamais modifiable."""
    site = db.query(ChatbotSite).filter(ChatbotSite.site_id == site_id).first()
    if site is None:
        raise HTTPException(status_code=404, detail="Site non trouvé")
    return _vue_settings(site)


@router.put("/sites/{site_id}/settings")
async def ecrire_reglages(
    site_id: str,
    corps: ReglagesSiteRequest,
    request: Request,
    db: Session = Depends(get_db),
    utilisateur: User = Depends(require_site_owner(ROLE_CLIENT_ADMIN)),
):
    """
    Modifie la configuration du site (client_admin uniquement).

    Le `system_prompt`, s'il est fourni, est REFUSÉ explicitement (400) —
    la raison est produits : le prompt est géré par ePerformance. Les colonnes
    JSON sont réassignées avec flag_modified (piège ORM du projet). Tracé en
    audit (action configuration_site, détail des champs modifiés).
    """
    site = db.query(ChatbotSite).filter(ChatbotSite.site_id == site_id).first()
    if site is None:
        raise HTTPException(status_code=404, detail="Site non trouvé")

    if corps.system_prompt is not None:
        raise HTTPException(
            status_code=400,
            detail="Le system_prompt n'est pas modifiable par le client : il "
                   "est géré par ePerformance (décision produit). Contactez "
                   "votre contact ePerformance pour le faire évoluer.",
        )

    champs_modifies: List[str] = []

    if corps.welcome_message is not None:
        site.welcome_message = corps.welcome_message
        champs_modifies.append("welcome_message")

    if corps.notification_telegram_enabled is not None:
        site.notification_telegram_enabled = corps.notification_telegram_enabled
        champs_modifies.append("notification_telegram_enabled")

    if corps.notification_email_enabled is not None:
        site.notification_email_enabled = corps.notification_email_enabled
        champs_modifies.append("notification_email_enabled")

    if corps.notification_recipients is not None:
        _ecrire_json(site, "notification_recipients", corps.notification_recipients)
        champs_modifies.append("notification_recipients")

    if corps.notification_settings is not None:
        # Normalise : types connus seulement, complété par les défauts.
        normalises: Dict[str, Dict[str, bool]] = {}
        for type_evenement, valeur in corps.notification_settings.items():
            if type_evenement not in TYPES_EVENEMENTS:
                raise HTTPException(
                    status_code=422,
                    detail=f"Type de notification inconnu : {type_evenement} "
                           f"(acceptés : {', '.join(TYPES_EVENEMENTS)})",
                )
            defaut = DEFAUTS_REGLAGES[type_evenement]
            normalises[type_evenement] = {
                canal: bool(
                    getattr(valeur, canal)
                    if getattr(valeur, canal) is not None
                    else defaut[canal]
                )
                for canal in ("push", "email", "telegram")
            }
        # Les types absents reprennent le défaut (pas de réglage fantôme).
        for type_evenement, defaut in DEFAUTS_REGLAGES.items():
            normalises.setdefault(type_evenement, dict(defaut))
        _ecrire_json(site, "notification_settings", normalises)
        champs_modifies.append("notification_settings")

    if corps.rate_limit_messages_per_minute is not None:
        site.rate_limit_messages_per_minute = corps.rate_limit_messages_per_minute
        champs_modifies.append("rate_limit_messages_per_minute")

    if corps.rate_limit_conversations_per_day is not None:
        site.rate_limit_conversations_per_day = corps.rate_limit_conversations_per_day
        champs_modifies.append("rate_limit_conversations_per_day")

    if corps.horaires is not None:
        if not isinstance(corps.horaires, dict):
            raise HTTPException(
                status_code=422,
                detail="horaires doit être un objet JSON "
                       "(cf. API-CLIENT-V1.md §8)",
            )
        _ecrire_json(site, "horaires", corps.horaires)
        champs_modifies.append("horaires")

    if corps.competences is not None:
        competences = [c.strip()[:100] for c in corps.competences if str(c or "").strip()]
        _ecrire_json(site, "allowed_intents", competences)
        champs_modifies.append("allowed_intents")

    if not champs_modifies:
        raise HTTPException(
            status_code=400,
            detail="Aucun réglage fourni (ou seulement des champs identiques)",
        )

    site.updated_at = datetime.utcnow()
    db.commit()

    tracer_audit(
        db,
        "configuration_site",
        user_id=utilisateur.id,
        user_email=utilisateur.email,
        site_id=site_id,
        details={"champs": champs_modifies},
        ip=_ip_appelant(request),
    )
    db.commit()

    return {"ok": True, "champs_modifies": champs_modifies, "settings": _vue_settings(site)}


# ============================================================
# Compétences de Mia (écran 8)
# ============================================================

@router.get("/sites/{site_id}/competences")
async def competences_du_site(
    site_id: str,
    db: Session = Depends(get_db),
    utilisateur: User = Depends(require_site_owner()),
):
    """
    Ce que Mia sait faire DANS LE MÉTIER du site (écran 8).

    Source : le NOYAU (agent-ia-web/eperf_core/sectors.py) via le snapshot
    versionné `backend/chatbot/competences_noyau.py` — l'app consomme le
    contenu sectoriel du noyau, elle ne le réécrit jamais (audit C1).
    L'activation/désactivation par le client passe par allowed_intents
    (PUT /settings, champ `competences`) : null = toutes actives.
    """
    site = db.query(ChatbotSite).filter(ChatbotSite.site_id == site_id).first()
    if site is None:
        raise HTTPException(status_code=404, detail="Site non trouvé")

    if not site.sector:
        return {
            "site_id": site_id,
            "disponible": False,
            "message": "Le secteur du site n'est pas encore renseigné par "
                       "ePerformance : les compétences de Mia s'afficheront "
                       "ensuite.",
            "secteur": None,
            "competences": [],
        }

    secteur = SECTEURS_CORE.get(site.sector)
    if secteur is None:
        return {
            "site_id": site_id,
            "disponible": False,
            "message": f"Secteur inconnu : {site.sector}",
            "secteur": site.sector,
            "competences": [],
        }

    autorises = site.allowed_intents
    toutes_actives = not autorises  # null ou vide = toutes
    competences = [
        {
            "theme": theme,
            "active": True if toutes_actives else theme in autorises,
        }
        for theme in secteur["faq_themes"]
    ]
    return {
        "site_id": site_id,
        "disponible": True,
        "secteur": site.sector,
        "secteur_nom": secteur["nom"],
        "intention": secteur["intention"],
        "item": secteur["item"],
        "competences": competences,
    }


# ============================================================
# Notifications in-app (écran 5) — alimentées par B4
# ============================================================

@router.get("/sites/{site_id}/notifications")
async def notifications_du_site(
    site_id: str,
    lu: Optional[bool] = Query(None, description="Filtrer par état lu/non lu"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    utilisateur: User = Depends(require_site_owner()),
):
    """Notifications in-app du site (les plus récentes d'abord) + non lues."""
    requete = db.query(ClientNotification).filter(ClientNotification.site_id == site_id)
    if lu is not None:
        requete = requete.filter(ClientNotification.lu.is_(lu))

    total = requete.count()
    non_lues = (
        db.query(func.count(ClientNotification.id))
        .filter(ClientNotification.site_id == site_id, ClientNotification.lu.is_(False))
        .scalar()
        or 0
    )
    lignes = (
        requete.order_by(ClientNotification.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "notifications": [
            {
                "id": n.id,
                "type": n.type,
                "titre": n.titre,
                "corps": n.corps,
                "conversation_id": n.conversation_id,
                "lu": bool(n.lu),
                "date_creation": n.date_creation.isoformat() if n.date_creation else None,
            }
            for n in lignes
        ],
        "non_lues": non_lues,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/sites/{site_id}/notifications/read")
async def marquer_notifications_lues(
    site_id: str,
    corps: LectureNotificationsRequest,
    db: Session = Depends(get_db),
    utilisateur: User = Depends(require_site_owner()),
):
    """Marque des notifications (ou toutes) comme lues. Scopé au site."""
    if not corps.toutes and not corps.ids:
        raise HTTPException(
            status_code=400,
            detail="Indiquez `ids: [...]` ou `toutes: true`",
        )

    requete = db.query(ClientNotification).filter(ClientNotification.site_id == site_id)
    if corps.toutes:
        lignes = requete.filter(ClientNotification.lu.is_(False)).all()
    else:
        lignes = requete.filter(
            ClientNotification.id.in_(corps.ids), ClientNotification.lu.is_(False)
        ).all()

    for ligne in lignes:
        ligne.lu = True
    db.commit()

    return {"ok": True, "marquees_lues": len(lignes)}


# ============================================================
# RGPD — droit d'accès et de suppression du visiteur final (C4)
# ============================================================

@router.get("/sites/{site_id}/rgpd/conversations/{conversation_id}/export")
async def exporter_conversation_rgpd(
    site_id: str,
    conversation_id: str,
    request: Request,
    db: Session = Depends(get_db),
    utilisateur: User = Depends(require_site_owner(ROLE_CLIENT_OPERATOR)),
):
    """
    Export JSON complet d'une conversation (droit d'accès du visiteur final).

    Le propriétaire exerce ici la demande de son visiteur : tout ce que la
    base sait sur cette conversation, en un fichier — conversation, messages,
    lead. Tracé en audit (export_rgpd_conversation), sans le contenu.
    """
    conversation = _conversation_du_site(db, site_id, conversation_id)
    messages = (
        db.query(ChatbotMessage)
        .filter(ChatbotMessage.conversation_id == conversation.conversation_id)
        .order_by(ChatbotMessage.created_at.asc(), ChatbotMessage.id.asc())
        .all()
    )
    leads = (
        db.query(ChatbotLead)
        .filter(ChatbotLead.conversation_id == conversation.conversation_id)
        .all()
    )

    tracer_audit(
        db,
        "export_rgpd_conversation",
        user_id=utilisateur.id,
        user_email=utilisateur.email,
        site_id=site_id,
        details={"conversation_id": conversation_id,
                 "messages": len(messages), "leads": len(leads)},
        ip=_ip_appelant(request),
    )
    db.commit()

    return {
        "export_rgpd": True,
        "genere_le": datetime.utcnow().isoformat(),
        "conversation": {
            "conversation_id": conversation.conversation_id,
            "site_id": conversation.site_id,
            "status": conversation.status,
            "started_at": conversation.started_at.isoformat() if conversation.started_at else None,
            "last_message_at": conversation.last_message_at.isoformat() if conversation.last_message_at else None,
            "message_count": conversation.message_count,
            "visitor_name": conversation.visitor_name,
            "visitor_email": conversation.visitor_email,
            "visitor_phone": conversation.visitor_phone,
            "metadata": conversation.conversation_metadata,
        },
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
        "leads": [
            {
                "name": l.name,
                "email": l.email,
                "phone": l.phone,
                "company": l.company,
                "lead_type": l.lead_type,
                "intent": l.intent,
                "message": l.message,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in leads
        ],
    }


@router.delete("/sites/{site_id}/rgpd/conversations/{conversation_id}")
async def supprimer_conversation_rgpd(
    site_id: str,
    conversation_id: str,
    request: Request,
    db: Session = Depends(get_db),
    utilisateur: User = Depends(require_site_owner(ROLE_CLIENT_ADMIN)),
):
    """
    Supprime une conversation à la demande du visiteur final (droit à
    l'effacement) : cascade messages et leads, tracée en audit. client_admin
    uniquement — la suppression est définitive.
    """
    conversation = _conversation_du_site(db, site_id, conversation_id)

    suppr_messages = (
        db.query(ChatbotMessage)
        .filter(ChatbotMessage.conversation_id == conversation.conversation_id)
        .delete(synchronize_session=False)
    )
    suppr_leads = (
        db.query(ChatbotLead)
        .filter(ChatbotLead.conversation_id == conversation.conversation_id)
        .delete(synchronize_session=False)
    )
    db.delete(conversation)
    db.commit()

    tracer_audit(
        db,
        "suppression_rgpd_conversation",
        user_id=utilisateur.id,
        user_email=utilisateur.email,
        site_id=site_id,
        details={
            "conversation_id": conversation_id,
            "messages_supprimes": suppr_messages,
            "leads_supprimes": suppr_leads,
        },
        ip=_ip_appelant(request),
    )
    db.commit()

    return {
        "ok": True,
        "supprime": True,
        "conversation_id": conversation_id,
        "messages_supprimes": suppr_messages,
        "leads_supprimes": suppr_leads,
    }

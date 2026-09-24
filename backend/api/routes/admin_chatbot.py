"""
Admin Chatbot routes - ePerformance API Flow

Dashboard admin (web + mobile PWA) pour:
- Lister/détailler les conversations chatbot
- Prendre la main (takeover humain) et rendre la main à l'IA
- Envoyer des messages humains (le LLM est en pause sur la conversation)
- Assigner manuellement un agent IA (override du router)
- Envoyer des notifications et consulter leur trace (tâche 6.5)

Auth: JWT existant (POST /api/auth/login) + role admin requis.
Sans migration DB: human_active et assigned_agent vivent dans
conversation_metadata (JSONB) — cf contrat dashboard.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm.attributes import flag_modified
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.core.auth import get_current_user, get_password_hash
from backend.chatbot import connaissances as connaissances_moteur
from backend.chatbot.models import ConnaissanceProprietaire
from backend.core.database import get_db
from backend.core.models import User
from backend.chatbot.models import (
    ChatbotConversation,
    ChatbotLead,
    ChatbotMessage,
    ChatbotNotificationLog,
    ChatbotPushSubscription,
    ChatbotSite,
    PushSubscription,
)
from backend.chatbot import notifications, push_abonnements
from backend.chatbot import conversations_service

router = APIRouter(prefix="/api/chatbot", tags=["chatbot"])


def require_admin(current_user: dict) -> None:
    """Garde 403 si l'utilisateur authentifié n'est pas admin."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")


def get_metadata(conversation: ChatbotConversation) -> Dict[str, Any]:
    return conversation.conversation_metadata or {}


def set_metadata(conversation: ChatbotConversation, meta: Dict[str, Any]) -> None:
    """Réassigne une COPIE du dict et FORCE le flag de modification.

    Colonne JSON plain: SQLAlchemy compare new == old au flush — une copie
    du dict est ÉGALE à l'original → colonne jamais incluse dans l'UPDATE
    (mutations perdues silencieusement). flag_modified() force l'écriture.
    """
    conversation.conversation_metadata = dict(meta)
    flag_modified(conversation, "conversation_metadata")


# ============================================================
# Schemas
# ============================================================

class HumanMessageRequest(BaseModel):
    content: str


class AssignAgentRequest(BaseModel):
    agent_key: str


class TakeoverResponse(BaseModel):
    conversation_id: str
    status: str
    human_active: bool


# ============================================================
# Conversations — liste & détail
# ============================================================

@router.get("/admin/conversations")
async def list_conversations(
    status: Optional[str] = None,
    site_id: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Liste des conversations (dernières en premier) + dernier message + lead."""
    require_admin(current_user)

    query = db.query(ChatbotConversation)
    if status:
        query = query.filter(ChatbotConversation.status == status)
    if site_id:
        query = query.filter(ChatbotConversation.site_id == site_id)

    conversations = (
        query.order_by(ChatbotConversation.created_at.desc()).limit(min(limit, 200)).all()
    )

    items = []
    for conv in conversations:
        last_message = (
            db.query(ChatbotMessage)
            .filter(ChatbotMessage.conversation_id == conv.conversation_id)
            .order_by(ChatbotMessage.created_at.desc())
            .first()
        )
        lead = (
            db.query(ChatbotLead)
            .filter(ChatbotLead.conversation_id == conv.conversation_id)
            .first()
        )
        meta = get_metadata(conv)
        items.append(
            {
                "conversation_id": conv.conversation_id,
                "site_id": conv.site_id,
                "status": conv.status,
                "human_active": bool(meta.get("human_active")),
                "assigned_agent": meta.get("assigned_agent"),
                "lead_captured": bool(conv.lead_captured),
                # Schéma réel: conversation.visitor_name + chatbot_leads.name
                "lead_name": (conv.visitor_name or (lead.name if lead else None)),
                "lead_phone": (conv.visitor_phone or (lead.phone if lead else None)),
                "message_count": conv.message_count,
                "last_message": last_message.content[:120] if last_message else None,
                "last_message_role": last_message.role if last_message else None,
                "created_at": conv.created_at.isoformat() if conv.created_at else None,
                "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
            }
        )

    return {"conversations": items, "total": len(items)}


@router.get("/admin/conversations/{conversation_id}")
async def get_conversation_detail(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Détail complet: conversation + messages + lead."""
    require_admin(current_user)

    conversation = (
        db.query(ChatbotConversation)
        .filter(ChatbotConversation.conversation_id == conversation_id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = (
        db.query(ChatbotMessage)
        .filter(ChatbotMessage.conversation_id == conversation_id)
        .order_by(ChatbotMessage.created_at.asc())
        .all()
    )
    lead = (
        db.query(ChatbotLead)
        .filter(ChatbotLead.conversation_id == conversation_id)
        .first()
    )
    meta = get_metadata(conversation)

    return {
        "conversation": {
            "conversation_id": conversation.conversation_id,
            "site_id": conversation.site_id,
            "status": conversation.status,
            "human_active": bool(meta.get("human_active")),
            "assigned_agent": meta.get("assigned_agent"),
            "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
            "last_message_at": conversation.last_message_at.isoformat() if conversation.last_message_at else None,
        },
        # Schéma réel: visiteur sur la conversation, lead avec name/email/phone
        "lead": {
            "name": conversation.visitor_name or (lead.name if lead else None),
            "email": conversation.visitor_email or (lead.email if lead else None),
            "phone": conversation.visitor_phone or (lead.phone if lead else None),
        }
        if (conversation.visitor_name or lead)
        else None,
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "human": bool((msg.context_data or {}).get("human")),
                "human_name": (msg.context_data or {}).get("human_name"),
                "agent_used": msg.agent_used,
                "intent": msg.intent,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }
            for msg in messages
        ],
    }


# ============================================================
# Takeover humain / rendu la main / message humain / assign
# ============================================================

@router.post("/admin/conversations/{conversation_id}/takeover")
async def takeover_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """L'humain prend la main: le LLM se met en pause sur cette conversation."""
    require_admin(current_user)

    conversation = (
        db.query(ChatbotConversation)
        .filter(ChatbotConversation.conversation_id == conversation_id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Logique factorisée avec l'API client v1 (B3) — voir
    # backend/chatbot/conversations_service.py.
    conversations_service.prendre_la_main(
        db,
        conversation,
        email_conseiller=current_user.get("email"),
        nom_conseiller=current_user.get("nom"),
    )

    # Debug persistance: la metadata relue depuis la DB juste après commit.
    # Si human_active=False ici → le flush n'écrit pas la colonne JSON
    # (bug ORM subtil) ; si True ici mais False à la lecture suivante →
    # problème réseau/réplication.
    return {
        "conversation_id": conversation_id,
        "status": conversation.status,
        "human_active": bool(get_metadata(conversation).get("human_active")),
        "after_commit_metadata": conversation.conversation_metadata,
    }


@router.post("/admin/conversations/{conversation_id}/release", response_model=TakeoverResponse)
async def release_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """L'humain rend la main: l'IA reprend avec tout l'historique."""
    require_admin(current_user)

    conversation = (
        db.query(ChatbotConversation)
        .filter(ChatbotConversation.conversation_id == conversation_id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Logique factorisée avec l'API client v1 (B3).
    conversations_service.rendre_la_main(db, conversation)

    return TakeoverResponse(conversation_id=conversation_id, status="active", human_active=False)


@router.post("/admin/conversations/{conversation_id}/human-message")
async def send_human_message(
    conversation_id: str,
    request: HumanMessageRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Message envoyé par l'humain (bypass LLM). Stocké avec context_data.human=true."""
    require_admin(current_user)

    conversation = (
        db.query(ChatbotConversation)
        .filter(ChatbotConversation.conversation_id == conversation_id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    content = (request.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Empty message")

    # Logique factorisée avec l'API client v1 (B3).
    message = conversations_service.message_humain(
        db,
        conversation,
        content,
        nom_conseiller=current_user.get("nom"),
    )

    return {
        "ok": True,
        "message_id": message.id,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


@router.post("/admin/conversations/{conversation_id}/assign")
async def assign_agent(
    conversation_id: str,
    request: AssignAgentRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Forcer le prochain routage vers un agent précis (override du router)."""
    require_admin(current_user)

    conversation = (
        db.query(ChatbotConversation)
        .filter(ChatbotConversation.conversation_id == conversation_id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    meta = get_metadata(conversation)
    meta["assigned_agent"] = request.agent_key
    set_metadata(conversation, meta)
    db.commit()

    return {"ok": True, "conversation_id": conversation_id, "assigned_agent": request.agent_key}


# ============================================================
# Debug: schéma réel d'une table (le modèle ORM peut diverger de la DB)
# ============================================================

_ALLOWED_TABLES = {
    "chatbot_leads",
    "chatbot_conversations",
    "chatbot_messages",
    "chatbot_sites",
    "chatbot_analytics",
    "users",
}


@router.get("/admin/debug/schema/{table_name}")
async def inspect_table_schema(
    table_name: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Colonnes réelles d'une table (information_schema) — whitelist stricte."""
    require_admin(current_user)
    if table_name not in _ALLOWED_TABLES:
        raise HTTPException(status_code=400, detail="Table non autorisée")

    from sqlalchemy import text

    rows = db.execute(
        text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = :t ORDER BY ordinal_position"
        ),
        {"t": table_name},
    ).fetchall()
    result: Dict[str, Any] = {table_name: [{"column": r[0], "type": r[1]} for r in rows]}

    # Enums PostgreSQL utilisés par la table (lead_type, status…)
    enum_rows = db.execute(
        text(
            "SELECT t.typname, e.enumlabel FROM pg_type t "
            "JOIN pg_enum e ON e.enumtypid = t.oid ORDER BY t.typname, e.enumsortorder"
        )
    ).fetchall()
    enums: Dict[str, List[str]] = {}
    for typname, enumlabel in enum_rows:
        enums.setdefault(typname, []).append(enumlabel)
    result["enums"] = enums
    return result




# ============================================================
# ADMINISTRATION UNIFIÉE — Utilisateurs, Candidats, Abonnements
# ============================================================

from backend.core.models import Candidat, User
from sqlalchemy import func as sa_func


@router.get("/admin/users")
async def admin_list_users(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Comptes utilisateurs (auth unifiée)."""
    require_admin(current_user)
    users = db.query(User).order_by(User.created_at.desc()).limit(min(limit, 500)).all()
    return {
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "nom": getattr(u, "nom", None),
                "role": u.role,
                "is_active": u.is_active,
                "last_login": u.last_login.isoformat() if u.last_login else None,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ],
        "total": len(users),
    }


@router.get("/admin/candidats")
async def admin_list_candidats(
    statut: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Candidats & diagnostics (leads qualifiés avec score)."""
    require_admin(current_user)
    query = db.query(Candidat)
    if statut:
        query = query.filter(Candidat.statut == statut)
    candidats = query.order_by(Candidat.created_at.desc()).limit(min(limit, 500)).all()
    return {
        "candidats": [
            {
                "id": c.id,
                "nom": c.nom,
                "email": c.email,
                "whatsapp": c.whatsapp,
                "entreprise": c.entreprise,
                "secteur": c.secteur,
                "score": c.score,
                "statut": c.statut,
                "niveau_accompagnement": c.niveau_accompagnement,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in candidats
        ],
        "total": len(candidats),
    }


@router.get("/admin/stats")
async def admin_stats(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """KPIs d'en-tête du cockpit unifié."""
    require_admin(current_user)

    def count(model, *filters):
        q = db.query(sa_func.count(model.id))
        for f in filters:
            q = q.filter(f)
        return q.scalar() or 0

    conv_escalated = (
        db.query(sa_func.count(ChatbotConversation.id))
        .filter(ChatbotConversation.status == "escalated")
        .scalar()
        or 0
    )
    return {
        "conversations": count(ChatbotConversation),
        "conversations_en_attente": conv_escalated,
        "leads_chatbot": count(ChatbotLead),
        "candidats": count(Candidat),
        "candidats_en_attente": count(Candidat, Candidat.statut == "en_attente"),
        "users": count(User),
    }


# ============================================================
# PROVISIONNEMENT DES COMPTES PROPRIÉTAIRES — refonte app Mia (B1)
# ============================================================
#
# Le flux de livraison : ePerformance crée le compte du propriétaire à la mise
# en ligne de son site. Le mot de passe TEMPORAIRE est généré par le backend
# (secrets.token_urlsafe) et renvoyé UNE SEULE FOIS dans la réponse — c'est lui
# qui alimente le fichier de livraison du client. Il n'est ni journalisé, ni
# audité, ni réaffichable : la seule suite possible est « mot de passe perdu →
# réinitialisation ». Le compte naît avec must_change_password=True : tant que
# le propriétaire n'a pas changé son mot de passe, toutes les routes client
# refusent (403) — voir backend/core/auth.py.

import secrets as _secrets
import string as _string

from pydantic import BaseModel, EmailStr, Field

from backend.core.auth import (
    HIERARCHIE_CLIENT,
    ROLE_CLIENT_ADMIN,
    ROLE_CLIENT_OPERATOR,
    ROLE_CLIENT_READER,
)
from backend.core.audit import AuditLog, tracer_audit

#: Alphabet du mot de passe temporaire : token_urlsafe (64 symboles) restreint
#: à un ensemble lisible sans ambiguïté au téléphone (pas de 0/O, 1/l/I).
_ALPHABET_MDP = _string.ascii_letters + _string.digits
_SYMBOLES_EXCLUS = set("O0Il1")
_LONGUEUR_MDP_TEMPORAIRE = 16


def _mot_de_passe_temporaire() -> str:
    """Mot de passe temporaire : 16+ caractères, symboles ambiguës écartés."""
    while True:
        brut = _secrets.token_urlsafe(12)
        propre = "".join(c for c in brut if c not in _SYMBOLES_EXCLUS)
        if len(propre) >= _LONGUEUR_MDP_TEMPORAIRE:
            return propre


class ProvisionnementClientRequest(BaseModel):
    """Demande de création du compte propriétaire d'un site."""

    email: EmailStr
    nom: str = Field(..., min_length=1, max_length=200)
    site_id: str = Field(..., min_length=1, max_length=100)
    role_client: str = Field(
        ROLE_CLIENT_ADMIN,
        description="client_admin | client_operator | client_reader",
    )


@router.post("/admin/clients", status_code=201)
async def provisionner_compte_client(
    corps: ProvisionnementClientRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Crée le compte propriétaire d'un site (auth admin).

    Réponse 201 avec `mot_de_passe_temporaire` — renvoyé UNE SEULE FOIS.
    Le compte peut se connecter immédiatement, mais toutes les routes client
    refusent tant que le mot de passe n'a pas été changé (must_change_password).
    """
    require_admin(current_user)

    role_client = (corps.role_client or "").strip()
    if role_client not in HIERARCHIE_CLIENT:
        raise HTTPException(
            status_code=422,
            detail=f"role_client doit être l'un de : {', '.join(HIERARCHIE_CLIENT)}",
        )

    site = db.query(ChatbotSite).filter(ChatbotSite.site_id == corps.site_id).first()
    if site is None:
        raise HTTPException(
            status_code=404,
            detail=f"Site inconnu : {corps.site_id} — créez-le d'abord (sites/configure)",
        )

    existant = db.query(User).filter(User.email == corps.email).first()
    if existant is not None:
        raise HTTPException(status_code=400, detail="Email already registered")

    mot_de_passe = _mot_de_passe_temporaire()
    utilisateur = User(
        email=corps.email,
        password_hash=get_password_hash(mot_de_passe),
        # role='client' : valeur EXISTANTE de l'enum PostgreSQL — la granularité
        # vit dans role_client (voir models.User pour la décision documentée).
        role="client",
        role_client=role_client,
        site_id=corps.site_id,
        nom=corps.nom,
        must_change_password=True,
        is_active=True,
        created_at=datetime.now(),
    )
    db.add(utilisateur)
    db.commit()
    db.refresh(utilisateur)

    # Trace d'audit — SANS le mot de passe, jamais.
    tracer_audit(
        db,
        "creation_compte_client",
        user_id=utilisateur.id,
        user_email=utilisateur.email,
        site_id=corps.site_id,
        details={
            "role_client": role_client,
            "nom": corps.nom,
            "cree_par": current_user.get("email"),
        },
        ip=_ip_appelant(request),
    )
    db.commit()

    return {
        "user_id": utilisateur.id,
        "email": utilisateur.email,
        "nom": utilisateur.nom,
        "site_id": utilisateur.site_id,
        "role_client": utilisateur.role_client,
        "must_change_password": True,
        # Une seule fois. Jamais journalisé, jamais réaffiché.
        "mot_de_passe_temporaire": mot_de_passe,
    }


@router.get("/admin/clients")
async def lister_comptes_clients(
    site_id: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Comptes propriétaires provisionés (auth admin). Aucun secret renvoyé."""
    require_admin(current_user)

    requete = db.query(User).filter(User.role_client.isnot(None))
    if site_id:
        requete = requete.filter(User.site_id == site_id)
    comptes = requete.order_by(User.created_at.desc()).limit(min(limit, 500)).all()
    return {
        "clients": [
            {
                "id": u.id,
                "email": u.email,
                "nom": u.nom,
                "site_id": u.site_id,
                "role_client": u.role_client,
                "must_change_password": bool(u.must_change_password),
                "totp_enabled": bool(u.totp_enabled),
                "is_active": u.is_active,
                "last_login": u.last_login.isoformat() if u.last_login else None,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in comptes
        ],
        "total": len(comptes),
    }


@router.get("/admin/audit")
async def lire_journal_audit(
    site_id: str | None = None,
    user_id: int | None = None,
    action: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Lecture du journal d'audit (auth admin) — B2.

    Filtres facultatifs combinables : site_id, user_id, action. Les plus
    récentes d'abord. Le journal ne contient jamais de contenu de conversation
    ni de secret : la lecture peut donc être donnée au support sans précaution.
    """
    require_admin(current_user)

    requete = db.query(AuditLog)
    if site_id:
        requete = requete.filter(AuditLog.site_id == site_id)
    if user_id is not None:
        requete = requete.filter(AuditLog.user_id == user_id)
    if action:
        requete = requete.filter(AuditLog.action == action)
    lignes = requete.order_by(AuditLog.date.desc()).limit(min(limit, 500)).all()

    return {
        "audit": [
            {
                "id": ligne.id,
                "user_id": ligne.user_id,
                "user_email": ligne.user_email,
                "site_id": ligne.site_id,
                "action": ligne.action,
                "details": ligne.details,
                "ip": ligne.ip,
                "date": ligne.date.isoformat() if ligne.date else None,
            }
            for ligne in lignes
        ],
        "total": len(lignes),
    }


def _ip_appelant(request: Request) -> str:
    """IP de l'appelant telle qu'arrivée (derrière un proxy Railway, XFF)."""
    transmis = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if transmis:
        return transmis
    return request.client.host if request.client else "inconnue"


# ============================================================
# AGENTS — catalogue des 27 agents IA (Phase 2, Tâche 5.2)
# ============================================================

_AGENTS_DIR = Path(__file__).resolve().parents[2] / "chatbot" / "agents"


def _parse_agent_file(path: Path) -> Optional[Dict[str, Any]]:
    """Extrait key/category/label d'un fichier agent Markdown."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    agent_key = None
    category = None
    label = None

    # Frontmatter YAML (--- ... ---)
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].splitlines():
                if ":" not in line:
                    continue
                k, _, v = line.partition(":")
                k = k.strip().lower()
                v = v.strip().strip('"\'')
                if k == "agent_key" and v:
                    agent_key = v
                elif k == "category" and v:
                    category = v

    # Libellé : "heading # Persona: X" sinon la clé
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# Persona:"):
            label = stripped.split(":", 1)[1].strip()
            break

    key = agent_key or path.stem
    return {
        "key": key,
        "label": label or key.replace("_", " ").replace("-", " ").title(),
        "category": category or path.parent.name,
    }


@router.get("/admin/agents")
async def list_agents_admin(
    current_user: dict = Depends(get_current_user),
):
    """Catalogue des agents IA disponibles (27) — pour le sélecteur d'assignation."""
    require_admin(current_user)

    agents: List[Dict[str, Any]] = []
    if _AGENTS_DIR.is_dir():
        for md_file in sorted(_AGENTS_DIR.rglob("*.md")):
            parsed = _parse_agent_file(md_file)
            if parsed:
                agents.append(parsed)

    agents.sort(key=lambda a: (a["category"], a["key"]))
    return {"agents": agents, "total": len(agents)}


# ============================================================
# NOTIFICATIONS — tâche 6.5
# ============================================================
#
# CODES HTTP CHOISIS, et pourquoi ils ne sont pas tous 200 :
#
#   200  l'envoi a abouti.
#   503  le canal n'est PAS CONFIGURÉ (clés absentes). Ce n'est pas une panne
#        du serveur, mais ce n'est pas un succès non plus : renvoyer 200 ici
#        ferait croire à un envoi parti. Le corps porte l'état exact du canal.
#   502  le canal EST configuré mais le fournisseur a refusé (clé invalide,
#        IP non autorisée, destinataire inconnu). C'est une défaillance d'une
#        dépendance externe — la définition même du 502.
#
# Dans les trois cas, la tentative est TRACÉE en base, et le corps de la
# réponse contient le résultat complet. Aucun de ces chemins ne peut lever
# une exception : `notifications.envoyer()` ne lève jamais.


class NotifyRequest(BaseModel):
    """Demande d'envoi d'une notification."""
    canal: str = Field(
        ...,
        description="telegram | email | webpush | whatsapp",
        examples=["telegram"],
    )
    message: str = Field(..., min_length=1, max_length=4000, description="Corps du message")
    sujet: str = Field("", max_length=200, description="Sujet (objet de l'e-mail, 1re ligne Telegram)")
    destinataire: Optional[str] = Field(
        None,
        description=(
            "Destinataire. Vide = valeur par défaut du canal "
            "(TELEGRAM_ADMIN_CHAT_ID pour Telegram, tous les abonnements actifs pour webpush)."
        ),
    )
    site_id: Optional[str] = Field(None, max_length=100, description="Site concerné (traçabilité)")

    class Config:
        json_schema_extra = {
            "example": {
                "canal": "telegram",
                "sujet": "Nouveau lead",
                "message": "Un visiteur a demandé un diagnostic.",
                "site_id": "eperformance_vitrine",
            }
        }


class PushSubscriptionRequest(BaseModel):
    """Enregistrement d'un abonnement au push navigateur."""
    endpoint: str = Field(..., min_length=10, description="URL du service de push")
    cle_p256dh: str = Field(..., min_length=10, description="Clé publique p256dh du navigateur")
    cle_auth: str = Field(..., min_length=5, description="Secret d'authentification du navigateur")
    libelle: Optional[str] = Field(None, max_length=200, description="Libellé lisible")
    site_id: Optional[str] = Field(None, max_length=100)


@router.get("/notifications")
async def lister_notifications(
    canal: Optional[str] = Query(None, description="Filtrer par canal"),
    statut: Optional[str] = Query(
        None, description="Filtrer par statut : envoye | echec | non_configure"
    ),
    limit: int = Query(50, ge=1, le=200, description="Nombre de lignes (1 à 200)"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Trace des notifications et ÉTAT DES CANAUX (tâche 6.5).

    Répond à deux questions d'un coup, parce qu'elles se posent ensemble :
      1. « Qu'est-ce qui est parti, à qui, quand, et est-ce que c'est passé ? »
         → `notifications` (les plus récentes d'abord) ;
      2. « Pourquoi rien ne part ? » → `canaux`, qui dit pour chaque canal s'il
         est configuré et, sinon, quelle variable manque.

    Le second point est le plus important en pratique : sans lui, un canal non
    configuré ne produit qu'un silence.
    """
    require_admin(current_user)

    requete = db.query(ChatbotNotificationLog)
    if canal:
        requete = requete.filter(ChatbotNotificationLog.canal == canal)
    if statut:
        requete = requete.filter(ChatbotNotificationLog.statut == statut)
    lignes = (
        requete.order_by(ChatbotNotificationLog.created_at.desc())
        .limit(limit)
        .all()
    )

    # Résumé par statut sur TOUT l'historique, pas seulement la page affichée :
    # c'est le chiffre qui dit si un canal ne fonctionne plus.
    from sqlalchemy import func as sa_func

    resume = {
        statut_ligne: total
        for statut_ligne, total in db.query(
            ChatbotNotificationLog.statut, sa_func.count(ChatbotNotificationLog.id)
        )
        .group_by(ChatbotNotificationLog.statut)
        .all()
    }

    # Abonnements push actifs, les deux sources (P3-PUSH).
    abonnements_publics, abonnements_admin = push_abonnements.compter_actifs(db)

    return {
        "canaux": [etat.pour_api() for etat in notifications.etat_canaux()],
        "notifications": [
            {
                "id": ligne.id,
                "canal": ligne.canal,
                "statut": ligne.statut,
                "succes": ligne.succes,
                "destinataire": ligne.destinataire,
                "sujet": ligne.sujet,
                "corps": ligne.corps,
                "code_erreur": ligne.code_erreur,
                "erreur": ligne.erreur,
                "identifiant_fournisseur": ligne.identifiant_fournisseur,
                "auteur": ligne.auteur,
                "duree_ms": ligne.duree_ms,
                "created_at": ligne.created_at.isoformat() if ligne.created_at else None,
                "envoye_le": ligne.envoye_le.isoformat() if ligne.envoye_le else None,
            }
            for ligne in lignes
        ],
        "total": len(lignes),
        "resume": {
            "envoye": resume.get("envoye", 0),
            "echec": resume.get("echec", 0),
            "non_configure": resume.get("non_configure", 0),
        },
        "abonnements_push_actifs": abonnements_publics + abonnements_admin,
        # Détail par source (P3-PUSH) : c'est le chiffre qui dit si le widget
        # transmet bien ses abonnements. Un total seul ne le dirait pas.
        "abonnements_push_detail": {
            "widget": abonnements_publics,
            "admin": abonnements_admin,
        },
    }


@router.get("/admin/push/subscriptions")
async def lister_abonnements_push(
    actifs_seulement: bool = Query(
        False,
        description="Ne garder que les abonnements qui reçoivent encore",
    ),
    limit: int = Query(50, ge=1, le=200, description="Nombre de lignes par source"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Lister les abonnements au push navigateur (P3-PUSH).

    Répond à la question que la trace seule ne permet pas de trancher :
    « les abonnements des visiteurs arrivent-ils, et lesquels reçoivent
    encore ? ». Les DEUX sources sont listées — `widget` (créés par la route
    publique, c'est-à-dire par les navigateurs) et `admin` (créés par la route
    d'administration de la tâche 6.5) — parce que c'est l'ensemble des
    abonnements qui partiront au prochain envoi.

    Les clés de chiffrement ne sont PAS renvoyées : elles sont inutiles au
    diagnostic et n'ont aucune raison de sortir de la base. Les endpoints sont
    tronqués, assez pour rapprocher deux lignes, pas assez pour viser un
    navigateur.
    """
    require_admin(current_user)

    requete_widget = db.query(PushSubscription)
    requete_admin = db.query(ChatbotPushSubscription)
    if actifs_seulement:
        requete_widget = requete_widget.filter(PushSubscription.actif.is_(True))
        requete_admin = requete_admin.filter(ChatbotPushSubscription.est_actif.is_(True))

    lignes_widget = (
        requete_widget.order_by(PushSubscription.id.desc()).limit(limit).all()
    )
    lignes_admin = (
        requete_admin.order_by(ChatbotPushSubscription.id.desc()).limit(limit).all()
    )

    abonnements = [
        {**push_abonnements.vers_api(ligne), "source": "widget"}
        for ligne in lignes_widget
    ]
    abonnements += [
        {
            "id": ligne.id,
            "endpoint_tronque": push_abonnements.tronquer_endpoint(ligne.endpoint),
            "conversation_id": None,
            "site_id": ligne.site_id,
            "actif": bool(ligne.est_actif),
            "date_creation": ligne.created_at.isoformat() if ligne.created_at else None,
            "date_derniere_utilisation": (
                ligne.derniere_reussite.isoformat() if ligne.derniere_reussite else None
            ),
            "user_agent": ligne.user_agent,
            "source": "admin",
        }
        for ligne in lignes_admin
    ]

    actifs_widget, actifs_admin = push_abonnements.compter_actifs(db)
    return {
        "abonnements": abonnements,
        "resume": {
            "widget": {"total": len(lignes_widget), "actifs": actifs_widget},
            "admin": {"total": len(lignes_admin), "actifs": actifs_admin},
        },
        "total": len(abonnements),
    }


@router.post("/admin/notify")
async def envoyer_notification(
    corps: NotifyRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Envoyer une notification par un canal configuré (tâche 6.5).

    L'état du canal est vérifié AVANT l'envoi : si les clés manquent, la
    réponse le dit (503 + `canaux`) et l'envoi n'est pas tenté. La tentative
    est tracée dans les trois cas (succès, échec, non configuré).

    Aucune exception ne peut remonter de cette route : `envoyer()` renvoie un
    résultat, et `tracer()` absorbe ses propres erreurs.
    """
    require_admin(current_user)

    canal = (corps.canal or "").strip().lower()

    # Abonnements actifs, uniquement pour le push : c'est le seul canal dont le
    # destinataire n'est pas une adresse mais un ensemble d'abonnements.
    # P3-PUSH : les deux tables sont lues et dédoublonnées sur l'endpoint, sinon
    # les abonnements créés par le widget ne recevraient jamais rien — c'était
    # exactement le maillon manquant.
    abonnements = None
    if canal == "webpush":
        abonnements = push_abonnements.abonnements_actifs(db)

    resultat = notifications.envoyer(
        canal=canal,
        destinataire=(corps.destinataire or "").strip(),
        sujet=corps.sujet or "",
        message=corps.message,
        abonnements=abonnements,
    )

    # Horodatage de l'utilisation réelle (P3-PUSH) : c'est ce qui permet de
    # repérer un abonnement qui ne sert plus. Écrit seulement si l'envoi a
    # abouti au moins une fois, et seulement sur les abonnements du widget.
    if canal == "webpush" and resultat.succes and abonnements:
        push_abonnements.marquer_utilisation(db, abonnements)

    # Trace dans TOUS les cas. `auteur` = le compte admin qui a déclenché.
    notifications.tracer(
        db,
        resultat,
        sujet=corps.sujet or "",
        message=corps.message,
        auteur=current_user.get("email"),
    )

    corps_reponse = {
        "resultat": resultat.pour_api(),
        "site_id": corps.site_id,
        "canaux": [etat.pour_api() for etat in notifications.etat_canaux()],
    }

    if resultat.statut == "non_configure":
        return JSONResponse(status_code=503, content=corps_reponse)
    if not resultat.succes:
        return JSONResponse(status_code=502, content=corps_reponse)
    return corps_reponse


@router.post("/admin/push/subscriptions")
async def enregistrer_abonnement_push(
    corps: PushSubscriptionRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Enregistrer un abonnement au push navigateur (tâche 6.5).

    Un abonnement est normalement créé par le service worker du navigateur, et
    non par un administrateur. Cet endpoint est donc PROVISOIRE : il existe
    pour que la chaîne (abonnement → stockage → envoi) soit complète et
    testable dès maintenant, alors qu'aucune clé VAPID n'existe en production.
    Le jour où le widget implémentera son côté, cette route sera complétée par
    une route publique équivalente, appelée par le navigateur.

    Refus explicite (503) si le push n'est pas configuré : accepter un
    abonnement qu'on ne pourra jamais servir ne ferait qu'accumuler des lignes
    inutiles et donnerait une fausse impression de fonctionnement.
    """
    require_admin(current_user)

    etat = notifications.etat_canal("webpush")
    if not etat.configure:
        return JSONResponse(
            status_code=503,
            content={
                "abonnement": None,
                "canal": etat.pour_api(),
                "message": (
                    "Push non configuré : l'abonnement n'est pas enregistré. "
                    "Renseigner VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY et ajouter "
                    "'pywebpush' à requirements.txt."
                ),
            },
        )

    existant = (
        db.query(ChatbotPushSubscription)
        .filter(ChatbotPushSubscription.endpoint == corps.endpoint)
        .first()
    )
    if existant:
        # Le navigateur peut régénérer ses clés pour un même endpoint : on
        # remplace les clés et on réactive, plutôt que de créer un doublon
        # (l'endpoint est unique en base).
        existant.cle_p256dh = corps.cle_p256dh
        existant.cle_auth = corps.cle_auth
        existant.libelle = corps.libelle or existant.libelle
        existant.site_id = corps.site_id or existant.site_id
        existant.est_actif = True
        abonnement = existant
        cree = False
    else:
        abonnement = ChatbotPushSubscription(
            endpoint=corps.endpoint,
            cle_p256dh=corps.cle_p256dh,
            cle_auth=corps.cle_auth,
            libelle=corps.libelle,
            site_id=corps.site_id,
            est_actif=True,
        )
        db.add(abonnement)
        cree = True

    db.commit()
    db.refresh(abonnement)

    return {
        "abonnement": {
            "id": abonnement.id,
            "libelle": abonnement.libelle,
            "site_id": abonnement.site_id,
            "est_actif": abonnement.est_actif,
            "cree": cree,
        },
        "canal": etat.pour_api(),
    }


# ============================================================
# MODE APPRENTISSAGE — connaissances du propriétaire (chantier F, 24/09)
# ============================================================


class ConnaissanceCreation(BaseModel):
    """Payload de création/édition d'une connaissance."""
    site_id: str = Field(min_length=1, max_length=100)
    type: str = Field(pattern="^(qr|texte)$")
    question: Optional[str] = Field(default=None, max_length=500)
    reponse: Optional[str] = Field(default=None, max_length=4000)
    contenu: Optional[str] = Field(default=None, max_length=20000)
    source_url: Optional[str] = Field(default=None, max_length=500)


def _connaissance_pour_api(c: ConnaissanceProprietaire) -> dict:
    return {
        "id": c.id,
        "site_id": c.site_id,
        "type": c.type,
        "question": c.question,
        "reponse": c.reponse,
        "contenu": (c.contenu or "")[:300] if c.contenu else None,
        "source_url": c.source_url,
        "actif": c.actif,
        "cree_le": c.cree_le.isoformat() if c.cree_le else None,
        "maj_le": c.maj_le.isoformat() if c.maj_le else None,
    }


@router.get("/admin/connaissances")
async def lister_connaissances(
    site_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Les connaissances d'un site (Q/R + documents), les récentes d'abord."""
    require_admin(current_user)
    lignes = (
        db.query(ConnaissanceProprietaire)
        .filter(ConnaissanceProprietaire.site_id == site_id)
        .order_by(ConnaissanceProprietaire.id.desc())
        .limit(500)
        .all()
    )
    return {"site_id": site_id, "total": len(lignes), "items": [_connaissance_pour_api(c) for c in lignes]}


@router.post("/admin/connaissances", status_code=201)
async def creer_connaissance(
    payload: ConnaissanceCreation,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Ajoute une Q/R ou un document au corpus d'entraînement du site."""
    require_admin(current_user)
    if payload.type == "qr" and (not (payload.question or "").strip() or not (payload.reponse or "").strip()):
        raise HTTPException(status_code=422, detail="une connaissance 'qr' exige question ET réponse")
    if payload.type == "texte" and not (payload.contenu or "").strip():
        raise HTTPException(status_code=422, detail="une connaissance 'texte' exige un contenu")
    item = ConnaissanceProprietaire(
        site_id=payload.site_id,
        type=payload.type,
        question=(payload.question or "").strip() or None,
        reponse=(payload.reponse or "").strip() or None,
        contenu=(payload.contenu or "").strip() or None,
        source_url=(payload.source_url or "").strip() or None,
        actif=True,
        cree_par=str(current_user.get("email") or current_user.get("sub") or "admin"),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    # L'effet est IMMÉDIAT : l'index mémoire du site est reconstruit ici.
    connaissances_moteur.invalider(payload.site_id)
    connaissances_moteur.charger_depuis_db(db, payload.site_id)
    return _connaissance_pour_api(item)


@router.delete("/admin/connaissances/{connaissance_id}")
async def supprimer_connaissance(
    connaissance_id: int,
    site_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Archive une connaissance (actif=false) : traçable, jamais effacé en silence."""
    require_admin(current_user)
    item = (
        db.query(ConnaissanceProprietaire)
        .filter(
            ConnaissanceProprietaire.id == connaissance_id,
            ConnaissanceProprietaire.site_id == site_id,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="connaissance inconnue pour ce site")
    item.actif = False
    db.commit()
    connaissances_moteur.invalider(site_id)
    connaissances_moteur.charger_depuis_db(db, site_id)
    return _connaissance_pour_api(item)

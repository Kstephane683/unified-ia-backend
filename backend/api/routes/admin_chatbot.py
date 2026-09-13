"""
Admin Chatbot routes - ePerformance API Flow

Dashboard admin (web + mobile PWA) pour:
- Lister/détailler les conversations chatbot
- Prendre la main (takeover humain) et rendre la main à l'IA
- Envoyer des messages humains (le LLM est en pause sur la conversation)
- Assigner manuellement un agent IA (override du router)

Auth: JWT existant (POST /api/auth/login) + role admin requis.
Sans migration DB: human_active et assigned_agent vivent dans
conversation_metadata (JSONB) — cf contrat dashboard.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core.auth import get_current_user
from backend.core.database import get_db
from backend.core.models import User
from backend.chatbot.models import ChatbotConversation, ChatbotLead, ChatbotMessage

router = APIRouter(prefix="/api/chatbot", tags=["chatbot"])


def require_admin(current_user: dict) -> None:
    """Garde 403 si l'utilisateur authentifié n'est pas admin."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")


def get_metadata(conversation: ChatbotConversation) -> Dict[str, Any]:
    return conversation.conversation_metadata or {}


def set_metadata(conversation: ChatbotConversation, meta: Dict[str, Any]) -> None:
    """Réassigne une COPIE du dict.

    Colonne JSON plain (pas MutableList): SQLAlchemy détecte le changement
    par IDENTITÉ d'objet au flush. Muter puis réassigner le même objet =
    commit no-op → mutations perdues silencieusement (bug takeover).
    """
    conversation.conversation_metadata = dict(meta)


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

    meta = get_metadata(conversation)
    meta["human_active"] = True
    meta["taken_over_at"] = datetime.utcnow().isoformat()
    set_metadata(conversation, meta)
    conversation.status = "escalated"
    db.commit()
    db.refresh(conversation)

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

    meta = get_metadata(conversation)
    meta["human_active"] = False
    set_metadata(conversation, meta)
    conversation.status = "active"
    db.commit()

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

    message = ChatbotMessage(
        conversation_id=conversation_id,
        role="assistant",  # enum DB: user/assistant/system — humain marqué via context_data
        content=content,
        agent_used=None,
        context_data={"human": True},
    )
    db.add(message)
    conversation.last_message_at = datetime.utcnow()
    db.commit()

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


@router.post("/admin/debug/meta-write/{conversation_id}")
async def debug_meta_write(
    conversation_id: str,
    body: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Diagnostic écriture metadata: écrit une copie fraîche, commit, refresh,
    relit — rend l'état APRÈS commit (distingue échec d'écriture vs cache)."""
    require_admin(current_user)
    conversation = (
        db.query(ChatbotConversation)
        .filter(ChatbotConversation.conversation_id == conversation_id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation.conversation_metadata = dict(body)
    db.commit()
    db.refresh(conversation)
    return {"after_commit_read": conversation.conversation_metadata, "written": body}

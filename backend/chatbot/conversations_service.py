"""
Opérations humaines sur une conversation — factorisation (refonte app Mia).

CE QUE CE MODULE FACTORISE
--------------------------
La prise de main, le rendu de main et le message humain existaient déjà dans
`admin_chatbot.py` (routes /api/chatbot/admin/...). L'API client v1 (B3) expose
les MÊMES opérations sous scope client — la logique ne doit donc exister qu'une
fois. Les routes admin et les routes client appellent ces fonctions ; les
réponses des routes admin restent strictement identiques (y compris le champ
de debug `after_commit_metadata`).

PIÈGE DES COLONNES JSON (connu du projet)
-----------------------------------------
`human_active` vit dans `conversation_metadata` (JSONB). SQLAlchemy compare
`new == old` au flush : une mutation en place d'un dict égal n'est JAMAIS
écrite. Le motif appliqué est celui d'`admin_chatbot.set_metadata` : réassigner
une COPIE du dict puis appeler `flag_modified()`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm.attributes import flag_modified

from backend.chatbot.models import ChatbotConversation, ChatbotMessage


def _ecrire_metadata(conversation: ChatbotConversation, meta: dict) -> None:
    """Réassigne une COPIE et force l'écriture de la colonne JSON."""
    conversation.conversation_metadata = dict(meta)
    flag_modified(conversation, "conversation_metadata")


def prendre_la_main(
    db,
    conversation: ChatbotConversation,
    email_conseiller: Optional[str],
    nom_conseiller: Optional[str] = None,
) -> None:
    """
    L'humain prend la main : le LLM se met en pause sur cette conversation
    (`human_active=True`, statut `escalated`). Commit inclus.
    """
    meta = conversation.conversation_metadata or {}
    meta["human_active"] = True
    meta["taken_over_at"] = datetime.utcnow().isoformat()
    # Nom réel du conseiller (affiché au visiteur, jamais « Conseiller »).
    meta["taken_over_by"] = email_conseiller or "L'équipe ePerformance"
    meta["counselor_name"] = nom_conseiller or meta.get("counselor_name") or "Conseiller ePerformance"
    _ecrire_metadata(conversation, meta)
    conversation.status = "escalated"
    db.commit()
    db.refresh(conversation)


def rendre_la_main(db, conversation: ChatbotConversation) -> None:
    """
    L'humain rend la main : l'IA reprend avec tout l'historique
    (`human_active=False`, statut `active`). Commit inclus.
    """
    meta = conversation.conversation_metadata or {}
    meta["human_active"] = False
    _ecrire_metadata(conversation, meta)
    conversation.status = "active"
    db.commit()
    db.refresh(conversation)


def message_humain(
    db,
    conversation: ChatbotConversation,
    contenu: str,
    nom_conseiller: Optional[str] = None,
) -> ChatbotMessage:
    """
    Message écrit par un humain (bypass LLM). Stocké avec
    `context_data.human=True` — le rôle reste `assistant` (enum DB), le badge
    « Conseiller » du widget lit `human_name`. Commit inclus.
    """
    counselor = (conversation.conversation_metadata or {}).get("counselor_name") \
        or nom_conseiller or "Conseiller ePerformance"
    message = ChatbotMessage(
        conversation_id=conversation.conversation_id,
        role="assistant",
        content=contenu,
        agent_used=None,
        context_data={"human": True, "human_name": counselor},
    )
    db.add(message)
    conversation.last_message_at = datetime.utcnow()
    db.commit()
    db.refresh(message)
    return message

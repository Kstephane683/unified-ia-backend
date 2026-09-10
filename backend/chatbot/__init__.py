"""
Module Chatbot Intelligent ePerformance
Phase 1-S1.4 : Chatbot multi-tenant avec 29 agents IA

Architecture :
- ChatbotService : Orchestrateur principal (pipeline complet)
- IntentDetector : Détection d'intent (regex → ML → LLM)
- ContextBuilder : Construction du contexte (historique + DB + site config)
- AgentRouter : Routing vers les 29 agents IA
- ResponseGenerator : Génération de réponse avec LLM + persona agent
- ActionExecutor : Exécution d'actions (lead capture, notifications, diagnostic)

Intégrations :
- Système communication Phase 1-S1.3 (Email/WhatsApp/Telegram)
- 29 agents IA (Marketing 14, Sales 9, Design 3, Research 2, Product 1)
- Base MySQL existante (candidats, diagnostics, clients_web)
"""

from .models import (
    ChatbotSite,
    ChatbotConversation,
    ChatbotMessage,
    ChatbotLead,
    ChatbotAnalytics
)

__all__ = [
    'ChatbotSite',
    'ChatbotConversation',
    'ChatbotMessage',
    'ChatbotLead',
    'ChatbotAnalytics'
]

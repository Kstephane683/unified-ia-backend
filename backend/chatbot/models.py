"""
Modèles SQLAlchemy pour le système Chatbot ePerformance
Phase 1-S1.4 : 5 tables (sites, conversations, messages, leads, analytics)
"""
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, TIMESTAMP, Enum, JSON, DECIMAL,
    ForeignKey, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.core.database import Base


class ChatbotSite(Base):
    """
    Configuration multi-tenant : chaque site_id a son propre chatbot personnalisé
    Sites : eperformance_vitrine, espace_client, boutique_client_xxx
    """
    __tablename__ = "chatbot_sites"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(String(100), nullable=False, unique=True, index=True, 
                     comment='Identifiant unique du site')
    site_name = Column(String(200), nullable=False, comment='Nom affiché du site')
    site_url = Column(String(500), nullable=True, comment='URL du site')
    
    # Configuration chatbot
    system_prompt = Column(Text, nullable=True, 
                          comment='System prompt personnalisé (override le prompt par défaut)')
    welcome_message = Column(Text, nullable=True, 
                            comment='Message de bienvenue personnalisé')
    theme_config = Column(JSON, nullable=True, 
                         comment='Configuration thème (couleurs, logo, position)')
    
    # Fonctionnalités activées
    features_enabled = Column(JSON, nullable=True, 
                             comment='{"diagnostic": true, "order_capture": true, "support": true}')
    allowed_intents = Column(JSON, nullable=True, 
                            comment='Liste des intents autorisés (null = tous)')
    
    # Rate limiting
    rate_limit_messages_per_minute = Column(Integer, default=20, 
                                           comment='Limite messages par minute par visiteur')
    rate_limit_conversations_per_day = Column(Integer, default=100, 
                                             comment='Limite conversations par jour par IP')
    
    # Notifications
    notification_telegram_enabled = Column(Boolean, default=True, 
                                          comment='Activer notifications Telegram pour leads')
    notification_email_enabled = Column(Boolean, default=True, 
                                       comment='Activer notifications Email pour leads')
    notification_recipients = Column(JSON, nullable=True, 
                                    comment='Liste des destinataires pour ce site')
    
    # Métadonnées
    is_active = Column(Boolean, default=True, index=True, comment='Site actif')
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), 
                       onupdate=func.current_timestamp())
    
    def __repr__(self):
        return f"<ChatbotSite(site_id={self.site_id}, name={self.site_name})>"


class ChatbotConversation(Base):
    """
    Sessions de conversation avec les visiteurs
    Tracking complet : visiteur, statut, métriques, lead capturé
    """
    __tablename__ = "chatbot_conversations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(100), nullable=False, unique=True, index=True, 
                            comment='UUID unique de la conversation')
    site_id = Column(String(100), nullable=False, index=True, 
                    comment='Site où la conversation a lieu')
    
    # Identification visiteur
    user_id = Column(Integer, nullable=True, index=True, 
                    comment='ID candidat/client si connecté (FK candidats.id)')
    visitor_name = Column(String(200), nullable=True, comment='Nom du visiteur (si fourni)')
    visitor_email = Column(String(200), nullable=True, comment='Email du visiteur (si fourni)')
    visitor_phone = Column(String(50), nullable=True, comment='Téléphone du visiteur (si fourni)')
    visitor_ip = Column(String(100), nullable=True, index=True, 
                       comment='IP du visiteur (rate limiting)')
    visitor_info = Column(JSON, nullable=True, 
                         comment='Infos navigateur, device, location')
    
    # État conversation
    status = Column(Enum('active', 'resolved', 'escalated', 'abandoned', name='conversation_status'), 
                   default='active', index=True, comment='État de la conversation')
    started_at = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True, 
                       comment='Début de la conversation')
    last_message_at = Column(TIMESTAMP, server_default=func.current_timestamp(), 
                            comment='Dernier message')
    ended_at = Column(TIMESTAMP, nullable=True, comment='Fin de la conversation')
    
    # Métriques
    message_count = Column(Integer, default=0, comment='Nombre de messages dans la conversation')
    lead_captured = Column(Boolean, default=False, index=True, 
                          comment='Lead capturé pendant cette conversation')
    satisfaction_rating = Column(Integer, nullable=True, 
                                comment='Note satisfaction (1-5) si demandée')
    
    # Métadonnées
    conversation_metadata = Column('metadata', JSON, nullable=True, 
                                   comment='Données additionnelles (utm_source, referrer, etc.)')
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), 
                       onupdate=func.current_timestamp())
    
    def __repr__(self):
        return f"<ChatbotConversation(id={self.conversation_id}, site={self.site_id}, status={self.status})>"


class ChatbotMessage(Base):
    """
    Messages individuels dans les conversations (user + assistant)
    Tracking : intent, agent utilisé, actions, métriques LLM
    """
    __tablename__ = "chatbot_messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(100), 
                            ForeignKey('chatbot_conversations.conversation_id', ondelete='CASCADE'), 
                            nullable=False, index=True, 
                            comment='ID de la conversation parent')
    
    # Message
    role = Column(Enum('user', 'assistant', 'system', name='message_role'), 
                 nullable=False, index=True, comment='Émetteur du message')
    content = Column(Text, nullable=False, comment='Contenu du message')
    
    # Traitement IA (seulement pour messages user)
    intent = Column(String(100), nullable=True, index=True, 
                   comment='Intent détecté (diagnostic_request, order_intent, etc.)')
    intent_confidence = Column(DECIMAL(5, 4), nullable=True, 
                              comment='Confiance de détection (0.0000-1.0000)')
    agent_used = Column(String(100), nullable=True, index=True, 
                       comment='Agent IA utilisé pour générer la réponse')
    
    # Actions exécutées
    actions_executed = Column(JSON, nullable=True, 
                             comment='Actions exécutées (lead_capture, diagnostic_create, etc.)')
    
    # Contexte utilisé
    context_data = Column(JSON, nullable=True, 
                         comment='Contexte utilisé pour générer la réponse')
    
    # Suggestions (quick replies)
    suggestions = Column(JSON, nullable=True, comment='Boutons de suggestion affichés')
    
    # Métriques
    processing_time_ms = Column(Integer, nullable=True, 
                               comment='Temps de traitement en millisecondes')
    llm_provider = Column(String(50), nullable=True, 
                         comment='Provider LLM utilisé (deepseek, claude)')
    llm_tokens_used = Column(Integer, nullable=True, 
                            comment='Tokens utilisés pour cette réponse')
    
    # Métadonnées
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)
    
    def __repr__(self):
        return f"<ChatbotMessage(id={self.id}, role={self.role}, intent={self.intent})>"


class ChatbotLead(Base):
    """
    Leads capturés pendant les conversations
    → Notifications équipe via système communication Phase 1-S1.3
    """
    __tablename__ = "chatbot_leads"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(100), nullable=False, index=True, comment='Conversation source')
    site_id = Column(String(100), nullable=False, index=True, comment='Site source')
    
    # Informations lead (colonnes réelles de la table)
    visitor_name = Column(String(200), nullable=True, comment='Nom du visiteur')
    visitor_email = Column(String(200), nullable=True, index=True, comment='Email du visiteur')
    visitor_phone = Column(String(50), nullable=True, index=True, comment='Téléphone du visiteur')
    conversation_transcript = Column(Text, nullable=True, comment='Transcript de la conversation')
    captured_at = Column(TIMESTAMP, server_default=func.current_timestamp(), comment='Date de capture')
    
    def __repr__(self):
        return f"<ChatbotLead(id={self.id}, name={self.visitor_name})>"


class ChatbotAnalytics(Base):
    """
    Events tracking pour analytics et optimisation
    Types d'events : conversation_start, message_sent, lead_captured, error, etc.
    """
    __tablename__ = "chatbot_analytics"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(String(100), nullable=False, index=True, comment='Site source')
    conversation_id = Column(String(100), nullable=True, index=True, 
                            comment='Conversation associée (si applicable)')
    
    # Event
    event_type = Column(String(100), nullable=False, index=True, 
                       comment='Type d\'event (conversation_start, message_sent, lead_captured, etc.)')
    event_category = Column(String(50), nullable=True, index=True, 
                           comment='Catégorie (engagement, conversion, error, performance)')
    
    # Données event
    event_data = Column(JSON, nullable=True, comment='Données spécifiques à l\'event')
    
    # Contexte
    visitor_ip = Column(String(100), nullable=True, comment='IP du visiteur')
    user_agent = Column(Text, nullable=True, comment='User agent')
    referrer = Column(String(500), nullable=True, comment='Referrer')
    
    # Timing
    timestamp = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True, 
                      comment='Moment de l\'event')
    
    def __repr__(self):
        return f"<ChatbotAnalytics(id={self.id}, type={self.event_type}, site={self.site_id})>"


# Indexes composés pour optimisation des requêtes
Index('idx_conversations_site_status', ChatbotConversation.site_id, ChatbotConversation.status)
Index('idx_conversations_site_started', ChatbotConversation.site_id, ChatbotConversation.started_at)
Index('idx_messages_conversation_created', ChatbotMessage.conversation_id, ChatbotMessage.created_at)
Index('idx_leads_site_captured', ChatbotLead.site_id, ChatbotLead.captured_at)
Index('idx_analytics_site_type_timestamp', ChatbotAnalytics.site_id, ChatbotAnalytics.event_type, ChatbotAnalytics.timestamp)

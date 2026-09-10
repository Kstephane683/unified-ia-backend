"""
Communication system models for unified_ia_system.
Phase 1-S1.3: Email automation, WhatsApp, Telegram integration.

Tables:
- notifications: Journal de toutes les notifications envoyées
- notification_templates: Templates réutilisables
- user_notification_preferences: Préférences utilisateur par canal
- notification_logs: Logs détaillés pour audit RGPD
"""

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, 
    Enum, ForeignKey, Index, TIMESTAMP, JSON
)
from sqlalchemy.orm import relationship
from datetime import datetime
from backend.core.database import Base


class NotificationChannel(Base):
    """
    Canaux de notification disponibles.
    Pre-populated avec email, whatsapp, telegram, sms, in_app.
    """
    __tablename__ = "notification_channels"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False, index=True)  # email, whatsapp, etc.
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    config = Column(JSON, nullable=True)  # Configuration spécifique (API keys, etc.)
    
    created_at = Column(TIMESTAMP, default=datetime.now, nullable=True)
    updated_at = Column(TIMESTAMP, default=datetime.now, onupdate=datetime.now, nullable=True)
    
    def __repr__(self):
        return f"<NotificationChannel(code={self.code}, name={self.name})>"


class NotificationTemplate(Base):
    """
    Templates réutilisables pour notifications.
    Supporte variables {{VAR_NAME}} style Jinja2.
    """
    __tablename__ = "notification_templates"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(100), unique=True, nullable=False, index=True)  # order_confirmation, etc.
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Type de notification
    category = Column(Enum('transactional', 'marketing', 'system', name='notification_category'), 
                     nullable=False, default='transactional', index=True)
    
    # Templates par canal
    email_subject = Column(String(255), nullable=True)
    email_html = Column(Text, nullable=True)
    email_text = Column(Text, nullable=True)  # Fallback plain text
    
    whatsapp_template_name = Column(String(100), nullable=True)  # Nom du template Meta approuvé
    whatsapp_params = Column(JSON, nullable=True)  # Mapping des variables
    
    telegram_message = Column(Text, nullable=True)  # Supporte HTML/Markdown
    telegram_parse_mode = Column(String(20), nullable=True, default='HTML')
    
    sms_message = Column(String(160), nullable=True)  # Max 160 chars
    
    # Variables requises (JSON array)
    required_vars = Column(JSON, nullable=True)  # ["nom", "montant", "date"]
    
    # Metadata
    is_active = Column(Boolean, default=True, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    
    created_at = Column(TIMESTAMP, default=datetime.now, nullable=True)
    updated_at = Column(TIMESTAMP, default=datetime.now, onupdate=datetime.now, nullable=True)
    
    def __repr__(self):
        return f"<NotificationTemplate(code={self.code}, category={self.category})>"


class Notification(Base):
    """
    Journal de toutes les notifications envoyées.
    Audit complet pour RGPD + retry logic + fallback tracking.
    """
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Destinataire
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    recipient_email = Column(String(255), nullable=True)
    recipient_phone = Column(String(50), nullable=True)
    recipient_telegram_chat_id = Column(String(100), nullable=True)
    
    # Template utilisé
    template_code = Column(String(100), nullable=False, index=True)
    template_data = Column(JSON, nullable=True)  # Variables injectées dans le template
    
    # Canal et statut
    channel = Column(Enum('email', 'whatsapp', 'telegram', 'sms', 'in_app', name='notification_channel_enum'), 
                    nullable=False, index=True)
    priority = Column(Enum('critical', 'high', 'medium', 'low', name='notification_priority'), 
                     nullable=False, default='medium', index=True)
    status = Column(Enum('queued', 'processing', 'sent', 'delivered', 'failed', 'bounced', 'fallback', name='notification_status'), 
                   nullable=False, default='queued', index=True)
    
    # Fallback tracking
    fallback_from_channel = Column(String(50), nullable=True)  # Si échec sur un autre canal
    fallback_attempt = Column(Integer, default=0, nullable=False)
    
    # Provider response
    provider = Column(String(50), nullable=True)  # brevo, whatsapp_cloud, telegram_bot
    provider_message_id = Column(String(255), nullable=True, index=True)
    provider_response = Column(JSON, nullable=True)
    
    # Timestamps
    created_at = Column(TIMESTAMP, default=datetime.now, nullable=False, index=True)
    queued_at = Column(TIMESTAMP, nullable=True)
    sent_at = Column(TIMESTAMP, nullable=True)
    delivered_at = Column(TIMESTAMP, nullable=True)
    failed_at = Column(TIMESTAMP, nullable=True)
    
    # Retry logic
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    next_retry_at = Column(TIMESTAMP, nullable=True, index=True)
    
    # Error tracking
    error_message = Column(Text, nullable=True)
    error_code = Column(String(50), nullable=True)
    
    # Tracking (email opens, clicks)
    opened_at = Column(TIMESTAMP, nullable=True)
    clicked_at = Column(TIMESTAMP, nullable=True)
    
    # Idempotency (prevent duplicates)
    idempotency_key = Column(String(255), nullable=True, unique=True, index=True)
    
    # Metadata
    notification_metadata = Column(JSON, nullable=True)  # Additional context (renamed from 'metadata' - SQLAlchemy reserved word)
    
    # Relationships
    user = relationship("User", backref="notifications")
    
    # Indexes
    __table_args__ = (
        Index('idx_notification_user_created', 'user_id', 'created_at'),
        Index('idx_notification_status_created', 'status', 'created_at'),
        Index('idx_notification_retry', 'status', 'next_retry_at'),
    )
    
    def __repr__(self):
        return f"<Notification(id={self.id}, channel={self.channel}, status={self.status})>"


class UserNotificationPreference(Base):
    """
    Préférences de notification par utilisateur.
    GDPR: opt-in/opt-out granulaire par type ET canal.
    """
    __tablename__ = "user_notification_preferences"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    
    # Contact info
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    telegram_chat_id = Column(String(100), nullable=True)
    
    # Préférences granulaires (JSON)
    # Structure: {"order_confirmation": {"email": true, "whatsapp": false}, ...}
    preferences = Column(JSON, nullable=False, default={})
    
    # Quiet hours
    quiet_hours_enabled = Column(Boolean, default=False, nullable=False)
    quiet_hours_start = Column(String(5), nullable=True, default='22:00')  # HH:MM
    quiet_hours_end = Column(String(5), nullable=True, default='08:00')
    timezone = Column(String(50), nullable=False, default='Africa/Abidjan')
    
    # Rate limiting (user-level)
    max_marketing_per_day = Column(Integer, default=3, nullable=False)
    max_marketing_per_week = Column(Integer, default=10, nullable=False)
    
    # Unsubscribe tokens
    unsubscribe_token = Column(String(64), unique=True, nullable=True, index=True)
    
    # Opt-out complet (GDPR)
    opted_out_at = Column(TIMESTAMP, nullable=True)
    opted_out_reason = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(TIMESTAMP, default=datetime.now, nullable=True)
    updated_at = Column(TIMESTAMP, default=datetime.now, onupdate=datetime.now, nullable=True)
    
    # Relationships
    user = relationship("User", backref="notification_preferences")
    
    __table_args__ = (
        Index('idx_user_notif_pref_user', 'user_id'),
    )
    
    def __repr__(self):
        return f"<UserNotificationPreference(user_id={self.user_id})>"


class NotificationLog(Base):
    """
    Logs détaillés pour audit RGPD.
    Enregistre TOUS les changements de préférences, envois, erreurs.
    """
    __tablename__ = "notification_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Contexte
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    notification_id = Column(Integer, ForeignKey('notifications.id'), nullable=True, index=True)
    
    # Type d'événement
    event_type = Column(Enum(
        'preference_changed', 'notification_sent', 'notification_failed', 
        'notification_delivered', 'notification_opened', 'notification_clicked',
        'opted_out', 'opted_in', 'unsubscribed', 'resubscribed',
        name='notification_event_type'
    ), nullable=False, index=True)
    
    # Détails
    event_data = Column(JSON, nullable=True)
    
    # Traçabilité (GDPR Article 30)
    ip_address = Column(String(45), nullable=True)  # Support IPv6
    user_agent = Column(String(255), nullable=True)
    
    # Timestamp
    created_at = Column(TIMESTAMP, default=datetime.now, nullable=False, index=True)
    
    # Relationships
    user = relationship("User", backref="notification_logs")
    notification = relationship("Notification", backref="logs")
    
    __table_args__ = (
        Index('idx_notif_log_user_event', 'user_id', 'event_type', 'created_at'),
    )
    
    def __repr__(self):
        return f"<NotificationLog(event_type={self.event_type}, created_at={self.created_at})>"


class NotificationQueue(Base):
    """
    File d'attente pour notifications différées.
    Alternative à Redis pour persistence.
    """
    __tablename__ = "notification_queue"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    notification_id = Column(Integer, ForeignKey('notifications.id'), nullable=False, unique=True, index=True)
    
    priority = Column(Enum('critical', 'high', 'medium', 'low', name='queue_priority'), 
                     nullable=False, default='medium', index=True)
    
    scheduled_at = Column(TIMESTAMP, nullable=False, index=True)  # Quand envoyer
    locked_at = Column(TIMESTAMP, nullable=True)  # Worker lock
    locked_by = Column(String(100), nullable=True)  # Worker ID
    
    attempts = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    
    created_at = Column(TIMESTAMP, default=datetime.now, nullable=False)
    
    # Relationships
    notification = relationship("Notification", backref="queue_entry")
    
    __table_args__ = (
        Index('idx_queue_scheduled_priority', 'scheduled_at', 'priority', 'locked_at'),
    )
    
    def __repr__(self):
        return f"<NotificationQueue(notification_id={self.notification_id}, scheduled_at={self.scheduled_at})>"

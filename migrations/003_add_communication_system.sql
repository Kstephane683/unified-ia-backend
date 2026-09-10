-- =====================================================================
-- Migration 003: Communication System Tables
-- Phase 1-S1.3: Email automation, WhatsApp, Telegram, notifications
-- =====================================================================

-- Channels disponibles
CREATE TABLE IF NOT EXISTS notification_channels (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    config JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_channel_code (code),
    INDEX idx_channel_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Templates réutilisables
CREATE TABLE IF NOT EXISTS notification_templates (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(100) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category ENUM('transactional', 'marketing', 'system') NOT NULL DEFAULT 'transactional',
    
    -- Email templates
    email_subject VARCHAR(255),
    email_html TEXT,
    email_text TEXT,
    
    -- WhatsApp templates (Meta approved)
    whatsapp_template_name VARCHAR(100),
    whatsapp_params JSON,
    
    -- Telegram templates
    telegram_message TEXT,
    telegram_parse_mode VARCHAR(20) DEFAULT 'HTML',
    
    -- SMS template
    sms_message VARCHAR(160),
    
    -- Variables requises
    required_vars JSON,
    
    -- Metadata
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    version INT NOT NULL DEFAULT 1,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_template_code (code),
    INDEX idx_template_category (category),
    INDEX idx_template_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Journal des notifications envoyées
CREATE TABLE IF NOT EXISTS notifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    
    -- Destinataire
    user_id INT NOT NULL,
    recipient_email VARCHAR(255),
    recipient_phone VARCHAR(50),
    recipient_telegram_chat_id VARCHAR(100),
    
    -- Template
    template_code VARCHAR(100) NOT NULL,
    template_data JSON,
    
    -- Canal et statut
    channel ENUM('email', 'whatsapp', 'telegram', 'sms', 'in_app') NOT NULL,
    priority ENUM('critical', 'high', 'medium', 'low') NOT NULL DEFAULT 'medium',
    status ENUM('queued', 'processing', 'sent', 'delivered', 'failed', 'bounced', 'fallback') NOT NULL DEFAULT 'queued',
    
    -- Fallback tracking
    fallback_from_channel VARCHAR(50),
    fallback_attempt INT NOT NULL DEFAULT 0,
    
    -- Provider response
    provider VARCHAR(50),
    provider_message_id VARCHAR(255),
    provider_response JSON,
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    queued_at TIMESTAMP NULL,
    sent_at TIMESTAMP NULL,
    delivered_at TIMESTAMP NULL,
    failed_at TIMESTAMP NULL,
    
    -- Retry logic
    retry_count INT NOT NULL DEFAULT 0,
    max_retries INT NOT NULL DEFAULT 3,
    next_retry_at TIMESTAMP NULL,
    
    -- Error tracking
    error_message TEXT,
    error_code VARCHAR(50),
    
    -- Tracking (opens, clicks)
    opened_at TIMESTAMP NULL,
    clicked_at TIMESTAMP NULL,
    
    -- Idempotency
    idempotency_key VARCHAR(255) UNIQUE,
    
    -- Metadata
    metadata JSON,
    
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    
    INDEX idx_notification_user (user_id, created_at),
    INDEX idx_notification_status (status, created_at),
    INDEX idx_notification_channel (channel, status),
    INDEX idx_notification_retry (status, next_retry_at),
    INDEX idx_notification_provider_msg (provider_message_id),
    INDEX idx_notification_idempotency (idempotency_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Préférences utilisateur
CREATE TABLE IF NOT EXISTS user_notification_preferences (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    
    -- Contact info
    email VARCHAR(255),
    phone VARCHAR(50),
    telegram_chat_id VARCHAR(100),
    
    -- Préférences granulaires (JSON)
    preferences JSON NOT NULL,
    
    -- Quiet hours
    quiet_hours_enabled TINYINT(1) NOT NULL DEFAULT 0,
    quiet_hours_start VARCHAR(5) DEFAULT '22:00',
    quiet_hours_end VARCHAR(5) DEFAULT '08:00',
    timezone VARCHAR(50) NOT NULL DEFAULT 'Africa/Abidjan',
    
    -- Rate limiting
    max_marketing_per_day INT NOT NULL DEFAULT 3,
    max_marketing_per_week INT NOT NULL DEFAULT 10,
    
    -- Unsubscribe
    unsubscribe_token VARCHAR(64) UNIQUE,
    opted_out_at TIMESTAMP NULL,
    opted_out_reason TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    
    INDEX idx_user_notif_pref_user (user_id),
    INDEX idx_user_notif_pref_token (unsubscribe_token)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Logs pour audit RGPD
CREATE TABLE IF NOT EXISTS notification_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    
    user_id INT,
    notification_id INT,
    
    event_type ENUM(
        'preference_changed', 'notification_sent', 'notification_failed',
        'notification_delivered', 'notification_opened', 'notification_clicked',
        'opted_out', 'opted_in', 'unsubscribed', 'resubscribed'
    ) NOT NULL,
    
    event_data JSON,
    
    -- Traçabilité RGPD
    ip_address VARCHAR(45),
    user_agent VARCHAR(255),
    
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (notification_id) REFERENCES notifications(id) ON DELETE SET NULL,
    
    INDEX idx_notif_log_user_event (user_id, event_type, created_at),
    INDEX idx_notif_log_notification (notification_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- File d'attente (alternative à Redis)
CREATE TABLE IF NOT EXISTS notification_queue (
    id INT AUTO_INCREMENT PRIMARY KEY,
    
    notification_id INT NOT NULL UNIQUE,
    
    priority ENUM('critical', 'high', 'medium', 'low') NOT NULL DEFAULT 'medium',
    
    scheduled_at TIMESTAMP NOT NULL,
    locked_at TIMESTAMP NULL,
    locked_by VARCHAR(100),
    
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 3,
    
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (notification_id) REFERENCES notifications(id) ON DELETE CASCADE,
    
    INDEX idx_queue_scheduled (scheduled_at, priority, locked_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================================================
-- Données initiales: Canaux de notification
-- =====================================================================

INSERT INTO notification_channels (code, name, is_active, config) VALUES
('email', 'Email', 1, JSON_OBJECT('provider', 'brevo')),
('whatsapp', 'WhatsApp', 1, JSON_OBJECT('provider', 'whatsapp_cloud')),
('telegram', 'Telegram', 1, JSON_OBJECT('provider', 'telegram_bot')),
('sms', 'SMS', 0, JSON_OBJECT('provider', 'twilio')),
('in_app', 'In-App', 1, JSON_OBJECT('provider', 'internal'));

-- =====================================================================
-- Templates de base
-- =====================================================================

INSERT INTO notification_templates (code, name, category, email_subject, email_html, email_text, is_active) VALUES
(
    'welcome_email',
    'Email de bienvenue',
    'transactional',
    'Bienvenue sur ePerformance ! 🎉',
    '<h1>Bienvenue {{nom}} !</h1><p>Nous sommes ravis de vous compter parmi nous.</p>',
    'Bienvenue {{nom}} ! Nous sommes ravis de vous compter parmi nous.',
    1
),
(
    'password_reset',
    'Réinitialisation mot de passe',
    'transactional',
    'Réinitialisation de votre mot de passe',
    '<h1>Code de vérification</h1><p>Votre code: <strong>{{code}}</strong></p><p>Valable 10 minutes.</p>',
    'Votre code de vérification: {{code}}. Valable 10 minutes.',
    1
),
(
    'order_confirmation',
    'Confirmation de commande',
    'transactional',
    'Commande {{numero}} confirmée ✅',
    '<h1>Commande confirmée</h1><p>Merci {{nom}} ! Votre commande #{{numero}} a bien été enregistrée.</p>',
    'Commande #{{numero}} confirmée. Merci de votre confiance !',
    1
);

-- =====================================================================
-- Vérification de l'installation
-- =====================================================================

SELECT 
    'notification_channels' as table_name, 
    COUNT(*) as row_count 
FROM notification_channels

UNION ALL

SELECT 
    'notification_templates' as table_name, 
    COUNT(*) as row_count 
FROM notification_templates

UNION ALL

SELECT 
    'notifications' as table_name, 
    COUNT(*) as row_count 
FROM notifications

UNION ALL

SELECT 
    'user_notification_preferences' as table_name, 
    COUNT(*) as row_count 
FROM user_notification_preferences;

-- =====================================================================
-- Notes de migration
-- =====================================================================
-- 
-- Pour appliquer cette migration:
--   mysql -u unified_dev -pdev_password_2026 unified_ia_dev < 003_add_communication_system.sql
--
-- Rollback (si nécessaire):
--   DROP TABLE IF EXISTS notification_queue;
--   DROP TABLE IF EXISTS notification_logs;
--   DROP TABLE IF EXISTS user_notification_preferences;
--   DROP TABLE IF EXISTS notifications;
--   DROP TABLE IF EXISTS notification_templates;
--   DROP TABLE IF EXISTS notification_channels;
-- 
-- =====================================================================

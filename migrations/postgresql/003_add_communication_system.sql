-- =====================================================================
-- Migration 003: Communication System Tables
-- Phase 1-S1.3: Email automation, WhatsApp, Telegram, notifications
-- PostgreSQL version
-- =====================================================================

-- =====================================================================
-- ENUM TYPES
-- =====================================================================

DO $$ BEGIN
    CREATE TYPE notification_category AS ENUM ('transactional', 'marketing', 'system');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE notification_channel AS ENUM ('email', 'whatsapp', 'telegram', 'sms', 'in_app');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE notification_priority AS ENUM ('critical', 'high', 'medium', 'low');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE notification_status AS ENUM ('queued', 'processing', 'sent', 'delivered', 'failed', 'bounced', 'fallback');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE notification_event_type AS ENUM (
        'preference_changed', 'notification_sent', 'notification_failed',
        'notification_delivered', 'notification_opened', 'notification_clicked',
        'opted_out', 'opted_in', 'unsubscribed', 'resubscribed'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE queue_priority AS ENUM ('critical', 'high', 'medium', 'low');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- =====================================================================
-- Channels disponibles
-- =====================================================================

CREATE TABLE IF NOT EXISTS notification_channels (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    config JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notification_channels_code ON notification_channels(code);
CREATE INDEX IF NOT EXISTS idx_notification_channels_active ON notification_channels(is_active);

-- =====================================================================
-- Templates réutilisables
-- =====================================================================

CREATE TABLE IF NOT EXISTS notification_templates (
    id SERIAL PRIMARY KEY,
    code VARCHAR(100) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category notification_category NOT NULL DEFAULT 'transactional',
    
    -- Email templates
    email_subject VARCHAR(255),
    email_html TEXT,
    email_text TEXT,
    
    -- WhatsApp templates (Meta approved)
    whatsapp_template_name VARCHAR(100),
    whatsapp_params JSONB,
    
    -- Telegram templates
    telegram_message TEXT,
    telegram_parse_mode VARCHAR(20) DEFAULT 'HTML',
    
    -- SMS template
    sms_message VARCHAR(160),
    
    -- Variables requises
    required_vars JSONB,
    
    -- Metadata
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    version INT NOT NULL DEFAULT 1,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notification_templates_code ON notification_templates(code);
CREATE INDEX IF NOT EXISTS idx_notification_templates_category ON notification_templates(category);
CREATE INDEX IF NOT EXISTS idx_notification_templates_active ON notification_templates(is_active);

-- =====================================================================
-- Journal des notifications envoyées
-- =====================================================================

CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    
    -- Destinataire
    user_id INT NOT NULL,
    recipient_email VARCHAR(255),
    recipient_phone VARCHAR(50),
    recipient_telegram_chat_id VARCHAR(100),
    
    -- Template
    template_code VARCHAR(100) NOT NULL,
    template_data JSONB,
    
    -- Canal et statut
    channel notification_channel NOT NULL,
    priority notification_priority NOT NULL DEFAULT 'medium',
    status notification_status NOT NULL DEFAULT 'queued',
    
    -- Fallback tracking
    fallback_from_channel VARCHAR(50),
    fallback_attempt INT NOT NULL DEFAULT 0,
    
    -- Provider response
    provider VARCHAR(50),
    provider_message_id VARCHAR(255),
    provider_response JSONB,
    
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
    metadata JSONB
);

-- Indexes for notifications
CREATE INDEX IF NOT EXISTS idx_notifications_user_created ON notifications(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_status_created ON notifications(status, created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_channel_status ON notifications(channel, status);
CREATE INDEX IF NOT EXISTS idx_notifications_status_retry ON notifications(status, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_notifications_provider_msg ON notifications(provider_message_id);
CREATE INDEX IF NOT EXISTS idx_notifications_idempotency ON notifications(idempotency_key);

-- =====================================================================
-- Préférences utilisateur
-- =====================================================================

CREATE TABLE IF NOT EXISTS user_notification_preferences (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL,
    
    -- Contact info
    email VARCHAR(255),
    phone VARCHAR(50),
    telegram_chat_id VARCHAR(100),
    
    -- Préférences granulaires (JSON)
    preferences JSONB NOT NULL,
    
    -- Quiet hours
    quiet_hours_enabled BOOLEAN NOT NULL DEFAULT FALSE,
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
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for user_notification_preferences
CREATE INDEX IF NOT EXISTS idx_user_notification_preferences_user ON user_notification_preferences(user_id);
CREATE INDEX IF NOT EXISTS idx_user_notification_preferences_token ON user_notification_preferences(unsubscribe_token);

-- =====================================================================
-- Logs pour audit RGPD
-- =====================================================================

CREATE TABLE IF NOT EXISTS notification_logs (
    id SERIAL PRIMARY KEY,
    
    user_id INT,
    notification_id INT,
    
    event_type notification_event_type NOT NULL,
    
    event_data JSONB,
    
    -- Traçabilité RGPD
    ip_address VARCHAR(45),
    user_agent VARCHAR(255),
    
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for notification_logs
CREATE INDEX IF NOT EXISTS idx_notification_logs_user_event ON notification_logs(user_id, event_type, created_at);
CREATE INDEX IF NOT EXISTS idx_notification_logs_notification ON notification_logs(notification_id);

-- =====================================================================
-- File d'attente (alternative à Redis)
-- =====================================================================

CREATE TABLE IF NOT EXISTS notification_queue (
    id SERIAL PRIMARY KEY,
    
    notification_id INT NOT NULL UNIQUE,
    
    priority queue_priority NOT NULL DEFAULT 'medium',
    
    scheduled_at TIMESTAMP NOT NULL,
    locked_at TIMESTAMP NULL,
    locked_by VARCHAR(100),
    
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 3,
    
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index for notification_queue
CREATE INDEX IF NOT EXISTS idx_notification_queue_scheduled ON notification_queue(scheduled_at, priority, locked_at);

-- =====================================================================
-- FOREIGN KEY CONSTRAINTS
-- =====================================================================

-- Foreign keys for notifications (uncomment when users table exists)
-- ALTER TABLE notifications 
-- ADD CONSTRAINT fk_notifications_user 
-- FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- Foreign keys for user_notification_preferences (uncomment when users table exists)
-- ALTER TABLE user_notification_preferences 
-- ADD CONSTRAINT fk_user_notification_preferences_user 
-- FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- Foreign keys for notification_logs (uncomment when users and notifications tables exist)
-- ALTER TABLE notification_logs 
-- ADD CONSTRAINT fk_notification_logs_user 
-- FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;

-- ALTER TABLE notification_logs 
-- ADD CONSTRAINT fk_notification_logs_notification 
-- FOREIGN KEY (notification_id) REFERENCES notifications(id) ON DELETE SET NULL;

-- Foreign key for notification_queue
ALTER TABLE notification_queue 
ADD CONSTRAINT fk_notification_queue_notification 
FOREIGN KEY (notification_id) REFERENCES notifications(id) ON DELETE CASCADE;

-- =====================================================================
-- TRIGGER FUNCTIONS for updated_at timestamps
-- =====================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply triggers to tables with updated_at
CREATE TRIGGER update_notification_channels_updated_at BEFORE UPDATE ON notification_channels
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_notification_templates_updated_at BEFORE UPDATE ON notification_templates
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_notification_preferences_updated_at BEFORE UPDATE ON user_notification_preferences
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =====================================================================
-- Données initiales: Canaux de notification
-- =====================================================================

INSERT INTO notification_channels (code, name, is_active, config) VALUES
('email', 'Email', TRUE, json_build_object('provider', 'brevo')::jsonb),
('whatsapp', 'WhatsApp', TRUE, json_build_object('provider', 'whatsapp_cloud')::jsonb),
('telegram', 'Telegram', TRUE, json_build_object('provider', 'telegram_bot')::jsonb),
('sms', 'SMS', FALSE, json_build_object('provider', 'twilio')::jsonb),
('in_app', 'In-App', TRUE, json_build_object('provider', 'internal')::jsonb)
ON CONFLICT (code) DO NOTHING;

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
    TRUE
),
(
    'password_reset',
    'Réinitialisation mot de passe',
    'transactional',
    'Réinitialisation de votre mot de passe',
    '<h1>Code de vérification</h1><p>Votre code: <strong>{{code}}</strong></p><p>Valable 10 minutes.</p>',
    'Votre code de vérification: {{code}}. Valable 10 minutes.',
    TRUE
),
(
    'order_confirmation',
    'Confirmation de commande',
    'transactional',
    'Commande {{numero}} confirmée ✅',
    '<h1>Commande confirmée</h1><p>Merci {{nom}} ! Votre commande #{{numero}} a bien été enregistrée.</p>',
    'Commande #{{numero}} confirmée. Merci de votre confiance !',
    TRUE
)
ON CONFLICT (code) DO NOTHING;

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
--   psql -U unified_dev -d unified_ia_dev -f 003_add_communication_system.sql
--
-- Rollback (si nécessaire):
--   DROP TABLE IF EXISTS notification_queue CASCADE;
--   DROP TABLE IF EXISTS notification_logs CASCADE;
--   DROP TABLE IF EXISTS user_notification_preferences CASCADE;
--   DROP TABLE IF EXISTS notifications CASCADE;
--   DROP TABLE IF EXISTS notification_templates CASCADE;
--   DROP TABLE IF EXISTS notification_channels CASCADE;
--   DROP TYPE IF EXISTS notification_category CASCADE;
--   DROP TYPE IF EXISTS notification_channel CASCADE;
--   DROP TYPE IF EXISTS notification_priority CASCADE;
--   DROP TYPE IF EXISTS notification_status CASCADE;
--   DROP TYPE IF EXISTS notification_event_type CASCADE;
--   DROP TYPE IF EXISTS queue_priority CASCADE;
-- 
-- =====================================================================

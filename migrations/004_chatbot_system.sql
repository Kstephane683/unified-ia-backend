-- ============================================================
-- Migration 004 : Chatbot ePerformance - Système Multi-Tenant
-- Phase 1-S1.4 : 5 tables (sites, conversations, messages, leads, analytics)
-- Date : 2026-09-10
-- ============================================================
-- 
-- Ordre d'exécution :
-- 1. chatbot_sites (config multi-tenant)
-- 2. chatbot_conversations (sessions)
-- 3. chatbot_messages (historique messages)
-- 4. chatbot_leads (leads capturés)
-- 5. chatbot_analytics (events tracking)
--
-- Indexes composés pour performance optimale
-- ============================================================

USE unified_ia_dev;

-- ============================================================
-- TABLE 1 : chatbot_sites
-- Configuration multi-tenant : chaque site a son propre chatbot
-- ============================================================

CREATE TABLE IF NOT EXISTS chatbot_sites (
    id INT AUTO_INCREMENT PRIMARY KEY,
    
    -- Identification site
    site_id VARCHAR(100) NOT NULL UNIQUE COMMENT 'Identifiant unique du site (ex: eperformance_vitrine, restaurant_chez_amina)',
    site_name VARCHAR(200) NOT NULL COMMENT 'Nom affiché du site',
    site_url VARCHAR(500) NULL COMMENT 'URL du site',
    
    -- Configuration chatbot personnalisée
    system_prompt TEXT NULL COMMENT 'System prompt personnalisé (override le prompt par défaut)',
    business_context TEXT NULL COMMENT 'Context métier du client (secteur, produits, services)',
    sector VARCHAR(100) NULL COMMENT 'Secteur d''activité (restaurant, mlm, ecommerce, salon_beaute, coach_formateur)',
    welcome_message TEXT NULL COMMENT 'Message de bienvenue personnalisé',
    theme JSON NULL COMMENT 'Configuration thème (couleurs, logo, avatar, position)',
    
    -- Fonctionnalités activées
    features_enabled JSON NULL COMMENT '{"diagnostic": true, "order_capture": true, "support": true}',
    allowed_intents JSON NULL COMMENT 'Liste des intents autorisés (null = tous)',
    
    -- Rate limiting (anti-spam)
    rate_limit_messages_per_minute INT DEFAULT 20 COMMENT 'Limite messages par minute par visiteur',
    rate_limit_conversations_per_day INT DEFAULT 100 COMMENT 'Limite conversations par jour par IP',
    
    -- Notifications équipe
    notification_telegram_enabled BOOLEAN DEFAULT TRUE COMMENT 'Activer notifications Telegram pour leads',
    notification_email_enabled BOOLEAN DEFAULT TRUE COMMENT 'Activer notifications Email pour leads',
    notification_recipients JSON NULL COMMENT 'Liste des destinataires pour ce site',
    
    -- Métadonnées
    is_active BOOLEAN DEFAULT TRUE COMMENT 'Site actif',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- Indexes
    INDEX idx_site_id (site_id),
    INDEX idx_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Configuration multi-tenant des chatbots par site';


-- ============================================================
-- TABLE 2 : chatbot_conversations
-- Sessions de conversation avec tracking complet
-- ============================================================

CREATE TABLE IF NOT EXISTS chatbot_conversations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    
    -- Identification
    conversation_id VARCHAR(100) NOT NULL UNIQUE COMMENT 'UUID unique de la conversation (généré backend)',
    site_id VARCHAR(100) NOT NULL COMMENT 'Site où la conversation a lieu (FK chatbot_sites.site_id)',
    
    -- Identification visiteur
    user_id INT NULL COMMENT 'ID candidat/client si connecté (FK candidats.id)',
    visitor_name VARCHAR(200) NULL COMMENT 'Nom du visiteur (si fourni)',
    visitor_email VARCHAR(200) NULL COMMENT 'Email du visiteur (si fourni)',
    visitor_phone VARCHAR(50) NULL COMMENT 'Téléphone du visiteur (si fourni)',
    visitor_ip VARCHAR(100) NULL COMMENT 'IP du visiteur (rate limiting)',
    visitor_info JSON NULL COMMENT 'Infos navigateur, device, location, utm_params',
    
    -- État conversation
    status ENUM('active', 'resolved', 'escalated', 'abandoned') DEFAULT 'active' COMMENT 'État de la conversation',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Début de la conversation',
    last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Dernier message (MAJ à chaque message)',
    ended_at TIMESTAMP NULL COMMENT 'Fin de la conversation',
    
    -- Métriques
    message_count INT DEFAULT 0 COMMENT 'Nombre de messages dans la conversation',
    lead_captured BOOLEAN DEFAULT FALSE COMMENT 'Lead capturé pendant cette conversation',
    satisfaction_rating INT NULL COMMENT 'Note satisfaction (1-5) si demandée',
    
    -- Métadonnées
    metadata JSON NULL COMMENT 'Données additionnelles (utm_source, referrer, etc.)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- Indexes
    INDEX idx_conversation_id (conversation_id),
    INDEX idx_site_id (site_id),
    INDEX idx_user_id (user_id),
    INDEX idx_visitor_ip (visitor_ip),
    INDEX idx_status (status),
    INDEX idx_started_at (started_at),
    INDEX idx_lead_captured (lead_captured),
    
    -- Index composé pour requêtes fréquentes
    INDEX idx_site_status (site_id, status),
    INDEX idx_site_started (site_id, started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Sessions de conversation chatbot';


-- ============================================================
-- TABLE 3 : chatbot_messages
-- Historique complet des messages (user + assistant)
-- ============================================================

CREATE TABLE IF NOT EXISTS chatbot_messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    
    -- Association conversation
    conversation_id VARCHAR(100) NOT NULL COMMENT 'ID de la conversation parent',
    
    -- Message
    role ENUM('user', 'assistant', 'system') NOT NULL COMMENT 'Émetteur du message',
    content TEXT NOT NULL COMMENT 'Contenu du message',
    
    -- Traitement IA (seulement pour messages user)
    intent VARCHAR(100) NULL COMMENT 'Intent détecté (diagnostic_request, order_intent, etc.)',
    intent_confidence DECIMAL(5, 4) NULL COMMENT 'Confiance de détection (0.0000-1.0000)',
    agent_used VARCHAR(100) NULL COMMENT 'Agent IA utilisé pour générer la réponse',
    
    -- Actions exécutées
    actions JSON NULL COMMENT 'Actions exécutées (lead_capture, diagnostic_create, etc.)',
    
    -- Contexte utilisé pour générer la réponse
    context_data JSON NULL COMMENT 'Contexte utilisé (user profile, diagnostics, history)',
    
    -- Suggestions (quick replies)
    suggestions JSON NULL COMMENT 'Boutons de suggestion affichés',
    
    -- Métriques LLM
    processing_time_ms INT NULL COMMENT 'Temps de traitement en millisecondes',
    llm_provider VARCHAR(50) NULL COMMENT 'Provider LLM utilisé (deepseek, claude, openai)',
    llm_tokens_used INT NULL COMMENT 'Tokens utilisés pour cette réponse',
    llm_cost_usd DECIMAL(10, 6) NULL COMMENT 'Coût approximatif en USD',
    
    -- Métadonnées
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Indexes
    INDEX idx_conversation_id (conversation_id),
    INDEX idx_role (role),
    INDEX idx_intent (intent),
    INDEX idx_agent_used (agent_used),
    INDEX idx_created_at (created_at),
    
    -- Index composé pour historique chronologique
    INDEX idx_conversation_created (conversation_id, created_at),
    
    -- Foreign key
    FOREIGN KEY (conversation_id) REFERENCES chatbot_conversations(conversation_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Historique messages chatbot (user + assistant)';


-- ============================================================
-- TABLE 4 : chatbot_leads
-- Leads capturés pendant les conversations → Notifications
-- ============================================================

CREATE TABLE IF NOT EXISTS chatbot_leads (
    id INT AUTO_INCREMENT PRIMARY KEY,
    
    -- Source
    conversation_id VARCHAR(100) NOT NULL COMMENT 'Conversation source',
    site_id VARCHAR(100) NOT NULL COMMENT 'Site source',
    
    -- Informations lead
    lead_name VARCHAR(200) NULL COMMENT 'Nom du lead (alias: visitor_name)',
    lead_email VARCHAR(200) NULL COMMENT 'Email du lead (alias: visitor_email)',
    lead_phone VARCHAR(50) NULL COMMENT 'Téléphone du lead (alias: visitor_phone)',
    lead_intent VARCHAR(100) NULL COMMENT 'Intent principal du lead',
    lead_temperature ENUM('cold', 'warm', 'hot') DEFAULT 'warm' COMMENT 'Température du lead',
    
    -- Données conversation
    conversation_summary TEXT NULL COMMENT 'Résumé de la conversation',
    conversation_transcript TEXT NULL COMMENT 'Transcript complet de la conversation',
    
    -- Qualification
    needs_identified JSON NULL COMMENT 'Besoins identifiés pendant la conversation',
    budget_range VARCHAR(100) NULL COMMENT 'Budget mentionné',
    timeline VARCHAR(100) NULL COMMENT 'Timeline mentionnée (urgent, 1 mois, 3 mois, etc.)',
    
    -- Traitement
    is_processed BOOLEAN DEFAULT FALSE COMMENT 'Lead traité par l''équipe',
    processed_at TIMESTAMP NULL COMMENT 'Date de traitement',
    processed_by INT NULL COMMENT 'ID utilisateur qui a traité',
    notes TEXT NULL COMMENT 'Notes ajoutées par l''équipe',
    
    -- Notifications envoyées
    notification_sent BOOLEAN DEFAULT FALSE COMMENT 'Notification envoyée',
    notification_telegram_sent BOOLEAN DEFAULT FALSE COMMENT 'Notification Telegram envoyée',
    notification_email_sent BOOLEAN DEFAULT FALSE COMMENT 'Notification Email envoyée',
    
    -- Métadonnées
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Date de capture',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- Indexes
    INDEX idx_conversation_id (conversation_id),
    INDEX idx_site_id (site_id),
    INDEX idx_lead_email (lead_email),
    INDEX idx_lead_phone (lead_phone),
    INDEX idx_lead_temperature (lead_temperature),
    INDEX idx_is_processed (is_processed),
    INDEX idx_captured_at (captured_at),
    
    -- Index composé pour dashboard leads
    INDEX idx_site_captured (site_id, captured_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Leads capturés via chatbot';


-- ============================================================
-- TABLE 5 : chatbot_analytics
-- Events tracking pour analytics et optimisation
-- ============================================================

CREATE TABLE IF NOT EXISTS chatbot_analytics (
    id INT AUTO_INCREMENT PRIMARY KEY,
    
    -- Source
    site_id VARCHAR(100) NOT NULL COMMENT 'Site source',
    conversation_id VARCHAR(100) NULL COMMENT 'Conversation associée (si applicable)',
    
    -- Event
    event_type VARCHAR(100) NOT NULL COMMENT 'Type d''event (conversation_start, message_sent, lead_captured, error, etc.)',
    event_category VARCHAR(50) NULL COMMENT 'Catégorie (engagement, conversion, error, performance)',
    
    -- Données event
    event_data JSON NULL COMMENT 'Données spécifiques à l''event',
    
    -- Contexte visiteur
    visitor_ip VARCHAR(100) NULL COMMENT 'IP du visiteur',
    user_agent TEXT NULL COMMENT 'User agent',
    referrer VARCHAR(500) NULL COMMENT 'Referrer',
    
    -- Timing
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Moment de l''event',
    
    -- Indexes
    INDEX idx_site_id (site_id),
    INDEX idx_conversation_id (conversation_id),
    INDEX idx_event_type (event_type),
    INDEX idx_event_category (event_category),
    INDEX idx_timestamp (timestamp),
    
    -- Index composé pour analytics dashboard
    INDEX idx_site_type_timestamp (site_id, event_type, timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Events tracking chatbot';


-- ============================================================
-- DONNÉES INITIALES : Site ePerformance (vitrine)
-- ============================================================

INSERT INTO chatbot_sites (
    site_id,
    site_name,
    site_url,
    system_prompt,
    business_context,
    sector,
    welcome_message,
    theme,
    features_enabled,
    is_active
) VALUES (
    'eperformance_vitrine',
    'ePerformance',
    'https://eperformance.pro',
    NULL, -- Utilise le system prompt par défaut
    'Agence marketing digital automatisé pour PME africaines (Côte d''Ivoire). Offres principales : Pack Découverte 100k FCFA (site + chatbot IA), Diagnostic Stratégique Gratuit (lead magnet), Formations MLM. Solutions sectorielles : MLM, Restaurant, E-commerce, Salon beauté, Coach/Formateur.',
    'marketing_agency',
    '👋 Bonjour ! Je suis l''assistant virtuel ePerformance. Je peux vous aider à découvrir le Pack Découverte 100k FCFA, faire votre diagnostic gratuit, ou en savoir plus sur nos services.',
    JSON_OBJECT(
        'primary_color', '#c9a96e',
        'secondary_color', '#08080c',
        'avatar_emoji', '⚡',
        'position', 'bottom-right'
    ),
    JSON_OBJECT(
        'diagnostic', TRUE,
        'order_capture', TRUE,
        'support', TRUE,
        'mlm_advice', TRUE,
        'content_strategy', TRUE,
        'seo_audit', TRUE
    ),
    TRUE
) ON DUPLICATE KEY UPDATE
    site_name = VALUES(site_name),
    business_context = VALUES(business_context),
    updated_at = CURRENT_TIMESTAMP;


-- ============================================================
-- DONNÉES INITIALES : Espace Client ePerformance
-- ============================================================

INSERT INTO chatbot_sites (
    site_id,
    site_name,
    site_url,
    business_context,
    sector,
    welcome_message,
    theme,
    features_enabled,
    is_active
) VALUES (
    'eperformance_espace_client',
    'ePerformance - Espace Client',
    'https://espace-client.eperformance.pro',
    'Espace client ePerformance pour suivi projets, support technique, formations, et gestion abonnements.',
    'client_portal',
    '👋 Bienvenue dans votre espace client ePerformance ! Comment puis-je vous aider aujourd''hui ?',
    JSON_OBJECT(
        'primary_color', '#c9a96e',
        'secondary_color', '#08080c',
        'avatar_emoji', '🔧',
        'position', 'bottom-right'
    ),
    JSON_OBJECT(
        'support', TRUE,
        'project_tracking', TRUE,
        'billing', TRUE,
        'training', TRUE
    ),
    TRUE
) ON DUPLICATE KEY UPDATE
    site_name = VALUES(site_name),
    updated_at = CURRENT_TIMESTAMP;


-- ============================================================
-- VÉRIFICATIONS POST-MIGRATION
-- ============================================================

-- Vérifier que toutes les tables existent
SELECT 
    'chatbot_sites' AS table_name,
    COUNT(*) AS row_count
FROM chatbot_sites
UNION ALL
SELECT 'chatbot_conversations', COUNT(*) FROM chatbot_conversations
UNION ALL
SELECT 'chatbot_messages', COUNT(*) FROM chatbot_messages
UNION ALL
SELECT 'chatbot_leads', COUNT(*) FROM chatbot_leads
UNION ALL
SELECT 'chatbot_analytics', COUNT(*) FROM chatbot_analytics;

-- Afficher la config site ePerformance
SELECT 
    site_id,
    site_name,
    sector,
    is_active,
    created_at
FROM chatbot_sites
WHERE site_id = 'eperformance_vitrine';


-- ============================================================
-- NOTES IMPORTANTES
-- ============================================================
-- 
-- 1. RATE LIMITING
--    - 20 messages/minute par visiteur
--    - 100 conversations/jour par IP
--    - Implémenté dans ChatbotService
-- 
-- 2. NOTIFICATIONS
--    - Telegram CRITICAL pour leads hot
--    - Email récap avec BCC admin auto
--    - Configuration par site dans chatbot_sites.notification_*
-- 
-- 3. MULTI-TENANT
--    - Chaque site_id a sa config personnalisée
--    - System prompt + business_context + theme
--    - Secteurs : restaurant, mlm, ecommerce, salon_beaute, etc.
-- 
-- 4. PERFORMANCE
--    - Indexes composés optimisés pour requêtes fréquentes
--    - CASCADE DELETE sur chatbot_messages (nettoyage auto)
--    - JSON pour métadonnées flexibles
-- 
-- 5. ANALYTICS
--    - Events : conversation_start, message_sent, lead_captured, error
--    - Catégories : engagement, conversion, error, performance
--    - Dashboard temps réel via /api/chatbot/analytics/{site_id}
-- 
-- 6. RGPD
--    - Données minimales collectées
--    - Opt-out disponible
--    - Rétention 90 jours (à implémenter cron cleanup)
-- 
-- ============================================================
-- FIN MIGRATION 004
-- ============================================================

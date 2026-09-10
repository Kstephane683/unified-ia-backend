-- ============================================================================
-- Migration 004 : Système Chatbot Intelligent ePerformance
-- Phase 1-S1.4 : Module chatbot multi-tenant avec 29 agents IA
-- ============================================================================
-- 
-- Tables créées :
-- 1. chatbot_sites : Configuration multi-tenant (system_prompt, theme, welcome par site)
-- 2. chatbot_conversations : Sessions de conversation avec visiteurs
-- 3. chatbot_messages : Messages user/assistant avec intent et agent utilisé
-- 4. chatbot_leads : Leads capturés en conversation (→ Notifications)
-- 5. chatbot_analytics : Events tracking (conversation_start, lead_captured, etc.)
--
-- Intégrations :
-- - Système communication Phase 1-S1.3 (Email/WhatsApp/Telegram)
-- - 29 agents IA (Marketing, Sales, Design, Research, Product)
-- - Base MySQL existante (candidats, diagnostics, clients_web)
-- ============================================================================

-- ============================================================================
-- TABLE 1 : chatbot_sites
-- Configuration multi-tenant : chaque site_id a son propre chatbot personnalisé
-- ============================================================================
CREATE TABLE IF NOT EXISTS chatbot_sites (
    id INT AUTO_INCREMENT PRIMARY KEY,
    site_id VARCHAR(100) NOT NULL UNIQUE COMMENT 'Identifiant unique du site (ex: eperformance_vitrine, espace_client, boutique_client_123)',
    site_name VARCHAR(200) NOT NULL COMMENT 'Nom affiché du site',
    site_url VARCHAR(500) DEFAULT NULL COMMENT 'URL du site',
    
    -- Configuration chatbot
    system_prompt TEXT DEFAULT NULL COMMENT 'System prompt personnalisé (override le prompt par défaut)',
    welcome_message TEXT DEFAULT NULL COMMENT 'Message de bienvenue personnalisé',
    theme_config JSON DEFAULT NULL COMMENT 'Configuration thème (couleurs, logo, position)',
    
    -- Fonctionnalités activées
    features_enabled JSON DEFAULT NULL COMMENT '{"diagnostic": true, "order_capture": true, "support": true, "search": true}',
    allowed_intents JSON DEFAULT NULL COMMENT 'Liste des intents autorisés (null = tous)',
    
    -- Rate limiting
    rate_limit_messages_per_minute INT DEFAULT 20 COMMENT 'Limite messages par minute par visiteur',
    rate_limit_conversations_per_day INT DEFAULT 100 COMMENT 'Limite conversations par jour par IP',
    
    -- Notifications
    notification_telegram_enabled BOOLEAN DEFAULT TRUE COMMENT 'Activer notifications Telegram pour leads',
    notification_email_enabled BOOLEAN DEFAULT TRUE COMMENT 'Activer notifications Email pour leads',
    notification_recipients JSON DEFAULT NULL COMMENT 'Liste des destinataires pour ce site',
    
    -- Métadonnées
    is_active BOOLEAN DEFAULT TRUE COMMENT 'Site actif',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_site_id (site_id),
    INDEX idx_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Configuration multi-tenant des sites avec chatbot';

-- ============================================================================
-- TABLE 2 : chatbot_conversations
-- Sessions de conversation avec les visiteurs
-- ============================================================================
CREATE TABLE IF NOT EXISTS chatbot_conversations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    conversation_id VARCHAR(100) NOT NULL UNIQUE COMMENT 'UUID unique de la conversation',
    site_id VARCHAR(100) NOT NULL COMMENT 'Site où la conversation a lieu',
    
    -- Identification visiteur
    user_id INT DEFAULT NULL COMMENT 'ID candidat/client si connecté',
    visitor_name VARCHAR(200) DEFAULT NULL COMMENT 'Nom du visiteur (si fourni)',
    visitor_email VARCHAR(200) DEFAULT NULL COMMENT 'Email du visiteur (si fourni)',
    visitor_phone VARCHAR(50) DEFAULT NULL COMMENT 'Téléphone du visiteur (si fourni)',
    visitor_ip VARCHAR(100) DEFAULT NULL COMMENT 'IP du visiteur (rate limiting)',
    visitor_info JSON DEFAULT NULL COMMENT 'Infos navigateur, device, location',
    
    -- État conversation
    status ENUM('active', 'resolved', 'escalated', 'abandoned') DEFAULT 'active' COMMENT 'État de la conversation',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Début de la conversation',
    last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Dernier message',
    ended_at TIMESTAMP DEFAULT NULL COMMENT 'Fin de la conversation',
    
    -- Métriques
    message_count INT DEFAULT 0 COMMENT 'Nombre de messages dans la conversation',
    lead_captured BOOLEAN DEFAULT FALSE COMMENT 'Lead capturé pendant cette conversation',
    satisfaction_rating INT DEFAULT NULL COMMENT 'Note satisfaction (1-5) si demandée',
    
    -- Métadonnées
    metadata JSON DEFAULT NULL COMMENT 'Données additionnelles (utm_source, referrer, etc.)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_conversation_id (conversation_id),
    INDEX idx_site_id (site_id),
    INDEX idx_user_id (user_id),
    INDEX idx_visitor_ip (visitor_ip),
    INDEX idx_status (status),
    INDEX idx_started_at (started_at),
    INDEX idx_lead_captured (lead_captured),
    
    FOREIGN KEY (user_id) REFERENCES candidats(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Conversations chatbot avec visiteurs';

-- ============================================================================
-- TABLE 3 : chatbot_messages
-- Messages individuels dans les conversations (user + assistant)
-- ============================================================================
CREATE TABLE IF NOT EXISTS chatbot_messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    conversation_id VARCHAR(100) NOT NULL COMMENT 'ID de la conversation parent',
    
    -- Message
    role ENUM('user', 'assistant', 'system') NOT NULL COMMENT 'Émetteur du message',
    content TEXT NOT NULL COMMENT 'Contenu du message',
    
    -- Traitement IA (seulement pour messages user)
    intent VARCHAR(100) DEFAULT NULL COMMENT 'Intent détecté (diagnostic_request, order_intent, etc.)',
    intent_confidence DECIMAL(5,4) DEFAULT NULL COMMENT 'Confiance de détection (0.0000-1.0000)',
    agent_used VARCHAR(100) DEFAULT NULL COMMENT 'Agent IA utilisé pour générer la réponse',
    
    -- Actions exécutées
    actions_executed JSON DEFAULT NULL COMMENT 'Actions exécutées (lead_capture, diagnostic_create, etc.)',
    
    -- Contexte utilisé
    context_data JSON DEFAULT NULL COMMENT 'Contexte utilisé pour générer la réponse',
    
    -- Suggestions (quick replies)
    suggestions JSON DEFAULT NULL COMMENT 'Boutons de suggestion affichés',
    
    -- Métriques
    processing_time_ms INT DEFAULT NULL COMMENT 'Temps de traitement en millisecondes',
    llm_provider VARCHAR(50) DEFAULT NULL COMMENT 'Provider LLM utilisé (deepseek, claude)',
    llm_tokens_used INT DEFAULT NULL COMMENT 'Tokens utilisés pour cette réponse',
    
    -- Métadonnées
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_conversation_id (conversation_id),
    INDEX idx_role (role),
    INDEX idx_intent (intent),
    INDEX idx_agent_used (agent_used),
    INDEX idx_created_at (created_at),
    
    FOREIGN KEY (conversation_id) REFERENCES chatbot_conversations(conversation_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Messages chatbot (user et assistant)';

-- ============================================================================
-- TABLE 4 : chatbot_leads
-- Leads capturés pendant les conversations → Notifications équipe
-- ============================================================================
CREATE TABLE IF NOT EXISTS chatbot_leads (
    id INT AUTO_INCREMENT PRIMARY KEY,
    conversation_id VARCHAR(100) NOT NULL COMMENT 'Conversation source',
    site_id VARCHAR(100) NOT NULL COMMENT 'Site source',
    
    -- Informations lead
    name VARCHAR(200) NOT NULL COMMENT 'Nom du lead',
    email VARCHAR(200) DEFAULT NULL COMMENT 'Email du lead',
    phone VARCHAR(50) DEFAULT NULL COMMENT 'Téléphone du lead',
    company VARCHAR(200) DEFAULT NULL COMMENT 'Entreprise (si B2B)',
    
    -- Type de lead
    lead_type ENUM('hot', 'warm', 'cold', 'information') DEFAULT 'warm' COMMENT 'Température du lead',
    intent VARCHAR(100) DEFAULT NULL COMMENT 'Intent principal (order_intent, diagnostic_request, etc.)',
    
    -- Demande
    message TEXT DEFAULT NULL COMMENT 'Message/demande du lead',
    interested_products JSON DEFAULT NULL COMMENT 'Produits/services d\'intérêt',
    budget_range VARCHAR(100) DEFAULT NULL COMMENT 'Budget indicatif',
    urgency VARCHAR(50) DEFAULT NULL COMMENT 'Urgence (immédiat, 1-7j, 1-30j, >30j)',
    
    -- Traitement
    status ENUM('new', 'contacted', 'qualified', 'converted', 'lost') DEFAULT 'new' COMMENT 'État du traitement',
    assigned_to VARCHAR(200) DEFAULT NULL COMMENT 'Assigné à (email commercial)',
    
    -- Notifications envoyées
    notification_sent BOOLEAN DEFAULT FALSE COMMENT 'Notification envoyée à l\'équipe',
    notification_ids JSON DEFAULT NULL COMMENT 'IDs des notifications envoyées (Telegram, Email)',
    
    -- Suivi
    first_contact_at TIMESTAMP DEFAULT NULL COMMENT 'Premier contact par l\'équipe',
    converted_at TIMESTAMP DEFAULT NULL COMMENT 'Date de conversion',
    conversion_value DECIMAL(10,2) DEFAULT NULL COMMENT 'Valeur de conversion (€)',
    
    -- Métadonnées
    source_url VARCHAR(500) DEFAULT NULL COMMENT 'URL de la page source',
    utm_data JSON DEFAULT NULL COMMENT 'Données UTM si disponibles',
    metadata JSON DEFAULT NULL COMMENT 'Autres données',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_conversation_id (conversation_id),
    INDEX idx_site_id (site_id),
    INDEX idx_lead_type (lead_type),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at),
    INDEX idx_email (email),
    INDEX idx_phone (phone),
    
    FOREIGN KEY (conversation_id) REFERENCES chatbot_conversations(conversation_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Leads capturés par le chatbot';

-- ============================================================================
-- TABLE 5 : chatbot_analytics
-- Events tracking pour analytics et optimisation
-- ============================================================================
CREATE TABLE IF NOT EXISTS chatbot_analytics (
    id INT AUTO_INCREMENT PRIMARY KEY,
    site_id VARCHAR(100) NOT NULL COMMENT 'Site source',
    conversation_id VARCHAR(100) DEFAULT NULL COMMENT 'Conversation associée (si applicable)',
    
    -- Event
    event_type VARCHAR(100) NOT NULL COMMENT 'Type d\'event (conversation_start, message_sent, lead_captured, etc.)',
    event_category VARCHAR(50) DEFAULT NULL COMMENT 'Catégorie (engagement, conversion, error, performance)',
    
    -- Données event
    event_data JSON DEFAULT NULL COMMENT 'Données spécifiques à l\'event',
    
    -- Contexte
    visitor_ip VARCHAR(100) DEFAULT NULL COMMENT 'IP du visiteur',
    user_agent TEXT DEFAULT NULL COMMENT 'User agent',
    referrer VARCHAR(500) DEFAULT NULL COMMENT 'Referrer',
    
    -- Timing
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Moment de l\'event',
    
    INDEX idx_site_id (site_id),
    INDEX idx_conversation_id (conversation_id),
    INDEX idx_event_type (event_type),
    INDEX idx_event_category (event_category),
    INDEX idx_timestamp (timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Analytics et tracking des events chatbot';

-- ============================================================================
-- DONNÉES INITIALES : Sites par défaut
-- ============================================================================
INSERT INTO chatbot_sites (site_id, site_name, site_url, system_prompt, welcome_message, features_enabled, theme_config, is_active) VALUES
(
    'eperformance_vitrine',
    'ePerformance',
    'https://eperformance.pro',
    'Tu es l\'assistant IA d\'ePerformance, expert en marketing digital, publicité Meta Ads, stratégies MLM et IA pour entrepreneurs. Tu aides les visiteurs à comprendre nos services, faire un diagnostic de leur business, et les guider vers les meilleures solutions. Tu es professionnel, empathique et orienté résultats. Tu poses des questions pertinentes pour bien comprendre leur situation avant de recommander.',
    'Bonjour ! 👋 Je suis l\'assistant IA d\'ePerformance. Je peux vous aider à :\n\n• Faire un diagnostic gratuit de votre business\n• Découvrir nos formations et services\n• Optimiser vos publicités Meta Ads\n• Mettre en place des stratégies IA\n\nComment puis-je vous aider aujourd\'hui ?',
    '{"diagnostic": true, "order_capture": true, "support": true, "search": true, "recommendations": true}',
    '{"primary_color": "#c9a96e", "position": "bottom-right", "show_badge": true, "animation": "slide"}',
    TRUE
),
(
    'espace_client',
    'Espace Client ePerformance',
    'https://api.eperformance.pro/connexion.php',
    'Tu es l\'assistant IA de l\'espace client ePerformance. Tu aides les clients existants avec leurs questions sur leurs formations, diagnostics, campagnes publicitaires et abonnements. Tu as accès à leur historique et peux les guider dans l\'utilisation de nos outils. Tu es toujours courtois et orienté service client.',
    'Bienvenue dans votre espace client ! 🎯\n\nJe peux vous aider avec :\n\n• Vos formations en cours\n• Vos diagnostics et rapports\n• Vos campagnes publicitaires\n• Vos questions techniques\n\nQue puis-je faire pour vous ?',
    '{"diagnostic": true, "order_capture": false, "support": true, "search": true, "recommendations": true, "account_info": true}',
    '{"primary_color": "#c9a96e", "position": "bottom-right", "show_badge": true, "animation": "slide"}',
    TRUE
);

-- ============================================================================
-- TEMPLATE NOTIFICATION : chatbot_lead_hot
-- Pour l'intégration avec le système de communication Phase 1-S1.3
-- ============================================================================
INSERT INTO notification_templates (
    channel_id,
    template_name,
    subject,
    body,
    variables,
    is_active
) VALUES
(
    (SELECT id FROM notification_channels WHERE channel_type = 'telegram' LIMIT 1),
    'chatbot_lead_hot',
    '🔥 Nouveau Lead Chaud - Chatbot',
    '🔥 <b>LEAD CHAUD CAPTURÉ</b>\n\n👤 <b>Contact</b>\nNom: {{lead_name}}\nTéléphone: {{lead_phone}}\nEmail: {{lead_email}}\n\n💬 <b>Intent</b>: {{intent}}\n\n📝 <b>Message</b>:\n{{lead_message}}\n\n🌐 <b>Site</b>: {{site_name}}\n⏰ <b>Capturé</b>: {{captured_at}}\n\n🔗 <a href="{{conversation_url}}">Voir la conversation</a>',
    '["lead_name", "lead_phone", "lead_email", "intent", "lead_message", "site_name", "captured_at", "conversation_url"]',
    TRUE
),
(
    (SELECT id FROM notification_channels WHERE channel_type = 'email' LIMIT 1),
    'chatbot_lead_hot',
    '🔥 Nouveau Lead Chaud - {{lead_name}} via Chatbot {{site_name}}',
    '<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: linear-gradient(135deg, #c9a96e 0%, #b8935a 100%); color: white; padding: 30px; text-align: center; border-radius: 8px 8px 0 0; }
        .content { background: #ffffff; padding: 30px; border: 1px solid #e5e5e5; }
        .label { font-weight: 600; color: #666; margin-top: 15px; }
        .value { color: #333; margin-bottom: 10px; }
        .cta { background: #c9a96e; color: white; padding: 12px 30px; text-decoration: none; border-radius: 6px; display: inline-block; margin-top: 20px; }
        .footer { text-align: center; padding: 20px; color: #999; font-size: 12px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0;">🔥 Nouveau Lead Chaud</h1>
        </div>
        <div class="content">
            <p><strong>Un lead chaud vient d\'être capturé via le chatbot !</strong></p>
            
            <div class="label">👤 Contact</div>
            <div class="value">
                <strong>{{lead_name}}</strong><br>
                📞 {{lead_phone}}<br>
                📧 {{lead_email}}
            </div>
            
            <div class="label">💬 Intent</div>
            <div class="value">{{intent}}</div>
            
            <div class="label">📝 Message</div>
            <div class="value">{{lead_message}}</div>
            
            <div class="label">🌐 Site source</div>
            <div class="value">{{site_name}}</div>
            
            <div class="label">⏰ Capturé le</div>
            <div class="value">{{captured_at}}</div>
            
            <a href="{{conversation_url}}" class="cta">Voir la conversation complète</a>
        </div>
        <div class="footer">
            ePerformance - Système de communication automatisé
        </div>
    </div>
</body>
</html>',
    '["lead_name", "lead_phone", "lead_email", "intent", "lead_message", "site_name", "captured_at", "conversation_url"]',
    TRUE
);

-- ============================================================================
-- FIN DE LA MIGRATION
-- ============================================================================

-- ============================================================================
-- Migration 004 : Système Chatbot Intelligent ePerformance
-- Phase 1-S1.4 : Module chatbot multi-tenant avec 29 agents IA
-- PostgreSQL version
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
-- - Base existante (candidats, diagnostics, clients_web)
-- ============================================================================

-- ============================================================================
-- ENUM TYPES
-- ============================================================================

DO $$ BEGIN
    CREATE TYPE conversation_status AS ENUM ('active', 'resolved', 'escalated', 'abandoned');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE message_role AS ENUM ('user', 'assistant', 'system');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE lead_type AS ENUM ('hot', 'warm', 'cold', 'information');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE lead_status AS ENUM ('new', 'contacted', 'qualified', 'converted', 'lost');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- ============================================================================
-- TABLE 1 : chatbot_sites
-- Configuration multi-tenant : chaque site_id a son propre chatbot personnalisé
-- ============================================================================

CREATE TABLE IF NOT EXISTS chatbot_sites (
    id SERIAL PRIMARY KEY,
    site_id VARCHAR(100) NOT NULL UNIQUE,
    site_name VARCHAR(200) NOT NULL,
    site_url VARCHAR(500) DEFAULT NULL,
    
    -- Configuration chatbot
    system_prompt TEXT DEFAULT NULL,
    welcome_message TEXT DEFAULT NULL,
    theme_config JSONB DEFAULT NULL,
    
    -- Fonctionnalités activées
    features_enabled JSONB DEFAULT NULL,
    allowed_intents JSONB DEFAULT NULL,
    
    -- Rate limiting
    rate_limit_messages_per_minute INT DEFAULT 20,
    rate_limit_conversations_per_day INT DEFAULT 100,
    
    -- Notifications
    notification_telegram_enabled BOOLEAN DEFAULT TRUE,
    notification_email_enabled BOOLEAN DEFAULT TRUE,
    notification_recipients JSONB DEFAULT NULL,
    
    -- Métadonnées
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for chatbot_sites
CREATE INDEX IF NOT EXISTS idx_chatbot_sites_site_id ON chatbot_sites(site_id);
CREATE INDEX IF NOT EXISTS idx_chatbot_sites_active ON chatbot_sites(is_active);

-- Comments for chatbot_sites
COMMENT ON TABLE chatbot_sites IS 'Configuration multi-tenant des sites avec chatbot';
COMMENT ON COLUMN chatbot_sites.site_id IS 'Identifiant unique du site (ex: eperformance_vitrine, espace_client, boutique_client_123)';
COMMENT ON COLUMN chatbot_sites.site_name IS 'Nom affiché du site';
COMMENT ON COLUMN chatbot_sites.site_url IS 'URL du site';
COMMENT ON COLUMN chatbot_sites.system_prompt IS 'System prompt personnalisé (override le prompt par défaut)';
COMMENT ON COLUMN chatbot_sites.welcome_message IS 'Message de bienvenue personnalisé';
COMMENT ON COLUMN chatbot_sites.theme_config IS 'Configuration thème (couleurs, logo, position)';
COMMENT ON COLUMN chatbot_sites.features_enabled IS '{"diagnostic": true, "order_capture": true, "support": true, "search": true}';
COMMENT ON COLUMN chatbot_sites.allowed_intents IS 'Liste des intents autorisés (null = tous)';
COMMENT ON COLUMN chatbot_sites.rate_limit_messages_per_minute IS 'Limite messages par minute par visiteur';
COMMENT ON COLUMN chatbot_sites.rate_limit_conversations_per_day IS 'Limite conversations par jour par IP';
COMMENT ON COLUMN chatbot_sites.notification_telegram_enabled IS 'Activer notifications Telegram pour leads';
COMMENT ON COLUMN chatbot_sites.notification_email_enabled IS 'Activer notifications Email pour leads';
COMMENT ON COLUMN chatbot_sites.notification_recipients IS 'Liste des destinataires pour ce site';
COMMENT ON COLUMN chatbot_sites.is_active IS 'Site actif';

-- ============================================================================
-- TABLE 2 : chatbot_conversations
-- Sessions de conversation avec les visiteurs
-- ============================================================================

CREATE TABLE IF NOT EXISTS chatbot_conversations (
    id SERIAL PRIMARY KEY,
    conversation_id VARCHAR(100) NOT NULL UNIQUE,
    site_id VARCHAR(100) NOT NULL,
    
    -- Identification visiteur
    user_id INT DEFAULT NULL,
    visitor_name VARCHAR(200) DEFAULT NULL,
    visitor_email VARCHAR(200) DEFAULT NULL,
    visitor_phone VARCHAR(50) DEFAULT NULL,
    visitor_ip VARCHAR(100) DEFAULT NULL,
    visitor_info JSONB DEFAULT NULL,
    
    -- État conversation
    status conversation_status DEFAULT 'active',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP DEFAULT NULL,
    
    -- Métriques
    message_count INT DEFAULT 0,
    lead_captured BOOLEAN DEFAULT FALSE,
    satisfaction_rating INT DEFAULT NULL,
    
    -- Métadonnées
    metadata JSONB DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for chatbot_conversations
CREATE INDEX IF NOT EXISTS idx_chatbot_conversations_conversation_id ON chatbot_conversations(conversation_id);
CREATE INDEX IF NOT EXISTS idx_chatbot_conversations_site_id ON chatbot_conversations(site_id);
CREATE INDEX IF NOT EXISTS idx_chatbot_conversations_user_id ON chatbot_conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_chatbot_conversations_visitor_ip ON chatbot_conversations(visitor_ip);
CREATE INDEX IF NOT EXISTS idx_chatbot_conversations_status ON chatbot_conversations(status);
CREATE INDEX IF NOT EXISTS idx_chatbot_conversations_started_at ON chatbot_conversations(started_at);
CREATE INDEX IF NOT EXISTS idx_chatbot_conversations_lead_captured ON chatbot_conversations(lead_captured);

-- Comments for chatbot_conversations
COMMENT ON TABLE chatbot_conversations IS 'Conversations chatbot avec visiteurs';
COMMENT ON COLUMN chatbot_conversations.conversation_id IS 'UUID unique de la conversation';
COMMENT ON COLUMN chatbot_conversations.site_id IS 'Site où la conversation a lieu';
COMMENT ON COLUMN chatbot_conversations.user_id IS 'ID candidat/client si connecté';
COMMENT ON COLUMN chatbot_conversations.visitor_name IS 'Nom du visiteur (si fourni)';
COMMENT ON COLUMN chatbot_conversations.visitor_email IS 'Email du visiteur (si fourni)';
COMMENT ON COLUMN chatbot_conversations.visitor_phone IS 'Téléphone du visiteur (si fourni)';
COMMENT ON COLUMN chatbot_conversations.visitor_ip IS 'IP du visiteur (rate limiting)';
COMMENT ON COLUMN chatbot_conversations.visitor_info IS 'Infos navigateur, device, location';
COMMENT ON COLUMN chatbot_conversations.status IS 'État de la conversation';
COMMENT ON COLUMN chatbot_conversations.started_at IS 'Début de la conversation';
COMMENT ON COLUMN chatbot_conversations.last_message_at IS 'Dernier message';
COMMENT ON COLUMN chatbot_conversations.ended_at IS 'Fin de la conversation';
COMMENT ON COLUMN chatbot_conversations.message_count IS 'Nombre de messages dans la conversation';
COMMENT ON COLUMN chatbot_conversations.lead_captured IS 'Lead capturé pendant cette conversation';
COMMENT ON COLUMN chatbot_conversations.satisfaction_rating IS 'Note satisfaction (1-5) si demandée';
COMMENT ON COLUMN chatbot_conversations.metadata IS 'Données additionnelles (utm_source, referrer, etc.)';

-- Foreign key for chatbot_conversations (uncomment when candidats table exists)
-- ALTER TABLE chatbot_conversations 
-- ADD CONSTRAINT fk_chatbot_conversations_user 
-- FOREIGN KEY (user_id) REFERENCES candidats(id) ON DELETE SET NULL;

-- ============================================================================
-- TABLE 3 : chatbot_messages
-- Messages individuels dans les conversations (user + assistant)
-- ============================================================================

CREATE TABLE IF NOT EXISTS chatbot_messages (
    id SERIAL PRIMARY KEY,
    conversation_id VARCHAR(100) NOT NULL,
    
    -- Message
    role message_role NOT NULL,
    content TEXT NOT NULL,
    
    -- Traitement IA (seulement pour messages user)
    intent VARCHAR(100) DEFAULT NULL,
    intent_confidence DECIMAL(5,4) DEFAULT NULL,
    agent_used VARCHAR(100) DEFAULT NULL,
    
    -- Actions exécutées
    actions_executed JSONB DEFAULT NULL,
    
    -- Contexte utilisé
    context_data JSONB DEFAULT NULL,
    
    -- Suggestions (quick replies)
    suggestions JSONB DEFAULT NULL,
    
    -- Métriques
    processing_time_ms INT DEFAULT NULL,
    llm_provider VARCHAR(50) DEFAULT NULL,
    llm_tokens_used INT DEFAULT NULL,
    
    -- Métadonnées
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for chatbot_messages
CREATE INDEX IF NOT EXISTS idx_chatbot_messages_conversation_id ON chatbot_messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_chatbot_messages_role ON chatbot_messages(role);
CREATE INDEX IF NOT EXISTS idx_chatbot_messages_intent ON chatbot_messages(intent);
CREATE INDEX IF NOT EXISTS idx_chatbot_messages_agent_used ON chatbot_messages(agent_used);
CREATE INDEX IF NOT EXISTS idx_chatbot_messages_created_at ON chatbot_messages(created_at);

-- Comments for chatbot_messages
COMMENT ON TABLE chatbot_messages IS 'Messages chatbot (user et assistant)';
COMMENT ON COLUMN chatbot_messages.conversation_id IS 'ID de la conversation parent';
COMMENT ON COLUMN chatbot_messages.role IS 'Émetteur du message';
COMMENT ON COLUMN chatbot_messages.content IS 'Contenu du message';
COMMENT ON COLUMN chatbot_messages.intent IS 'Intent détecté (diagnostic_request, order_intent, etc.)';
COMMENT ON COLUMN chatbot_messages.intent_confidence IS 'Confiance de détection (0.0000-1.0000)';
COMMENT ON COLUMN chatbot_messages.agent_used IS 'Agent IA utilisé pour générer la réponse';
COMMENT ON COLUMN chatbot_messages.actions_executed IS 'Actions exécutées (lead_capture, diagnostic_create, etc.)';
COMMENT ON COLUMN chatbot_messages.context_data IS 'Contexte utilisé pour générer la réponse';
COMMENT ON COLUMN chatbot_messages.suggestions IS 'Boutons de suggestion affichés';
COMMENT ON COLUMN chatbot_messages.processing_time_ms IS 'Temps de traitement en millisecondes';
COMMENT ON COLUMN chatbot_messages.llm_provider IS 'Provider LLM utilisé (deepseek, claude)';
COMMENT ON COLUMN chatbot_messages.llm_tokens_used IS 'Tokens utilisés pour cette réponse';

-- Foreign key for chatbot_messages
ALTER TABLE chatbot_messages 
ADD CONSTRAINT fk_chatbot_messages_conversation 
FOREIGN KEY (conversation_id) REFERENCES chatbot_conversations(conversation_id) ON DELETE CASCADE;

-- ============================================================================
-- TABLE 4 : chatbot_leads
-- Leads capturés pendant les conversations → Notifications équipe
-- ============================================================================

CREATE TABLE IF NOT EXISTS chatbot_leads (
    id SERIAL PRIMARY KEY,
    conversation_id VARCHAR(100) NOT NULL,
    site_id VARCHAR(100) NOT NULL,
    
    -- Informations lead
    name VARCHAR(200) NOT NULL,
    email VARCHAR(200) DEFAULT NULL,
    phone VARCHAR(50) DEFAULT NULL,
    company VARCHAR(200) DEFAULT NULL,
    
    -- Type de lead
    lead_type lead_type DEFAULT 'warm',
    intent VARCHAR(100) DEFAULT NULL,
    
    -- Demande
    message TEXT DEFAULT NULL,
    interested_products JSONB DEFAULT NULL,
    budget_range VARCHAR(100) DEFAULT NULL,
    urgency VARCHAR(50) DEFAULT NULL,
    
    -- Traitement
    status lead_status DEFAULT 'new',
    assigned_to VARCHAR(200) DEFAULT NULL,
    
    -- Notifications envoyées
    notification_sent BOOLEAN DEFAULT FALSE,
    notification_ids JSONB DEFAULT NULL,
    
    -- Suivi
    first_contact_at TIMESTAMP DEFAULT NULL,
    converted_at TIMESTAMP DEFAULT NULL,
    conversion_value DECIMAL(10,2) DEFAULT NULL,
    
    -- Métadonnées
    source_url VARCHAR(500) DEFAULT NULL,
    utm_data JSONB DEFAULT NULL,
    metadata JSONB DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for chatbot_leads
CREATE INDEX IF NOT EXISTS idx_chatbot_leads_conversation_id ON chatbot_leads(conversation_id);
CREATE INDEX IF NOT EXISTS idx_chatbot_leads_site_id ON chatbot_leads(site_id);
CREATE INDEX IF NOT EXISTS idx_chatbot_leads_lead_type ON chatbot_leads(lead_type);
CREATE INDEX IF NOT EXISTS idx_chatbot_leads_status ON chatbot_leads(status);
CREATE INDEX IF NOT EXISTS idx_chatbot_leads_created_at ON chatbot_leads(created_at);
CREATE INDEX IF NOT EXISTS idx_chatbot_leads_email ON chatbot_leads(email);
CREATE INDEX IF NOT EXISTS idx_chatbot_leads_phone ON chatbot_leads(phone);

-- Comments for chatbot_leads
COMMENT ON TABLE chatbot_leads IS 'Leads capturés par le chatbot';
COMMENT ON COLUMN chatbot_leads.conversation_id IS 'Conversation source';
COMMENT ON COLUMN chatbot_leads.site_id IS 'Site source';
COMMENT ON COLUMN chatbot_leads.name IS 'Nom du lead';
COMMENT ON COLUMN chatbot_leads.email IS 'Email du lead';
COMMENT ON COLUMN chatbot_leads.phone IS 'Téléphone du lead';
COMMENT ON COLUMN chatbot_leads.company IS 'Entreprise (si B2B)';
COMMENT ON COLUMN chatbot_leads.lead_type IS 'Température du lead';
COMMENT ON COLUMN chatbot_leads.intent IS 'Intent principal (order_intent, diagnostic_request, etc.)';
COMMENT ON COLUMN chatbot_leads.message IS 'Message/demande du lead';
COMMENT ON COLUMN chatbot_leads.interested_products IS 'Produits/services d''intérêt';
COMMENT ON COLUMN chatbot_leads.budget_range IS 'Budget indicatif';
COMMENT ON COLUMN chatbot_leads.urgency IS 'Urgence (immédiat, 1-7j, 1-30j, >30j)';
COMMENT ON COLUMN chatbot_leads.status IS 'État du traitement';
COMMENT ON COLUMN chatbot_leads.assigned_to IS 'Assigné à (email commercial)';
COMMENT ON COLUMN chatbot_leads.notification_sent IS 'Notification envoyée à l''équipe';
COMMENT ON COLUMN chatbot_leads.notification_ids IS 'IDs des notifications envoyées (Telegram, Email)';
COMMENT ON COLUMN chatbot_leads.first_contact_at IS 'Premier contact par l''équipe';
COMMENT ON COLUMN chatbot_leads.converted_at IS 'Date de conversion';
COMMENT ON COLUMN chatbot_leads.conversion_value IS 'Valeur de conversion (€)';
COMMENT ON COLUMN chatbot_leads.source_url IS 'URL de la page source';
COMMENT ON COLUMN chatbot_leads.utm_data IS 'Données UTM si disponibles';
COMMENT ON COLUMN chatbot_leads.metadata IS 'Autres données';

-- Foreign key for chatbot_leads
ALTER TABLE chatbot_leads 
ADD CONSTRAINT fk_chatbot_leads_conversation 
FOREIGN KEY (conversation_id) REFERENCES chatbot_conversations(conversation_id) ON DELETE CASCADE;

-- ============================================================================
-- TABLE 5 : chatbot_analytics
-- Events tracking pour analytics et optimisation
-- ============================================================================

CREATE TABLE IF NOT EXISTS chatbot_analytics (
    id SERIAL PRIMARY KEY,
    site_id VARCHAR(100) NOT NULL,
    conversation_id VARCHAR(100) DEFAULT NULL,
    
    -- Event
    event_type VARCHAR(100) NOT NULL,
    event_category VARCHAR(50) DEFAULT NULL,
    
    -- Données event
    event_data JSONB DEFAULT NULL,
    
    -- Contexte
    visitor_ip VARCHAR(100) DEFAULT NULL,
    user_agent TEXT DEFAULT NULL,
    referrer VARCHAR(500) DEFAULT NULL,
    
    -- Timing
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for chatbot_analytics
CREATE INDEX IF NOT EXISTS idx_chatbot_analytics_site_id ON chatbot_analytics(site_id);
CREATE INDEX IF NOT EXISTS idx_chatbot_analytics_conversation_id ON chatbot_analytics(conversation_id);
CREATE INDEX IF NOT EXISTS idx_chatbot_analytics_event_type ON chatbot_analytics(event_type);
CREATE INDEX IF NOT EXISTS idx_chatbot_analytics_event_category ON chatbot_analytics(event_category);
CREATE INDEX IF NOT EXISTS idx_chatbot_analytics_timestamp ON chatbot_analytics(timestamp);

-- Comments for chatbot_analytics
COMMENT ON TABLE chatbot_analytics IS 'Analytics et tracking des events chatbot';
COMMENT ON COLUMN chatbot_analytics.site_id IS 'Site source';
COMMENT ON COLUMN chatbot_analytics.conversation_id IS 'Conversation associée (si applicable)';
COMMENT ON COLUMN chatbot_analytics.event_type IS 'Type d''event (conversation_start, message_sent, lead_captured, etc.)';
COMMENT ON COLUMN chatbot_analytics.event_category IS 'Catégorie (engagement, conversion, error, performance)';
COMMENT ON COLUMN chatbot_analytics.event_data IS 'Données spécifiques à l''event';
COMMENT ON COLUMN chatbot_analytics.visitor_ip IS 'IP du visiteur';
COMMENT ON COLUMN chatbot_analytics.user_agent IS 'User agent';
COMMENT ON COLUMN chatbot_analytics.referrer IS 'Referrer';
COMMENT ON COLUMN chatbot_analytics.timestamp IS 'Moment de l''event';

-- ============================================================================
-- TRIGGER FUNCTIONS for updated_at timestamps
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply triggers to tables with updated_at
CREATE TRIGGER update_chatbot_sites_updated_at BEFORE UPDATE ON chatbot_sites
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_chatbot_conversations_updated_at BEFORE UPDATE ON chatbot_conversations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_chatbot_leads_updated_at BEFORE UPDATE ON chatbot_leads
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- DONNÉES INITIALES : Sites par défaut
-- ============================================================================

INSERT INTO chatbot_sites (site_id, site_name, site_url, system_prompt, welcome_message, features_enabled, theme_config, is_active) VALUES
(
    'eperformance_vitrine',
    'ePerformance',
    'https://eperformance.pro',
    'Tu es l''assistant IA d''ePerformance, expert en marketing digital, publicité Meta Ads, stratégies MLM et IA pour entrepreneurs. Tu aides les visiteurs à comprendre nos services, faire un diagnostic de leur business, et les guider vers les meilleures solutions. Tu es professionnel, empathique et orienté résultats. Tu poses des questions pertinentes pour bien comprendre leur situation avant de recommander.',
    'Bonjour ! 👋 Je suis l''assistant IA d''ePerformance. Je peux vous aider à :

• Faire un diagnostic gratuit de votre business
• Découvrir nos formations et services
• Optimiser vos publicités Meta Ads
• Mettre en place des stratégies IA

Comment puis-je vous aider aujourd''hui ?',
    '{"diagnostic": true, "order_capture": true, "support": true, "search": true, "recommendations": true}'::jsonb,
    '{"primary_color": "#c9a96e", "position": "bottom-right", "show_badge": true, "animation": "slide"}'::jsonb,
    TRUE
),
(
    'espace_client',
    'Espace Client ePerformance',
    'https://api.eperformance.pro/connexion.php',
    'Tu es l''assistant IA de l''espace client ePerformance. Tu aides les clients existants avec leurs questions sur leurs formations, diagnostics, campagnes publicitaires et abonnements. Tu as accès à leur historique et peux les guider dans l''utilisation de nos outils. Tu es toujours courtois et orienté service client.',
    'Bienvenue dans votre espace client ! 🎯

Je peux vous aider avec :

• Vos formations en cours
• Vos diagnostics et rapports
• Vos campagnes publicitaires
• Vos questions techniques

Que puis-je faire pour vous ?',
    '{"diagnostic": true, "order_capture": false, "support": true, "search": true, "recommendations": true, "account_info": true}'::jsonb,
    '{"primary_color": "#c9a96e", "position": "bottom-right", "show_badge": true, "animation": "slide"}'::jsonb,
    TRUE
)
ON CONFLICT (site_id) DO NOTHING;

-- ============================================================================
-- TEMPLATE NOTIFICATION : chatbot_lead_hot
-- Pour l'intégration avec le système de communication Phase 1-S1.3
-- ============================================================================

INSERT INTO notification_templates (
    code,
    name,
    category,
    telegram_message,
    telegram_parse_mode,
    required_vars,
    is_active
) VALUES
(
    'chatbot_lead_hot_telegram',
    'Chatbot Lead Hot - Telegram',
    'transactional',
    '🔥 <b>LEAD CHAUD CAPTURÉ</b>

👤 <b>Contact</b>
Nom: {{lead_name}}
Téléphone: {{lead_phone}}
Email: {{lead_email}}

💬 <b>Intent</b>: {{intent}}

📝 <b>Message</b>:
{{lead_message}}

🌐 <b>Site</b>: {{site_name}}
⏰ <b>Capturé</b>: {{captured_at}}

🔗 <a href="{{conversation_url}}">Voir la conversation</a>',
    'HTML',
    '["lead_name", "lead_phone", "lead_email", "intent", "lead_message", "site_name", "captured_at", "conversation_url"]'::jsonb,
    TRUE
)
ON CONFLICT (code) DO NOTHING;

INSERT INTO notification_templates (
    code,
    name,
    category,
    email_subject,
    email_html,
    required_vars,
    is_active
) VALUES
(
    'chatbot_lead_hot_email',
    'Chatbot Lead Hot - Email',
    'transactional',
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
            <p><strong>Un lead chaud vient d''être capturé via le chatbot !</strong></p>
            
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
    '["lead_name", "lead_phone", "lead_email", "intent", "lead_message", "site_name", "captured_at", "conversation_url"]'::jsonb,
    TRUE
)
ON CONFLICT (code) DO NOTHING;

-- ============================================================================
-- FIN DE LA MIGRATION
-- ============================================================================

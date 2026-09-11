-- ============================================================
-- SQL Migration: Create SaaS tables for ePerformance unified system.
-- PostgreSQL version
-- Run: psql -U unified_dev -d unified_ia_dev -f migrations/postgresql/001_create_saas_tables.sql
-- ============================================================

-- ============================================================
-- ENUM TYPES
-- ============================================================

DO $$ BEGIN
    CREATE TYPE subscription_type AS ENUM ('accompagnement', 'module_standalone');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE subscription_niveau AS ENUM ('essentielle', 'croissance', 'acceleration');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE subscription_statut AS ENUM ('active', 'paused', 'cancelled', 'expired');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE product_type AS ENUM ('site_web', 'module', 'formation', 'service');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE billing_type AS ENUM ('one_time', 'monthly', 'yearly');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE user_product_statut AS ENUM ('active', 'expired', 'cancelled');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE invoice_statut AS ENUM ('draft', 'pending', 'paid', 'failed', 'refunded');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- ============================================================
-- TABLE: subscriptions (Abonnements récurrents)
-- ============================================================

CREATE TABLE IF NOT EXISTS subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL,
    candidat_id INT NULL,
    
    -- Type abonnement
    type subscription_type NOT NULL,
    niveau subscription_niveau NULL,
    
    -- Pricing
    montant_mensuel DECIMAL(10,2) NOT NULL,
    devise VARCHAR(3) DEFAULT 'XOF',
    
    -- Durée
    engagement_mois INT NOT NULL,
    date_debut DATE NOT NULL,
    date_fin DATE NOT NULL,
    
    -- Statut
    statut subscription_statut DEFAULT 'active',
    auto_renew BOOLEAN DEFAULT FALSE,
    
    -- Facturation
    facturation_jour INT DEFAULT 1,
    prochaine_facturation DATE,
    derniere_facturation DATE,
    
    -- Métadonnées
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    cancelled_at TIMESTAMP NULL,
    cancellation_reason TEXT NULL
);

-- Indexes for subscriptions
CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_candidat_id ON subscriptions(candidat_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_user_statut ON subscriptions(user_id, statut);
CREATE INDEX IF NOT EXISTS idx_subscriptions_prochaine_facturation ON subscriptions(prochaine_facturation, statut);

-- Comments for subscriptions
COMMENT ON TABLE subscriptions IS 'Abonnements récurrents (accompagnement ou modules standalone)';
COMMENT ON COLUMN subscriptions.candidat_id IS 'Si vient du chemin diagnostic';
COMMENT ON COLUMN subscriptions.niveau IS 'Pour accompagnement';
COMMENT ON COLUMN subscriptions.engagement_mois IS '3, 6, 12 mois';
COMMENT ON COLUMN subscriptions.facturation_jour IS 'Jour du mois pour facturation';

-- ============================================================
-- TABLE: products (Catalogue produits)
-- ============================================================

CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    
    -- Identification
    slug VARCHAR(100) UNIQUE NOT NULL,
    nom VARCHAR(255) NOT NULL,
    description TEXT,
    
    -- Type produit
    type product_type NOT NULL,
    category VARCHAR(50),
    
    -- Pricing
    prix_unitaire DECIMAL(10,2) NOT NULL,
    devise VARCHAR(3) DEFAULT 'XOF',
    billing_type billing_type NOT NULL,
    
    -- Features
    features_json TEXT,
    quota_mensuel JSONB NULL,
    
    -- Visibilité
    is_active BOOLEAN DEFAULT TRUE,
    is_visible BOOLEAN DEFAULT TRUE,
    requires_approval BOOLEAN DEFAULT FALSE,
    
    -- Métadonnées
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for products
CREATE INDEX IF NOT EXISTS idx_products_slug ON products(slug);
CREATE INDEX IF NOT EXISTS idx_products_type_active ON products(type, is_active);

-- Comments for products
COMMENT ON TABLE products IS 'Catalogue des produits et modules disponibles';
COMMENT ON COLUMN products.category IS 'ia, marketing, seo, video';
COMMENT ON COLUMN products.features_json IS 'JSON: ["chatbot_ia", "posts_generation:20"]';
COMMENT ON COLUMN products.quota_mensuel IS '{"posts": 20, "articles_seo": 5}';
COMMENT ON COLUMN products.is_visible IS 'Visible sur catalogue public';
COMMENT ON COLUMN products.requires_approval IS 'Nécessite validation manuelle';

-- ============================================================
-- TABLE: user_products (Produits achetés par user)
-- ============================================================

CREATE TABLE IF NOT EXISTS user_products (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL,
    product_id INT NOT NULL,
    subscription_id INT NULL,
    
    -- Statut
    statut user_product_statut DEFAULT 'active',
    
    -- Dates
    date_achat DATE NOT NULL,
    date_activation DATE,
    date_expiration DATE NULL,
    
    -- Usage tracking
    usage_current JSONB NULL,
    usage_limit JSONB NULL,
    
    -- Métadonnées
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for user_products
CREATE INDEX IF NOT EXISTS idx_user_products_user_id ON user_products(user_id);
CREATE INDEX IF NOT EXISTS idx_user_products_product_id ON user_products(product_id);
CREATE INDEX IF NOT EXISTS idx_user_products_subscription_id ON user_products(subscription_id);
CREATE INDEX IF NOT EXISTS idx_user_products_user_statut ON user_products(user_id, statut);
CREATE INDEX IF NOT EXISTS idx_user_products_product ON user_products(product_id);

-- Comments for user_products
COMMENT ON TABLE user_products IS 'Produits achetés/activés par utilisateur';
COMMENT ON COLUMN user_products.subscription_id IS 'Si lié à un abonnement';
COMMENT ON COLUMN user_products.date_expiration IS 'Pour produits one-time avec durée';
COMMENT ON COLUMN user_products.usage_current IS '{"posts_generated": 15}';
COMMENT ON COLUMN user_products.usage_limit IS '{"posts_generated": 20}';

-- ============================================================
-- TABLE: features (Features disponibles dans le système)
-- ============================================================

CREATE TABLE IF NOT EXISTS features (
    id SERIAL PRIMARY KEY,
    
    -- Identification
    slug VARCHAR(100) UNIQUE NOT NULL,
    nom VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(50),
    
    -- Configuration
    is_quota_based BOOLEAN DEFAULT FALSE,
    default_quota INT NULL,
    
    -- Métadonnées
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for features
CREATE INDEX IF NOT EXISTS idx_features_slug ON features(slug);
CREATE INDEX IF NOT EXISTS idx_features_category ON features(category);

-- Comments for features
COMMENT ON TABLE features IS 'Features disponibles dans le système';
COMMENT ON COLUMN features.category IS 'core, premium, enterprise';
COMMENT ON COLUMN features.is_quota_based IS 'Si limité par quota';
COMMENT ON COLUMN features.default_quota IS 'Quota par défaut si applicable';

-- ============================================================
-- TABLE: subscription_features (Features incluses par subscription)
-- ============================================================

CREATE TABLE IF NOT EXISTS subscription_features (
    subscription_id INT NOT NULL,
    feature_slug VARCHAR(100) NOT NULL,
    quota_limite INT NULL,
    
    PRIMARY KEY (subscription_id, feature_slug)
);

-- Indexes for subscription_features
CREATE INDEX IF NOT EXISTS idx_subscription_features_subscription_id ON subscription_features(subscription_id);

-- Comments for subscription_features
COMMENT ON TABLE subscription_features IS 'Features activées pour chaque subscription';
COMMENT ON COLUMN subscription_features.quota_limite IS 'NULL = illimité';

-- ============================================================
-- TABLE: invoices (Factures)
-- ============================================================

CREATE TABLE IF NOT EXISTS invoices (
    id SERIAL PRIMARY KEY,
    
    -- Référence
    invoice_number VARCHAR(50) UNIQUE NOT NULL,
    user_id INT NOT NULL,
    subscription_id INT NULL,
    
    -- Montant
    montant_ht DECIMAL(10,2) NOT NULL,
    tva DECIMAL(10,2) DEFAULT 0,
    montant_ttc DECIMAL(10,2) NOT NULL,
    devise VARCHAR(3) DEFAULT 'XOF',
    
    -- Période facturée
    periode_debut DATE NOT NULL,
    periode_fin DATE NOT NULL,
    
    -- Statut
    statut invoice_statut DEFAULT 'pending',
    
    -- Paiement
    date_emission DATE NOT NULL,
    date_echeance DATE NOT NULL,
    date_paiement DATE NULL,
    mode_paiement VARCHAR(50) NULL,
    transaction_id VARCHAR(100) NULL,
    
    -- Métadonnées
    items_json TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for invoices
CREATE INDEX IF NOT EXISTS idx_invoices_user_id ON invoices(user_id);
CREATE INDEX IF NOT EXISTS idx_invoices_subscription_id ON invoices(subscription_id);
CREATE INDEX IF NOT EXISTS idx_invoices_user_statut ON invoices(user_id, statut);
CREATE INDEX IF NOT EXISTS idx_invoices_invoice_number ON invoices(invoice_number);
CREATE INDEX IF NOT EXISTS idx_invoices_date_echeance ON invoices(date_echeance, statut);

-- Comments for invoices
COMMENT ON TABLE invoices IS 'Factures générées pour subscriptions et produits';
COMMENT ON COLUMN invoices.invoice_number IS 'INV-2026-09-0001';
COMMENT ON COLUMN invoices.mode_paiement IS 'orange_money, wave, card';
COMMENT ON COLUMN invoices.items_json IS 'JSON des lignes de facturation';

-- ============================================================
-- TABLE: usage_logs (Tracking usage features)
-- ============================================================

CREATE TABLE IF NOT EXISTS usage_logs (
    id BIGSERIAL PRIMARY KEY,
    
    -- Référence
    user_id INT NOT NULL,
    feature_slug VARCHAR(100) NOT NULL,
    product_id INT NULL,
    
    -- Usage
    action VARCHAR(100) NOT NULL,
    quantity INT DEFAULT 1,
    metadata JSONB NULL,
    
    -- Dates
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for usage_logs
CREATE INDEX IF NOT EXISTS idx_usage_logs_user_id ON usage_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_usage_logs_user_feature ON usage_logs(user_id, feature_slug);
CREATE INDEX IF NOT EXISTS idx_usage_logs_created_at ON usage_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_usage_logs_user_date ON usage_logs(user_id, created_at);

-- Comments for usage_logs
COMMENT ON TABLE usage_logs IS 'Logs d''usage des features (pour quota tracking et analytics)';
COMMENT ON COLUMN usage_logs.action IS 'post_generated, article_seo_created';
COMMENT ON COLUMN usage_logs.metadata IS 'Détails de l''action';

-- ============================================================
-- TRIGGER FUNCTIONS for updated_at timestamps
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply triggers to tables with updated_at
CREATE TRIGGER update_subscriptions_updated_at BEFORE UPDATE ON subscriptions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_products_updated_at BEFORE UPDATE ON products
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_products_updated_at BEFORE UPDATE ON user_products
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_invoices_updated_at BEFORE UPDATE ON invoices
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- SEED DATA: Features de base
-- ============================================================

INSERT INTO features (slug, nom, description, category, is_quota_based, default_quota) VALUES
('posts_generation', 'Génération de posts', 'Génération automatique de posts réseaux sociaux', 'marketing', TRUE, 20),
('articles_seo', 'Articles SEO', 'Génération d''articles SEO optimisés', 'seo', TRUE, 5),
('chatbot_ia', 'Chatbot IA', 'Chatbot IA conversationnel', 'ia', FALSE, NULL),
('chatbot_ia_advanced', 'Chatbot IA Avancé', 'Chatbot IA avec mémoire et analytics', 'ia', FALSE, NULL),
('videos_generation', 'Génération de vidéos', 'Génération automatique de vidéos courtes', 'video', TRUE, 5),
('analytics_basic', 'Analytics Basiques', 'Statistiques de base', 'core', FALSE, NULL),
('analytics_advanced', 'Analytics Avancées', 'Analytics détaillées avec rapports', 'premium', FALSE, NULL),
('support_email', 'Support Email', 'Support par email', 'core', FALSE, NULL),
('support_whatsapp', 'Support WhatsApp', 'Support prioritaire WhatsApp', 'premium', FALSE, NULL),
('api_webhooks', 'API Webhooks', 'Webhooks pour intégrations externes', 'enterprise', FALSE, NULL),
('white_label', 'White Label', 'Branding personnalisé', 'enterprise', FALSE, NULL),
('ab_testing', 'A/B Testing', 'Tests A/B pour contenus', 'premium', FALSE, NULL)
ON CONFLICT (slug) DO NOTHING;

-- ============================================================
-- SEED DATA: Products de base
-- ============================================================

INSERT INTO products (slug, nom, description, type, category, prix_unitaire, billing_type, features_json, quota_mensuel, is_active, is_visible) VALUES
-- Sites Web
('site-web-decouverte', 'Site Web Découverte', 'Site professionnel + Chatbot IA basique + Domaine 1 an', 'site_web', 'ia', 100000, 'one_time', '["chatbot_ia", "analytics_basic"]', NULL, TRUE, TRUE),
('site-web-professionnel', 'Site Web Professionnel', 'Site + Chatbot IA mémoire + 3 articles SEO + Espace client', 'site_web', 'ia', 250000, 'one_time', '["chatbot_ia_advanced", "articles_seo:3", "analytics_basic"]', '{"articles_seo": 3}'::jsonb, TRUE, TRUE),
('site-web-croissance', 'Site Web Croissance', 'Site + Chatbot avancé + 10 articles SEO + 12 mois modifications', 'site_web', 'ia', 350000, 'one_time', '["chatbot_ia_advanced", "articles_seo:10", "analytics_advanced", "support_whatsapp"]', '{"articles_seo": 10}'::jsonb, TRUE, TRUE),

-- Modules Standalone
('chatbot-ia-standalone', 'Chatbot IA Standalone', 'Chatbot IA pour site existant (1000 messages/mois)', 'module', 'ia', 50000, 'monthly', '["chatbot_ia_advanced", "analytics_basic"]', NULL, TRUE, TRUE),
('content-generator', 'Module Content Generator', 'Génération automatique posts (20/mois) + images IA', 'module', 'marketing', 30000, 'monthly', '["posts_generation:20", "analytics_basic"]', '{"posts": 20}'::jsonb, TRUE, TRUE),
('seo-auto', 'Module SEO Auto', '5 articles SEO/mois + optimisation on-page', 'module', 'seo', 40000, 'monthly', '["articles_seo:5", "analytics_basic"]', '{"articles_seo": 5}'::jsonb, TRUE, TRUE),
('video-ia', 'Module Video IA', '10 vidéos courtes/mois (Instagram, TikTok)', 'module', 'video', 60000, 'monthly', '["videos_generation:10", "analytics_basic"]', '{"videos": 10}'::jsonb, TRUE, TRUE),

-- Formations
('formation-facebook-ads', 'Formation Facebook Ads', '2h visio + eBook + accès espace apprenant', 'formation', 'marketing', 10000, 'one_time', '["support_email"]', NULL, TRUE, TRUE),
('formation-structurer-acquisition', 'Formation Structurer Acquisition', '2h visio + eBook CAC/LTV/Payback', 'formation', 'marketing', 15000, 'one_time', '["support_email"]', NULL, TRUE, TRUE),
('pack-duo-formations', 'Pack Duo Formations', '2 formations + 2 eBooks', 'formation', 'marketing', 20000, 'one_time', '["support_email"]', NULL, TRUE, TRUE)
ON CONFLICT (slug) DO NOTHING;

-- ============================================================
-- VERIFICATION
-- ============================================================

SELECT 'Tables SaaS créées avec succès!' as Status;
SELECT COUNT(*) as features_count FROM features;
SELECT COUNT(*) as products_count FROM products;

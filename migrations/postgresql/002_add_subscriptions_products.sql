-- Migration: Add subscriptions and products tables
-- Phase 1-S1 - ePerformance API Flow
-- PostgreSQL version
-- Date: 2026-09-10

-- ============================================================
-- ENUM TYPES
-- ============================================================

DO $$ BEGIN
    CREATE TYPE plan_type AS ENUM ('starter', 'pro', 'enterprise', 'custom');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE subscription_status AS ENUM ('pending', 'active', 'cancelled', 'expired');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE billing_cycle AS ENUM ('monthly', 'quarterly', 'yearly');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- ============================================================
-- SUBSCRIPTIONS TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL,
    product_id INT DEFAULT NULL,
    
    -- Subscription details
    plan_type plan_type NOT NULL DEFAULT 'starter',
    status subscription_status NOT NULL DEFAULT 'pending',
    
    -- Billing
    billing_cycle billing_cycle NOT NULL DEFAULT 'monthly',
    price DECIMAL(10, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'XOF',
    
    -- Dates
    start_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    end_date TIMESTAMP DEFAULT NULL,
    next_billing_date TIMESTAMP DEFAULT NULL,
    cancelled_at TIMESTAMP DEFAULT NULL,
    
    -- Payment integration
    payment_provider VARCHAR(50) DEFAULT NULL,
    payment_provider_id VARCHAR(255) DEFAULT NULL,
    last_payment_date TIMESTAMP DEFAULT NULL,
    last_payment_status VARCHAR(50) DEFAULT NULL,
    
    -- Metadata
    trial_ends_at TIMESTAMP DEFAULT NULL,
    auto_renew BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT DEFAULT NULL,
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for subscriptions
CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_product_id ON subscriptions(product_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_plan_type ON subscriptions(plan_type);
CREATE INDEX IF NOT EXISTS idx_subscriptions_payment_provider_id ON subscriptions(payment_provider_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_user_status ON subscriptions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_next_billing ON subscriptions(next_billing_date, status);

-- ============================================================
-- PRODUCTS TABLE (Phase 1-S1.2)
-- ============================================================

CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) UNIQUE NOT NULL,
    description TEXT DEFAULT NULL,
    category VARCHAR(100) DEFAULT NULL,
    
    -- Pricing
    base_price DECIMAL(10, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'XOF',
    
    -- Features (JSON stored as JSONB)
    features JSONB DEFAULT NULL,
    
    -- Status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_featured BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Metadata
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for products
CREATE INDEX IF NOT EXISTS idx_products_slug ON products(slug);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_is_active ON products(is_active);
CREATE INDEX IF NOT EXISTS idx_products_is_featured ON products(is_featured);

-- ============================================================
-- ADD FOREIGN KEY CONSTRAINT (after products table created)
-- ============================================================

ALTER TABLE subscriptions 
ADD CONSTRAINT fk_subscription_product 
FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL;

-- Foreign key for users (if users table exists)
-- ALTER TABLE subscriptions 
-- ADD CONSTRAINT fk_subscription_user 
-- FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

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

-- ============================================================
-- INSERT SAMPLE PRODUCTS
-- ============================================================

INSERT INTO products (name, slug, description, category, base_price, currency, features, is_active, is_featured) VALUES
(
    'ePerformance Starter',
    'eperformance-starter',
    'Plan de démarrage pour PME et startups - Outils marketing IA essentiels',
    'subscription',
    25000,
    'XOF',
    '["Diagnostic IA gratuit", "3 publications IA/mois", "Email automation basique", "Support email"]'::jsonb,
    TRUE,
    FALSE
),
(
    'ePerformance Pro',
    'eperformance-pro',
    'Plan professionnel - Suite complète marketing digital + automation',
    'subscription',
    75000,
    'XOF',
    '["Diagnostic IA illimité", "50 publications IA/mois", "Email automation avancée", "Chatbot IA personnalisé", "Tracking prospects", "Support prioritaire"]'::jsonb,
    TRUE,
    TRUE
),
(
    'ePerformance Enterprise',
    'eperformance-enterprise',
    'Plan entreprise - Solution sur mesure avec accompagnement dédié',
    'subscription',
    250000,
    'XOF',
    '["Tout Pro inclus", "Publications IA illimitées", "Multi-agents IA personnalisés", "API access", "Formation équipe", "Account manager dédié", "Support 24/7"]'::jsonb,
    TRUE,
    TRUE
),
(
    'Formation Marketing Digital',
    'formation-marketing-digital',
    'Formation complète marketing digital et acquisition clients (12 semaines)',
    'formation',
    150000,
    'XOF',
    '["12 semaines de formation", "Certification", "Projets pratiques", "Mentorat 1-to-1", "Accès communauté alumni"]'::jsonb,
    TRUE,
    FALSE
),
(
    'Audit Site Web',
    'audit-site-web',
    'Audit complet de votre site web (SEO, UX, performance, conversion)',
    'service',
    50000,
    'XOF',
    '["Analyse technique complète", "Rapport détaillé", "Recommandations priorisées", "Session conseil 1h"]'::jsonb,
    TRUE,
    FALSE
)
ON CONFLICT (slug) DO NOTHING;

-- ============================================================
-- VERIFICATION
-- ============================================================

-- Vérifier les tables créées
SELECT 
    'Tables créées:' as message,
    COUNT(*) as count 
FROM information_schema.tables 
WHERE table_schema = 'public' 
AND table_name IN ('subscriptions', 'products');

-- Vérifier les produits insérés
SELECT 
    'Produits insérés:' as message,
    COUNT(*) as count 
FROM products;

-- Afficher les produits
SELECT id, name, slug, base_price, currency, is_active, is_featured 
FROM products 
ORDER BY base_price ASC;

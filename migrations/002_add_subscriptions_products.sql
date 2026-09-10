-- Migration: Add subscriptions and products tables
-- Phase 1-S1 - ePerformance API Flow
-- Date: 2026-09-10

-- ============================================================
-- SUBSCRIPTIONS TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS subscriptions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    product_id INT DEFAULT NULL,
    
    -- Subscription details
    plan_type ENUM('starter', 'pro', 'enterprise', 'custom') NOT NULL DEFAULT 'starter',
    status ENUM('pending', 'active', 'cancelled', 'expired') NOT NULL DEFAULT 'pending',
    
    -- Billing
    billing_cycle ENUM('monthly', 'quarterly', 'yearly') NOT NULL DEFAULT 'monthly',
    price DECIMAL(10, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'XOF',
    
    -- Dates
    start_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    end_date DATETIME DEFAULT NULL,
    next_billing_date DATETIME DEFAULT NULL,
    cancelled_at DATETIME DEFAULT NULL,
    
    -- Payment integration
    payment_provider VARCHAR(50) DEFAULT NULL,
    payment_provider_id VARCHAR(255) DEFAULT NULL,
    last_payment_date DATETIME DEFAULT NULL,
    last_payment_status VARCHAR(50) DEFAULT NULL,
    
    -- Metadata
    trial_ends_at DATETIME DEFAULT NULL,
    auto_renew BOOLEAN NOT NULL DEFAULT TRUE,
    notes TEXT DEFAULT NULL,
    
    -- Timestamps
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- Foreign keys
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    
    -- Indexes
    INDEX idx_user_id (user_id),
    INDEX idx_product_id (product_id),
    INDEX idx_status (status),
    INDEX idx_plan_type (plan_type),
    INDEX idx_payment_provider_id (payment_provider_id),
    INDEX idx_subscription_user_status (user_id, status),
    INDEX idx_subscription_next_billing (next_billing_date, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================
-- PRODUCTS TABLE (Phase 1-S1.2)
-- ============================================================

CREATE TABLE IF NOT EXISTS products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) UNIQUE NOT NULL,
    description TEXT DEFAULT NULL,
    category VARCHAR(100) DEFAULT NULL,
    
    -- Pricing
    base_price DECIMAL(10, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'XOF',
    
    -- Features (JSON stored as TEXT)
    features TEXT DEFAULT NULL,
    
    -- Status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_featured BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Metadata
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- Indexes
    INDEX idx_slug (slug),
    INDEX idx_category (category),
    INDEX idx_is_active (is_active),
    INDEX idx_is_featured (is_featured)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================
-- ADD FOREIGN KEY CONSTRAINT (after products table created)
-- ============================================================

ALTER TABLE subscriptions 
ADD CONSTRAINT fk_subscription_product 
FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL;


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
    '["Diagnostic IA gratuit", "3 publications IA/mois", "Email automation basique", "Support email"]',
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
    '["Diagnostic IA illimité", "50 publications IA/mois", "Email automation avancée", "Chatbot IA personnalisé", "Tracking prospects", "Support prioritaire"]',
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
    '["Tout Pro inclus", "Publications IA illimitées", "Multi-agents IA personnalisés", "API access", "Formation équipe", "Account manager dédié", "Support 24/7"]',
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
    '["12 semaines de formation", "Certification", "Projets pratiques", "Mentorat 1-to-1", "Accès communauté alumni"]',
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
    '["Analyse technique complète", "Rapport détaillé", "Recommandations priorisées", "Session conseil 1h"]',
    TRUE,
    FALSE
);


-- ============================================================
-- VERIFICATION
-- ============================================================

-- Vérifier les tables créées
SELECT 
    'Tables créées:' as message,
    COUNT(*) as count 
FROM information_schema.tables 
WHERE table_schema = DATABASE() 
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

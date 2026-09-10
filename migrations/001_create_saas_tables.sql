-- ============================================================
-- SQL Migration: Create SaaS tables for ePerformance unified system.
-- Run: mysql -u unified_dev -p unified_ia_dev < migrations/001_create_saas_tables.sql
-- ============================================================
-- TABLE: subscriptions (Abonnements récurrents)
-- ============================================================

CREATE TABLE IF NOT EXISTS subscriptions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    candidat_id INT NULL COMMENT 'Si vient du chemin diagnostic',
    
    -- Type abonnement
    type ENUM('accompagnement', 'module_standalone') NOT NULL,
    niveau ENUM('essentielle', 'croissance', 'acceleration') NULL COMMENT 'Pour accompagnement',
    
    -- Pricing
    montant_mensuel DECIMAL(10,2) NOT NULL,
    devise VARCHAR(3) DEFAULT 'XOF',
    
    -- Durée
    engagement_mois INT NOT NULL COMMENT '3, 6, 12 mois',
    date_debut DATE NOT NULL,
    date_fin DATE NOT NULL,
    
    -- Statut
    statut ENUM('active', 'paused', 'cancelled', 'expired') DEFAULT 'active',
    auto_renew BOOLEAN DEFAULT FALSE,
    
    -- Facturation
    facturation_jour INT DEFAULT 1 COMMENT 'Jour du mois pour facturation',
    prochaine_facturation DATE,
    derniere_facturation DATE,
    
    -- Métadonnées
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    cancelled_at TIMESTAMP NULL,
    cancellation_reason TEXT NULL,
    
    -- Foreign keys sans contraintes pour éviter erreur 150
    KEY fk_user_id (user_id),
    KEY fk_candidat_id (candidat_id),
    INDEX idx_user_statut (user_id, statut),
    INDEX idx_prochaine_facturation (prochaine_facturation, statut)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Abonnements récurrents (accompagnement ou modules standalone)';


-- ============================================================
-- TABLE: products (Catalogue produits)
-- ============================================================

CREATE TABLE IF NOT EXISTS products (
    id INT PRIMARY KEY AUTO_INCREMENT,
    
    -- Identification
    slug VARCHAR(100) UNIQUE NOT NULL,
    nom VARCHAR(255) NOT NULL,
    description TEXT,
    
    -- Type produit
    type ENUM('site_web', 'module', 'formation', 'service') NOT NULL,
    category VARCHAR(50) COMMENT 'ia, marketing, seo, video',
    
    -- Pricing
    prix_unitaire DECIMAL(10,2) NOT NULL,
    devise VARCHAR(3) DEFAULT 'XOF',
    billing_type ENUM('one_time', 'monthly', 'yearly') NOT NULL,
    
    -- Features
    features_json TEXT COMMENT 'JSON: ["chatbot_ia", "posts_generation:20"]',
    quota_mensuel JSON NULL COMMENT '{"posts": 20, "articles_seo": 5}',
    
    -- Visibilité
    is_active BOOLEAN DEFAULT TRUE,
    is_visible BOOLEAN DEFAULT TRUE COMMENT 'Visible sur catalogue public',
    requires_approval BOOLEAN DEFAULT FALSE COMMENT 'Nécessite validation manuelle',
    
    -- Métadonnées
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_slug (slug),
    INDEX idx_type_active (type, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Catalogue des produits et modules disponibles';


-- ============================================================
-- TABLE: user_products (Produits achetés par user)
-- ============================================================

CREATE TABLE IF NOT EXISTS user_products (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    product_id INT NOT NULL,
    subscription_id INT NULL COMMENT 'Si lié à un abonnement',
    
    -- Statut
    statut ENUM('active', 'expired', 'cancelled') DEFAULT 'active',
    
    -- Dates
    date_achat DATE NOT NULL,
    date_activation DATE,
    date_expiration DATE NULL COMMENT 'Pour produits one-time avec durée',
    
    -- Usage tracking
    usage_current JSON NULL COMMENT '{"posts_generated": 15}',
    usage_limit JSON NULL COMMENT '{"posts_generated": 20}',
    
    -- Métadonnées
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    KEY fk_user_id_up (user_id),
    KEY fk_product_id (product_id),
    KEY fk_subscription_id (subscription_id),
    INDEX idx_user_statut (user_id, statut),
    INDEX idx_product (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Produits achetés/activés par utilisateur';


-- ============================================================
-- TABLE: features (Features disponibles dans le système)
-- ============================================================

CREATE TABLE IF NOT EXISTS features (
    id INT PRIMARY KEY AUTO_INCREMENT,
    
    -- Identification
    slug VARCHAR(100) UNIQUE NOT NULL,
    nom VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(50) COMMENT 'core, premium, enterprise',
    
    -- Configuration
    is_quota_based BOOLEAN DEFAULT FALSE COMMENT 'Si limité par quota',
    default_quota INT NULL COMMENT 'Quota par défaut si applicable',
    
    -- Métadonnées
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_slug (slug),
    INDEX idx_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Features disponibles dans le système';


-- ============================================================
-- TABLE: subscription_features (Features incluses par subscription)
-- ============================================================

CREATE TABLE IF NOT EXISTS subscription_features (
    subscription_id INT NOT NULL,
    feature_slug VARCHAR(100) NOT NULL,
    quota_limite INT NULL COMMENT 'NULL = illimité',
    
    PRIMARY KEY (subscription_id, feature_slug),
    KEY fk_subscription_id_sf (subscription_id),
    INDEX idx_subscription (subscription_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Features activées pour chaque subscription';


-- ============================================================
-- TABLE: invoices (Factures)
-- ============================================================

CREATE TABLE IF NOT EXISTS invoices (
    id INT PRIMARY KEY AUTO_INCREMENT,
    
    -- Référence
    invoice_number VARCHAR(50) UNIQUE NOT NULL COMMENT 'INV-2026-09-0001',
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
    statut ENUM('draft', 'pending', 'paid', 'failed', 'refunded') DEFAULT 'pending',
    
    -- Paiement
    date_emission DATE NOT NULL,
    date_echeance DATE NOT NULL,
    date_paiement DATE NULL,
    mode_paiement VARCHAR(50) NULL COMMENT 'orange_money, wave, card',
    transaction_id VARCHAR(100) NULL,
    
    -- Métadonnées
    items_json TEXT COMMENT 'JSON des lignes de facturation',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    KEY fk_user_id_inv (user_id),
    KEY fk_subscription_id_inv (subscription_id),
    INDEX idx_user_statut (user_id, statut),
    INDEX idx_invoice_number (invoice_number),
    INDEX idx_date_echeance (date_echeance, statut)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Factures générées pour subscriptions et produits';


-- ============================================================
-- TABLE: usage_logs (Tracking usage features)
-- ============================================================

CREATE TABLE IF NOT EXISTS usage_logs (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    
    -- Référence
    user_id INT NOT NULL,
    feature_slug VARCHAR(100) NOT NULL,
    product_id INT NULL,
    
    -- Usage
    action VARCHAR(100) NOT NULL COMMENT 'post_generated, article_seo_created',
    quantity INT DEFAULT 1,
    metadata JSON NULL COMMENT 'Détails de l\'action',
    
    -- Dates
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    KEY fk_user_id_ul (user_id),
    INDEX idx_user_feature (user_id, feature_slug),
    INDEX idx_created_at (created_at),
    INDEX idx_user_date (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Logs d\'usage des features (pour quota tracking et analytics)';


-- ============================================================
-- SEED DATA: Features de base
-- ============================================================

INSERT INTO features (slug, nom, description, category, is_quota_based, default_quota) VALUES
('posts_generation', 'Génération de posts', 'Génération automatique de posts réseaux sociaux', 'marketing', TRUE, 20),
('articles_seo', 'Articles SEO', 'Génération d\'articles SEO optimisés', 'seo', TRUE, 5),
('chatbot_ia', 'Chatbot IA', 'Chatbot IA conversationnel', 'ia', FALSE, NULL),
('chatbot_ia_advanced', 'Chatbot IA Avancé', 'Chatbot IA avec mémoire et analytics', 'ia', FALSE, NULL),
('videos_generation', 'Génération de vidéos', 'Génération automatique de vidéos courtes', 'video', TRUE, 5),
('analytics_basic', 'Analytics Basiques', 'Statistiques de base', 'core', FALSE, NULL),
('analytics_advanced', 'Analytics Avancées', 'Analytics détaillées avec rapports', 'premium', FALSE, NULL),
('support_email', 'Support Email', 'Support par email', 'core', FALSE, NULL),
('support_whatsapp', 'Support WhatsApp', 'Support prioritaire WhatsApp', 'premium', FALSE, NULL),
('api_webhooks', 'API Webhooks', 'Webhooks pour intégrations externes', 'enterprise', FALSE, NULL),
('white_label', 'White Label', 'Branding personnalisé', 'enterprise', FALSE, NULL),
('ab_testing', 'A/B Testing', 'Tests A/B pour contenus', 'premium', FALSE, NULL);


-- ============================================================
-- SEED DATA: Products de base
-- ============================================================

INSERT INTO products (slug, nom, description, type, category, prix_unitaire, billing_type, features_json, quota_mensuel, is_active, is_visible) VALUES
-- Sites Web
('site-web-decouverte', 'Site Web Découverte', 'Site professionnel + Chatbot IA basique + Domaine 1 an', 'site_web', 'ia', 100000, 'one_time', '["chatbot_ia", "analytics_basic"]', NULL, TRUE, TRUE),
('site-web-professionnel', 'Site Web Professionnel', 'Site + Chatbot IA mémoire + 3 articles SEO + Espace client', 'site_web', 'ia', 250000, 'one_time', '["chatbot_ia_advanced", "articles_seo:3", "analytics_basic"]', '{"articles_seo": 3}', TRUE, TRUE),
('site-web-croissance', 'Site Web Croissance', 'Site + Chatbot avancé + 10 articles SEO + 12 mois modifications', 'site_web', 'ia', 350000, 'one_time', '["chatbot_ia_advanced", "articles_seo:10", "analytics_advanced", "support_whatsapp"]', '{"articles_seo": 10}', TRUE, TRUE),

-- Modules Standalone
('chatbot-ia-standalone', 'Chatbot IA Standalone', 'Chatbot IA pour site existant (1000 messages/mois)', 'module', 'ia', 50000, 'monthly', '["chatbot_ia_advanced", "analytics_basic"]', NULL, TRUE, TRUE),
('content-generator', 'Module Content Generator', 'Génération automatique posts (20/mois) + images IA', 'module', 'marketing', 30000, 'monthly', '["posts_generation:20", "analytics_basic"]', '{"posts": 20}', TRUE, TRUE),
('seo-auto', 'Module SEO Auto', '5 articles SEO/mois + optimisation on-page', 'module', 'seo', 40000, 'monthly', '["articles_seo:5", "analytics_basic"]', '{"articles_seo": 5}', TRUE, TRUE),
('video-ia', 'Module Video IA', '10 vidéos courtes/mois (Instagram, TikTok)', 'module', 'video', 60000, 'monthly', '["videos_generation:10", "analytics_basic"]', '{"videos": 10}', TRUE, TRUE),

-- Formations
('formation-facebook-ads', 'Formation Facebook Ads', '2h visio + eBook + accès espace apprenant', 'formation', 'marketing', 10000, 'one_time', '["support_email"]', NULL, TRUE, TRUE),
('formation-structurer-acquisition', 'Formation Structurer Acquisition', '2h visio + eBook CAC/LTV/Payback', 'formation', 'marketing', 15000, 'one_time', '["support_email"]', NULL, TRUE, TRUE),
('pack-duo-formations', 'Pack Duo Formations', '2 formations + 2 eBooks', 'formation', 'marketing', 20000, 'one_time', '["support_email"]', NULL, TRUE, TRUE);


-- ============================================================
-- VERIFICATION
-- ============================================================

SELECT 'Tables SaaS créées avec succès!' as Status;
SELECT COUNT(*) as features_count FROM features;
SELECT COUNT(*) as products_count FROM products;

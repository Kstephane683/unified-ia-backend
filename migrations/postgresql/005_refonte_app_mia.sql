-- ============================================================================
-- 005_refonte_app_mia.sql — Refonte de l'app Mia (chantiers B1-B4)
-- Date : 2026-09-19
--
-- CE QUE FAIT CETTE MIGRATION
-- ---------------------------
-- Ajoute les colonnes exigées par l'app Mia (SaaS de gestion multi-tenant) :
--   · users               : provisionnement des propriétaires (B1) + 2FA (B2)
--   · chatbot_sites       : horaires (B3) + réglages de notification (B4)
-- Crée les deux NOUVELLES tables (audit B2, notifications in-app B4).
--
-- POURQUOI CES ALTER TABLE SONT NÉCESSAIRES
-- -----------------------------------------
-- `init_db()` exécute create_all au boot : il crée les tables ABSENTES mais
-- n'ajoute JAMAIS une colonne à une table existante. Ces colonnes ont été
-- ajoutées au modèle ORM — sans les ALTER, l'ORM annoncerait des colonnes que
-- la base de production n'a pas.
--
-- COMMENT ELLE EST APPLIQUÉE
-- --------------------------
--   1. AUTOMATIQUEMENT au boot : backend/core/migrations_boot.py exécute le
--      même travail, idempotent, via l'inspecteur SQLAlchemy (voie préférée) ;
--   2. MANUELLEMENT si besoin (Import_MIGRATIONS_RAILWAY.sh) : ce fichier est
--      totalement idempotent (IF NOT EXISTS partout).
--
-- Rien ici n'est destructeur : aucune suppression, aucun renommage, aucun
-- changement de type. Les colonnes ajoutées sont NULLABLE — le déploiement ne
-- peut pas échouer sur des lignes existantes.
-- ============================================================================

-- ============================================================================
-- B1/B2 — users : provisionnement des comptes propriétaires + 2FA
-- ============================================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS nom VARCHAR(200);
ALTER TABLE users ADD COLUMN IF NOT EXISTS site_id VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS role_client VARCHAR(20);
ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_users_site_id ON users(site_id);
CREATE INDEX IF NOT EXISTS idx_users_role_client ON users(role_client);

-- NOTE DÉSIGN (à ne pas « corriger » par un ALTER TYPE) :
-- Les rôles granulaires client_admin / client_operator / client_reader sont
-- dans `role_client` (VARCHAR validé applicativement, cf. backend/core/auth.py
-- HIERARCHIE_CLIENT), PAS dans l'enum natif `user_role`. Y ajouter des valeurs
-- exigerait ALTER TYPE ... ADD VALUE — fragile en déploiement — pour un
-- bénéfice nul : `role` garde sa sémantique existante ('client' pour un
-- propriétaire), la granularité vit à côté.

-- ============================================================================
-- B3/B4 — chatbot_sites : horaires, secteur, réglages de notification
-- ============================================================================

ALTER TABLE chatbot_sites ADD COLUMN IF NOT EXISTS sector VARCHAR(50);
ALTER TABLE chatbot_sites ADD COLUMN IF NOT EXISTS horaires JSONB;
ALTER TABLE chatbot_sites ADD COLUMN IF NOT EXISTS notification_settings JSONB;

-- `sector` porte le slug du noyau (agent-ia-web/eperf_core/sectors.py) :
-- restauration, hotellerie, ecommerce, immobilier, mlm, beaute, sante,
-- education, evenementiel, tourisme, artisan, vitrine (12 secteurs clients ;
-- `blog` et `email` existent dans le noyau mais ne sont pas des secteurs
-- clients de l'app).

-- ============================================================================
-- B2 — audit_log : journal des actions sensibles
-- (NOUVELLE table : create_all l'aurait créée seule ; elle est déclarée ici
--  pour que la voie manuelle soit complète et pour documenter le schéma.)
-- ============================================================================

CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER DEFAULT NULL,
    user_email VARCHAR(255) DEFAULT NULL,
    site_id VARCHAR(100) DEFAULT NULL,
    action VARCHAR(100) NOT NULL,
    details JSONB DEFAULT NULL,
    ip VARCHAR(100) DEFAULT NULL,
    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_site_id ON audit_log(site_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_date ON audit_log(date);

COMMENT ON TABLE audit_log IS 'Journal des actions sensibles (app Mia B2) : provisionnement, configuration, RGPD, 2FA. Jamais de contenu de conversation ni de secret dans details.';

-- ============================================================================
-- B4 — client_notifications : notifications in-app du propriétaire
-- ============================================================================

CREATE TABLE IF NOT EXISTS client_notifications (
    id SERIAL PRIMARY KEY,
    site_id VARCHAR(100) NOT NULL,
    type VARCHAR(50) NOT NULL,
    titre VARCHAR(200) NOT NULL,
    corps TEXT DEFAULT NULL,
    conversation_id VARCHAR(100) DEFAULT NULL,
    lu BOOLEAN DEFAULT FALSE NOT NULL,
    date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_client_notifications_site_id ON client_notifications(site_id);
CREATE INDEX IF NOT EXISTS idx_client_notifications_type ON client_notifications(type);
CREATE INDEX IF NOT EXISTS idx_client_notifications_lu ON client_notifications(lu);
CREATE INDEX IF NOT EXISTS idx_client_notifications_conv ON client_notifications(conversation_id);
CREATE INDEX IF NOT EXISTS idx_client_notifications_date ON client_notifications(date_creation);
CREATE INDEX IF NOT EXISTS idx_client_notifications_site_lu ON client_notifications(site_id, lu);
CREATE INDEX IF NOT EXISTS idx_client_notifications_site_date ON client_notifications(site_id, date_creation);

COMMENT ON TABLE client_notifications IS 'Boîte in-app du propriétaire (app Mia B4) : écrite pour CHAQUE événement (nouveau lead, escalade, nouveau visiteur), indépendamment des canaux externes — le filet qui ne dépend d''aucune clé.';

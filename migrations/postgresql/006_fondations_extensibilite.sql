-- ============================================================================
-- 006_fondations_extensibilite.sql — Fondations d'extensibilité de l'app Mia
-- Date : 2026-09-19
--
-- CE QUE FAIT CETTE MIGRATION
-- ---------------------------
--   · users            : colonne `plan` (free | premium | pro) — Mission 1 ;
--   · fonctionnalites  : NOUVELLE table des feature flags (seedée au boot) ;
--   · abonnements      : NOUVELLE table des intentions/souscriptions Jeko ;
--   · app_analytics    : NOUVELLE table du tracking applicatif (Mission 2).
--
-- POURQUOI L'ALTER TABLE EST NÉCESSAIRE
-- -------------------------------------
-- `init_db()` exécute create_all au boot : il crée les tables ABSENTES mais
-- n'ajoute JAMAIS une colonne à une table existante (piège du projet). La
-- colonne `plan` a été ajoutée au modèle ORM (backend/core/models.py) alors
-- que `users` existe déjà en production — sans l'ALTER, l'ORM annoncerait
-- une colonne que la base n'a pas.
--
-- COMMENT ELLE EST APPLIQUÉE
-- --------------------------
--   1. AUTOMATIQUEMENT au boot : backend/core/migrations_boot.py (colonne)
--      + create_all (tables nouvelles) + seed idempotente des flags
--      (backend/core/fonctionnalites.py) — voie préférée ;
--   2. MANUELLEMENT si besoin (IMPORT_MIGRATIONS_RAILWAY.sh) : ce fichier
--      est totalement idempotent (IF NOT EXISTS partout).
--
-- Rien ici n'est destructeur : aucune suppression, aucun renommage, aucun
-- changement de type. La colonne `plan` est NULLABLE avec DEFAULT 'free' —
-- le déploiement ne peut pas échouer sur les lignes existantes, et tout
-- compte préexistant devient `free`.
-- ============================================================================

-- ============================================================================
-- Mission 1 — users.plan : plan du compte (fondation des fonctionnalités)
-- ============================================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS plan VARCHAR(20) DEFAULT 'free';
CREATE INDEX IF NOT EXISTS idx_users_plan ON users(plan);

-- NOTE DÉSIGN (à ne pas « corriger » par un ALTER TYPE) :
-- free | premium | pro vivent dans un VARCHAR validé applicativement (même
-- choix que role_client) : y ajouter un plan ne doit exiger AUCUN ALTER TYPE.
-- `premium` et `pro` EXISTENT dans le catalogue mais rien ne les active
-- encore : l'abonnement Jeko n'est pas branché (cf. docs/refonte-app-mia/
-- EXTENSIBILITE.md).

-- ============================================================================
-- Mission 1 — fonctionnalites : feature flags (seed IDEMPOTENTE au boot)
-- ============================================================================

CREATE TABLE IF NOT EXISTS fonctionnalites (
    id SERIAL PRIMARY KEY,
    cle VARCHAR(50) NOT NULL UNIQUE,
    plan_minimum VARCHAR(20) DEFAULT 'free' NOT NULL,
    active BOOLEAN DEFAULT TRUE NOT NULL,
    description TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_fonctionnalites_cle ON fonctionnalites(cle);

-- Flags seedés au boot par backend/core/fonctionnalites.py (une ligne
-- absente est créée, une ligne présente n'est JAMAIS écrasée) :
--   notifications_push      (free,    ACTIVE)  · analytics_export (free, ACTIVE)
--   ia_en_direct            (free,    ACTIVE)  · whatsapp_notifications (premium, INACTIF)
--   rcs_messages            (premium, INACTIF) · abonnement_jeko (premium, INACTIF)
-- La seed ne contient AUCUNE donnée : elle est rejouée à chaque boot.

COMMENT ON TABLE fonctionnalites IS 'Feature flags de l''app Mia (fondations d''extensibilité) : clé unique, plan minimum, interrupteur actif. Verrou 403 explicite via exiger_fonctionnalite().';

-- ============================================================================
-- Mission 1 — abonnements : intentions et souscriptions Jeko
-- ============================================================================

CREATE TABLE IF NOT EXISTS abonnements (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    plan VARCHAR(20) NOT NULL,
    statut VARCHAR(30) NOT NULL,
    fournisseur VARCHAR(30) DEFAULT 'jeko',
    reference_fournisseur VARCHAR(200) DEFAULT NULL,
    metadata JSONB DEFAULT NULL,
    date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    date_mise_a_jour TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_abonnements_user_id ON abonnements(user_id);
CREATE INDEX IF NOT EXISTS idx_abonnements_statut ON abonnements(statut);
CREATE INDEX IF NOT EXISTS idx_abonnements_reference ON abonnements(reference_fournisseur);

-- statut : intention (enregistrée sans fournisseur) | en_attente (fournisseur
-- appelé, webhook attendu) | actif | annule | echec_fournisseur.
-- Le statut `actif` (posé PAR LE WEBHOOK SIGNÉ POST /api/webhooks/jeko) est
-- le seul mécanisme qui élève user.plan aujourd'hui.
-- Aucun montant : la tarification n'est pas décidée (décision du propriétaire).

COMMENT ON TABLE abonnements IS 'Intentions et souscriptions d''abonnement (fournisseur Jeko). Sans clés JEKO_*, POST /subscribe enregistre l''intention (statut intention) et répond un état explicite — rien n''est perdu.';

-- ============================================================================
-- Mission 2 — app_analytics : tracking APPLICATIF (usage de l'app Mia)
-- ============================================================================

CREATE TABLE IF NOT EXISTS app_analytics (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(64) NOT NULL UNIQUE,
    installation_id VARCHAR(64) NOT NULL,
    user_id INTEGER DEFAULT NULL,
    site_id VARCHAR(100) DEFAULT NULL,
    event_type VARCHAR(50) NOT NULL,
    metadata JSONB DEFAULT NULL,
    date_evenement TIMESTAMP NOT NULL,
    date_reception TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_app_analytics_event_id ON app_analytics(event_id);
CREATE INDEX IF NOT EXISTS idx_app_analytics_installation ON app_analytics(installation_id);
CREATE INDEX IF NOT EXISTS idx_app_analytics_site_date ON app_analytics(site_id, date_evenement);
CREATE INDEX IF NOT EXISTS idx_app_analytics_type ON app_analytics(event_type);
CREATE INDEX IF NOT EXISTS idx_app_analytics_user_id ON app_analytics(user_id);
CREATE INDEX IF NOT EXISTS idx_app_analytics_reception ON app_analytics(date_reception);

-- event_id : UUID produit PAR L'APP — UNIQUE = déduplication (rejeu de batch
-- ignoré silencieusement). date_evenement : horodatage CLIENT (local-first) ;
-- date_reception : horodatage SERVEUR (borne de confiance des périodes).
-- Types (énumération applicative extensible) : install, app_open,
-- session_start, session_end, screen_view, feature_use, notification_open,
-- upgrade_intent, consent.
-- CE QUE CETTE TABLE N'ENREGISTRE PAS : aucune donnée personnelle du visiteur
-- final des sites clients, aucune conversation — c'est l'usage de l'APP.

COMMENT ON TABLE app_analytics IS 'Tracking applicatif de l''app Mia (local-first, dédupliqué par event_id) : usage de l''app, jamais les conversations visiteurs. Agrégats servis par GET /api/client/v1/analytics/app, scopés au site du compte.';

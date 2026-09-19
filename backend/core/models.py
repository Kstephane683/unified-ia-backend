"""
SQLAlchemy models for unified IA system.

Architecture:
- Reuse existing 63 tables from ePerformance
- Add new tables for unified system
- Auth unified (users table replaces multiple auth systems)
- Relations with foreign keys
"""

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date, Boolean, 
    Enum, ForeignKey, Index, TIMESTAMP, Numeric
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
from backend.core.database import Base


# ============================================================
# AUTH UNIFIED — Replaces admins + candidats auth + formation_inscrits auth
# ============================================================

class User(Base):
    """
    Unified authentication table.
    Replaces separate auth in: admins, candidats, formation_inscrits

    Refonte app Mia (chantier B1/B2, 2026-09-19) — colonnes ajoutées :
    nom, site_id, role_client, must_change_password, totp_secret, totp_enabled.

    POURQUOI LES RÔLES CLIENT NE SONT PAS DANS LA COLONNE `role`
    ------------------------------------------------------------
    `role` est un Enum PostgreSQL NATIF (`user_role`) créé par create_all en
    production. Y ajouter client_admin/client_operator/client_reader exigerait
    un ALTER TYPE ... ADD VALUE — fragile en déploiement (ordre d'exécution,
    transaction, recréation sur base neuve) pour un bénéfice nul. La granularité
    vit donc dans `role_client`, une colonne VARCHAR validée APPLICATIVEMENT
    (backend.core.auth.HIERARCHIE_CLIENT), tandis que `role` garde sa sémantique
    existante : un propriétaire de site a role='client' (compatible avec
    tout l'existant, y compris verify_role) et role_client='client_admin' etc.
    Voir docs/refonte-app-mia/API-CLIENT-V1.md §2.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum('admin', 'client', 'apprenant', 'lead', name='user_role'),
                  default='lead', nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    # --- Refonte app Mia (B1/B2) — colonnes créées par la migration au boot
    # (backend/core/migrations_boot.py) ; create_all ne les aurait PAS ajoutées
    # à la table existante de production (piège connu du projet).
    nom = Column(String(200), nullable=True, comment='Nom affiché du compte')
    site_id = Column(String(100), nullable=True, index=True,
                     comment='Site géré par ce compte (multi-tenant app Mia)')
    role_client = Column(String(20), nullable=True, index=True,
                         comment='Granularité client : client_admin | '
                                 'client_operator | client_reader (null = '
                                 'compte non provisioné pour l\'app Mia)')
    must_change_password = Column(Boolean, nullable=True,
                                  comment='Vrai après provisionnement : toutes '
                                          'les routes client refusent tant que '
                                          'le mot de passe temporaire n\'a pas '
                                          'été changé')
    totp_secret = Column(Text, nullable=True,
                         comment='Secret TOTP chiffré (Fernet, clé dérivée de '
                                 'SECRET_KEY) — jamais en clair, jamais renvoyé')
    totp_enabled = Column(Boolean, nullable=True,
                          comment='2FA TOTP active (obligatoire pour '
                                  'client_admin)')

    # Relationships (candidat and formation_inscrit relationships disabled until migration adds user_id FK)
    # candidat = relationship("Candidat", back_populates="user", uselist=False)
    # formation_inscrit = relationship("FormationInscrit", back_populates="user", uselist=False)


class UserRole(Base):
    """
    Pivot table for multiple roles (e.g., client + apprenant)
    """
    __tablename__ = "user_roles"
    
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    role = Column(Enum('admin', 'client', 'apprenant', name='role_type'), primary_key=True)
    granted_at = Column(DateTime, default=datetime.now, nullable=False)


# ============================================================
# CRM — Existing tables from ePerformance
# ============================================================

class Candidat(Base):
    """
    Prospects and clients (existing table).
    Now linked to users table for auth.
    """
    __tablename__ = "candidats"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    nom = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    whatsapp = Column(String(50))
    entreprise = Column(String(255))
    secteur = Column(String(100))
    score = Column(Integer, default=0)
    niveau_accompagnement = Column(
        Enum('essentielle', 'croissance', 'acceleration', name='niveau_accompagnement'),
        default='essentielle'
    )
    statut = Column(
        Enum('en_attente', 'accepte', 'refuse', 'alumni', name='candidat_statut'),
        default='en_attente',
        index=True
    )
    mot_de_passe = Column(String(255))  # Legacy, migrate to users table
    token_activation = Column(String(64))
    compte_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    date_acceptation = Column(DateTime)
    
    # MLM
    mlm_actif = Column(Boolean, default=False)
    ref_parrainage = Column(String(20))
    parrain_id = Column(Integer, ForeignKey('candidats.id'))
    nb_parrainages = Column(Integer, default=0)
    
    # Risk scoring
    score_risque = Column(Integer, default=0)
    niveau_risque = Column(
        Enum('stable', 'attention', 'critique', name='niveau_risque'),
        default='stable'
    )
    risque_updated_at = Column(DateTime)
    
    # Activity
    derniere_connexion = Column(DateTime)
    
    # Upsell
    upsell_html = Column(Text)
    upsell_at = Column(DateTime)
    upsell_envoye = Column(Boolean, default=False)
    upsell_envoye_at = Column(DateTime)
    
    # Alumni
    alumni_at = Column(DateTime)
    reactivation_j30_at = Column(DateTime)
    reactivation_j60_at = Column(DateTime)
    reactivation_manuel_at = Column(DateTime)
    
    # Certifications & suivi
    certification_ref = Column(String(40))
    certification_at = Column(DateTime)
    mdp_temp = Column(String(50))
    note_suivi = Column(Text)
    pipeline_statut = Column(
        Enum('nouveau', 'contacte', 'diagnostic_envoye', 'proposition_envoyee', 
             'negociation', 'accepte', 'refuse', name='pipeline_statut'),
        default='nouveau'
    )
    
    # New: link to unified auth (to be added via migration)
    # user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=True)
    
    # Relationships (commented until user_id column exists)
    # user = relationship("User", back_populates="candidat")
    # parrain = relationship("Candidat", remote_side=[id], backref="filleuls")


class ClientWeb(Base):
    """
    Websites in production/accompagnement (existing table).
    Merged with clients_site_web_75k via type_offre column.
    """
    __tablename__ = "clients_web"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    nom = Column(String(200), nullable=False)
    email = Column(String(200), nullable=False)
    site_web = Column(String(300))
    telephone = Column(String(50))
    notes = Column(Text)
    statut = Column(
        Enum('actif', 'en_attente', 'accompagnement', 'termine', name='client_web_statut'),
        default='actif',
        index=True
    )
    
    # Accompagnement
    date_creation_site = Column(Date)
    accompagnement_actif = Column(Boolean, default=False)
    accompagnement_debut = Column(Date)
    accompagnement_fin = Column(Date)
    mois_en_cours = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    
    # Technical
    plateforme_actuelle = Column(
        String(50),
        default='wordpress_woo',
        comment='wordpress_woo, wordpress_simple, prestashop, shopify, google_sites, html_statique, autre'
    )
    plateforme_cible = Column(
        String(50),
        comment='identique, wordpress_woo, github_pages, html_statique'
    )
    type_site = Column(
        String(50),
        comment='landing_page, vitrine, ecommerce, blog_vitrine'
    )
    budget_hebergement = Column(Boolean, default=True, comment='1=oui, 0=non')
    archive = Column(Boolean, default=False, comment='1=archivé')
    code_source_existant = Column(Text, comment='Code HTML source existant pour amélioration')
    
    # New: type offre (fusion clients_site_web_75k)
    type_offre = Column(
        Enum('essentielle', 'croissance', 'acceleration', 'site_75k', name='type_offre'),
        default='essentielle',
        index=True
    )


class Production(Base):
    """
    Website production pipeline (existing table).
    Used by website_generator module.
    """
    __tablename__ = "productions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    candidat_id = Column(Integer, ForeignKey('candidats.id'), nullable=False)
    livrable_id = Column(Integer)
    type = Column(Enum('landing', 'vitrine', 'boutique', 'vitrine_boutique', name='production_type'))
    statut = Column(
        Enum('brief_valide', 'elements_collectes', 'en_production', 'a_valider', 'livre', name='production_statut'),
        default='brief_valide',
        index=True
    )
    elements = Column(Text, comment='JSON field')  # JSON valid check in MySQL
    contenu = Column(Text)
    contenu_impression = Column(Text)
    signe_le = Column(DateTime)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())


class Diagnostic(Base):
    """
    Client diagnostics (existing table).
    """
    __tablename__ = "diagnostics"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    candidat_id = Column(Integer, ForeignKey('candidats.id'), nullable=False)
    reponses = Column(Text, comment='JSON field')
    score_final = Column(Integer)
    recommendations = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


class Alerte(Base):
    """
    Alerts (Meta Ads, thresholds, etc.) (existing table).
    """
    __tablename__ = "alertes"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    candidat_id = Column(Integer, ForeignKey('candidats.id'), nullable=False)
    type = Column(String(50))
    label = Column(String(255))
    valeur_actuelle = Column(Numeric(10, 2))
    seuil = Column(Numeric(10, 2))
    ecart = Column(Numeric(10, 2))
    gravite = Column(Enum('attention', 'critique', name='gravite'), default='attention')
    mois = Column(String(7))  # Format: YYYY-MM
    lue = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())


# ============================================================
# FORMATIONS
# ============================================================

class FormationInscrit(Base):
    """
    Formation enrollments (existing table).
    Now linked to users table for auth.
    """
    __tablename__ = "formation_inscrits"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    nom = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    telephone = Column(String(50))
    formation = Column(String(255))
    statut = Column(String(50))
    date_inscription = Column(DateTime, default=datetime.now)
    
    # New: link to unified auth (to be added via migration)
    # user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=True)
    
    # Relationships (commented until user_id column exists)
    # user = relationship("User", back_populates="formation_inscrit")


# ============================================================
# NEW TABLES — Unified System
# ============================================================

class AIGeneration(Base):
    """
    Track all AI generations (text, image, website).
    Used for analytics, cost tracking, and debugging.
    """
    __tablename__ = "ai_generations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=True)  # Nullable, no FK (add later with migration)
    type = Column(Enum('text', 'image', 'website', name='generation_type'), nullable=False)
    provider = Column(String(50), nullable=False)  # claude, deepseek, glm, dalle3
    model = Column(String(100))
    prompt = Column(Text)
    result = Column(Text)
    cost_usd = Column(Numeric(10, 6))
    duration_seconds = Column(Numeric(10, 2))
    tokens_input = Column(Integer)
    tokens_output = Column(Integer)
    success = Column(Boolean, default=True)
    error_message = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)
    
    __table_args__ = (
        Index('idx_client_type', 'client_id', 'type'),
        Index('idx_provider', 'provider'),
        Index('idx_created_at', 'created_at'),
    )


class Project(Base):
    """
    Website projects (new unified structure).
    Replaces/extends productions table with modern workflow.
    """
    __tablename__ = "projects"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, nullable=False)  # Nullable, no FK (add later with migration)
    domain = Column(String(255), unique=True)
    status = Column(
        Enum('draft', 'brief', 'production', 'validation', 'deployed', name='project_status'),
        default='draft',
        nullable=False,
        index=True
    )
    brief_data = Column(Text, comment='JSON field - percepteur output')
    strategy_data = Column(Text, comment='JSON field - stratege output')
    deployed_url = Column(String(500))
    deployed_at = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class ProspectsTracking(Base):
    """
    Prospects follow-up automation (replaces CSV).
    Used by campaigns/sequences module (WhatsApp J+0/J+3/J+7).
    """
    __tablename__ = "prospects_tracking"
    
    id = Column(String(20), primary_key=True)  # Format: YYMMDD-UUID
    nom = Column(String(255))
    telephone = Column(String(20), unique=True, nullable=False, index=True)
    statut = Column(
        Enum(
            'Nouveau', 'Contacté_J0', 'Relancé_J3', 'Relancé_J7',
            'Répondu_Positif', 'Répondu_Négatif', 'En_Accompagnement',
            'Abandonné', 'Stoppé_Manuellement',
            name='prospect_statut'
        ),
        default='Nouveau',
        nullable=False,
        index=True
    )
    date_contact = Column(DateTime, index=True)
    date_relance_j3 = Column(DateTime)
    date_relance_j7 = Column(DateTime)
    nombre_contacts = Column(Integer, default=0)
    derniere_reponse = Column(Text)
    stop_raison = Column(String(255))
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())


# ============================================================
# CHATBOT MODELS MOVED TO backend/chatbot/models.py
# ============================================================
# Old simple models replaced by complete Phase 1-S1.4 architecture
# See: backend/chatbot/models.py for ChatbotSite, ChatbotConversation, 
#      ChatbotMessage, ChatbotLead, ChatbotAnalytics (6 tables total)
# ============================================================

# class ChatbotLead(Base):
#     """DEPRECATED - Use backend/chatbot/models.py instead"""
#     __tablename__ = "chatbot_leads"
#     ...

# class ChatbotConfig(Base):
#     """DEPRECATED - Use backend/chatbot/models.py ChatbotSite instead"""
#     __tablename__ = "chatbot_configs"
#     ...


class PublicationState(Base):
    """
    Social media publications state (replaces JSON file).
    Used by content_creator/publisher module.
    """
    __tablename__ = "publications_state"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    publication_id = Column(String(100), unique=True, nullable=False)
    platform = Column(String(50), nullable=False, index=True)  # facebook, instagram, linkedin, tiktok, whatsapp
    status = Column(
        Enum('draft', 'scheduled', 'published', 'failed', name='publication_status'),
        default='draft',
        nullable=False,
        index=True
    )
    scheduled_at = Column(DateTime, index=True)
    published_at = Column(DateTime)
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())


class CacheEntry(Base):
    """
    Generic file-based cache (replaces Redis).
    Used by core/cache module.
    """
    __tablename__ = "cache_entries"
    
    cache_key = Column(String(255), primary_key=True)
    cache_value = Column(Text, nullable=False)
    expires_at = Column(TIMESTAMP, index=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())


# ============================================================
# Indexes for performance
# ============================================================

# Additional indexes are defined in __table_args__ above
# For existing tables, create indexes via Alembic migrations

if __name__ == "__main__":
    """Show models summary when run directly."""
    from sqlalchemy import inspect


# ============================================================
# SUBSCRIPTIONS — Phase 1-S1
# ============================================================

# NOTE: Subscription and Product models moved to models_legacy.py
# to match existing ePerformance table structures.
# Keeping these definitions commented for reference.

# class Subscription(Base):
#     """
#     Subscriptions to ePerformance products/plans.
#     
#     States flow:
#     - pending → active (payment confirmed)
#     - active → cancelled (user cancels)
#     - active → expired (payment failed or end date reached)
#     - cancelled → active (user reactivates)
#     
#     Agents: public-apis (payment APIs), ruflo (workflows), deer-flow (state orchestration)
#     """
# #     __tablename__ = "subscriptions_new"  # Would conflict with existing table
#     
#     id = Column(Integer, primary_key=True, autoincrement=True)
#     user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
#     ... (rest of definition)


# class Product(Base):
#     """
#     Products catalog — Phase 1-S1.2
#     Will be implemented after Subscriptions
#     """
#     __tablename__ = "products_new"  # Would conflict with existing table
#     
#     id = Column(Integer, primary_key=True, autoincrement=True)
#     ... (rest of definition)

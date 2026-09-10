"""
Legacy models mapping to existing ePerformance tables.
These models map to tables that already exist with specific structures.
"""

from sqlalchemy import (
    Column, Integer, String, Text, Date, Boolean, 
    Enum, ForeignKey, TIMESTAMP, Numeric
)
from sqlalchemy.orm import relationship
from datetime import datetime, date
from backend.core.database import Base


class SubscriptionLegacy(Base):
    """
    Maps to existing subscriptions table from ePerformance.
    Used for accompagnement and module_standalone subscriptions.
    """
    __tablename__ = "subscriptions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    candidat_id = Column(Integer, nullable=True, index=True)
    
    # Type and level
    type = Column(Enum('accompagnement', 'module_standalone', name='subscription_type'), 
                  nullable=False)
    niveau = Column(Enum('essentielle', 'croissance', 'acceleration', name='subscription_niveau'), 
                    nullable=True)
    
    # Billing
    montant_mensuel = Column(Numeric(10, 2), nullable=False)
    devise = Column(String(3), nullable=True, default='XOF')
    engagement_mois = Column(Integer, nullable=False)
    
    # Dates
    date_debut = Column(Date, nullable=False)
    date_fin = Column(Date, nullable=False)
    prochaine_facturation = Column(Date, nullable=True, index=True)
    derniere_facturation = Column(Date, nullable=True)
    
    # Status
    statut = Column(Enum('active', 'paused', 'cancelled', 'expired', name='subscription_statut'), 
                    nullable=True, default='active')
    
    # Renewal
    auto_renew = Column(Boolean, default=False, nullable=True)
    facturation_jour = Column(Integer, nullable=True, default=1)
    
    # Cancellation
    cancelled_at = Column(TIMESTAMP, nullable=True)
    cancellation_reason = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(TIMESTAMP, nullable=True)
    updated_at = Column(TIMESTAMP, nullable=True)
    
    # Relationships
    user = relationship("User", backref="legacy_subscriptions")
    
    def __repr__(self):
        return f"<SubscriptionLegacy(id={self.id}, type={self.type}, statut={self.statut})>"
    
    def is_active(self):
        """Check if subscription is currently active"""
        return self.statut == 'active'
    
    def days_remaining(self):
        """Calculate days remaining until end date"""
        if not self.date_fin:
            return None
        
        today = date.today()
        delta = self.date_fin - today
        return delta.days if delta.days > 0 else 0


class ProductLegacy(Base):
    """
    Maps to existing products table from ePerformance.
    Catalog of sites, modules, formations, and services.
    """
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(100), unique=True, nullable=False)
    nom = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Product type
    type = Column(Enum('site_web', 'module', 'formation', 'service', name='product_type'), 
                  nullable=False, index=True)
    category = Column(String(50), nullable=True)
    
    # Pricing
    prix_unitaire = Column(Numeric(10, 2), nullable=False)
    devise = Column(String(3), nullable=True, default='XOF')
    billing_type = Column(Enum('one_time', 'monthly', 'yearly', name='billing_type'), 
                         nullable=False)
    
    # Features and quotas
    features_json = Column(Text, nullable=True)  # JSON string
    quota_mensuel = Column(Text, nullable=True)  # JSON string
    
    # Status
    is_active = Column(Boolean, nullable=True, default=True)
    is_visible = Column(Boolean, nullable=True, default=True)
    requires_approval = Column(Boolean, nullable=True, default=False)
    
    # Timestamps
    created_at = Column(TIMESTAMP, nullable=True)
    updated_at = Column(TIMESTAMP, nullable=True)
    
    def __repr__(self):
        return f"<ProductLegacy(id={self.id}, nom={self.nom}, type={self.type})>"

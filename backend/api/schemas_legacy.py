"""
Pydantic schemas for legacy ePerformance tables.
These schemas map to existing table structures.
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime, date
from enum import Enum


# ============================================================
# SUBSCRIPTION LEGACY SCHEMAS
# ============================================================

class SubscriptionTypeEnum(str, Enum):
    accompagnement = "accompagnement"
    module_standalone = "module_standalone"


class SubscriptionNiveauEnum(str, Enum):
    essentielle = "essentielle"
    croissance = "croissance"
    acceleration = "acceleration"


class SubscriptionStatutEnum(str, Enum):
    active = "active"
    paused = "paused"
    cancelled = "cancelled"
    expired = "expired"


class SubscriptionLegacyCreate(BaseModel):
    """Schema for creating a new subscription (legacy format)"""
    user_id: int
    candidat_id: Optional[int] = None
    type: SubscriptionTypeEnum
    niveau: Optional[SubscriptionNiveauEnum] = None
    montant_mensuel: float = Field(..., gt=0, description="Monthly amount")
    devise: str = Field(default="XOF", max_length=3)
    engagement_mois: int = Field(..., gt=0, description="Commitment period in months")
    date_debut: date
    auto_renew: bool = False
    facturation_jour: int = Field(default=1, ge=1, le=28, description="Day of month for billing")


class SubscriptionLegacyUpdate(BaseModel):
    """Schema for updating a subscription (legacy format)"""
    statut: Optional[SubscriptionStatutEnum] = None
    niveau: Optional[SubscriptionNiveauEnum] = None
    montant_mensuel: Optional[float] = Field(None, gt=0)
    auto_renew: Optional[bool] = None
    prochaine_facturation: Optional[date] = None


class SubscriptionLegacyResponse(BaseModel):
    """Schema for subscription response (legacy format)"""
    id: int
    user_id: int
    candidat_id: Optional[int]
    type: str
    niveau: Optional[str]
    montant_mensuel: float
    devise: str
    engagement_mois: int
    date_debut: date
    date_fin: date
    prochaine_facturation: Optional[date]
    derniere_facturation: Optional[date]
    statut: str
    auto_renew: bool
    facturation_jour: int
    cancelled_at: Optional[datetime]
    cancellation_reason: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    
    # Computed fields
    is_active: bool = Field(default=False)
    days_remaining: Optional[int] = None
    
    class Config:
        from_attributes = True


class SubscriptionLegacyList(BaseModel):
    """Schema for paginated list of subscriptions"""
    total: int
    page: int
    page_size: int
    subscriptions: List[SubscriptionLegacyResponse]


class SubscriptionCancelRequest(BaseModel):
    """Schema for cancelling a subscription"""
    reason: Optional[str] = Field(None, max_length=500, description="Reason for cancellation")
    cancel_immediately: bool = Field(default=False, description="Cancel now vs at end of period")


# ============================================================
# PRODUCT LEGACY SCHEMAS
# ============================================================

class ProductTypeEnum(str, Enum):
    site_web = "site_web"
    module = "module"
    formation = "formation"
    service = "service"


class BillingTypeEnum(str, Enum):
    one_time = "one_time"
    monthly = "monthly"
    yearly = "yearly"


class ProductLegacyCreate(BaseModel):
    """Schema for creating a new product (legacy format)"""
    slug: str = Field(..., max_length=100)
    nom: str = Field(..., max_length=255)
    description: Optional[str] = None
    type: ProductTypeEnum
    category: Optional[str] = Field(None, max_length=50)
    prix_unitaire: float = Field(..., gt=0)
    devise: str = Field(default="XOF", max_length=3)
    billing_type: BillingTypeEnum
    features_json: Optional[str] = None
    quota_mensuel: Optional[str] = None
    is_active: bool = True
    is_visible: bool = True
    requires_approval: bool = False


class ProductLegacyUpdate(BaseModel):
    """Schema for updating a product (legacy format)"""
    nom: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    prix_unitaire: Optional[float] = Field(None, gt=0)
    billing_type: Optional[BillingTypeEnum] = None
    features_json: Optional[str] = None
    quota_mensuel: Optional[str] = None
    is_active: Optional[bool] = None
    is_visible: Optional[bool] = None
    requires_approval: Optional[bool] = None


class ProductLegacyResponse(BaseModel):
    """Schema for product response (legacy format)"""
    id: int
    slug: str
    nom: str
    description: Optional[str]
    type: str
    category: Optional[str]
    prix_unitaire: float
    devise: str
    billing_type: str
    features_json: Optional[str]
    quota_mensuel: Optional[str]
    is_active: bool
    is_visible: bool
    requires_approval: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class ProductLegacyList(BaseModel):
    """Schema for paginated list of products"""
    total: int
    page: int
    page_size: int
    products: List[ProductLegacyResponse]

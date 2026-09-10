"""
Pydantic schemas for request/response validation.
ePerformance API Flow unified system.
"""

from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List
from datetime import datetime
from enum import Enum


# ============================================================
# ENUMS
# ============================================================

class UserRoleEnum(str, Enum):
    admin = "admin"
    client = "client"
    apprenant = "apprenant"
    lead = "lead"


class CandidatStatutEnum(str, Enum):
    en_attente = "en_attente"
    accepte = "accepte"
    refuse = "refuse"
    alumni = "alumni"


class NiveauAccompagnementEnum(str, Enum):
    essentielle = "essentielle"
    croissance = "croissance"
    acceleration = "acceleration"


class NiveauRisqueEnum(str, Enum):
    stable = "stable"
    attention = "attention"
    critique = "critique"


# ============================================================
# AUTH SCHEMAS
# ============================================================

class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    role: UserRoleEnum = UserRoleEnum.lead


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 86400  # 24 hours


class UserResponse(BaseModel):
    id: int
    email: str
    role: str
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime]

    class Config:
        from_attributes = True


# ============================================================
# CANDIDAT SCHEMAS (ePerformance Pulse CRM)
# ============================================================

class CandidatBase(BaseModel):
    """Base schema for Candidat (shared fields)"""
    nom: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    whatsapp: Optional[str] = Field(None, max_length=50)
    entreprise: Optional[str] = Field(None, max_length=255)
    secteur: Optional[str] = Field(None, max_length=100)
    niveau_accompagnement: NiveauAccompagnementEnum = NiveauAccompagnementEnum.essentielle
    
    @validator('whatsapp')
    def validate_whatsapp(cls, v):
        if v and not v.startswith('+'):
            return f'+{v}'
        return v


class CandidatCreate(CandidatBase):
    """Schema for creating a new candidat"""
    statut: CandidatStatutEnum = CandidatStatutEnum.en_attente
    mlm_actif: bool = False
    ref_parrainage: Optional[str] = None
    parrain_id: Optional[int] = None


class CandidatUpdate(BaseModel):
    """Schema for updating candidat (all fields optional)"""
    nom: Optional[str] = Field(None, min_length=2, max_length=255)
    email: Optional[EmailStr] = None
    whatsapp: Optional[str] = None
    entreprise: Optional[str] = None
    secteur: Optional[str] = None
    niveau_accompagnement: Optional[NiveauAccompagnementEnum] = None
    statut: Optional[CandidatStatutEnum] = None
    mlm_actif: Optional[bool] = None
    score: Optional[int] = Field(None, ge=0, le=100)
    
    @validator('whatsapp')
    def validate_whatsapp(cls, v):
        if v and not v.startswith('+'):
            return f'+{v}'
        return v


class CandidatResponse(CandidatBase):
    """Schema for candidat response"""
    id: int
    score: int
    statut: str
    mlm_actif: bool
    ref_parrainage: Optional[str]
    parrain_id: Optional[int]
    nb_parrainages: int
    score_risque: int
    niveau_risque: str
    compte_active: bool
    created_at: datetime
    date_acceptation: Optional[datetime]
    derniere_connexion: Optional[datetime]
    risque_updated_at: Optional[datetime]
    alumni_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class CandidatList(BaseModel):
    """Schema for paginated list of candidats"""
    total: int
    page: int
    page_size: int
    candidats: List[CandidatResponse]


class CandidatStatutUpdate(BaseModel):
    """Schema for updating candidat status"""
    statut: CandidatStatutEnum


class CandidatScoreResponse(BaseModel):
    """Schema for candidat score calculation"""
    candidat_id: int
    score: int
    score_risque: int
    niveau_risque: str
    details: dict
    
    class Config:
        from_attributes = True


# ============================================================
# CLIENT WEB SCHEMAS
# ============================================================

class ClientWebBase(BaseModel):
    """Base schema for ClientWeb"""
    nom: str = Field(..., min_length=2, max_length=200)
    email: EmailStr
    site_web: Optional[str] = Field(None, max_length=300)
    telephone: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = None


class ClientWebCreate(ClientWebBase):
    """Schema for creating new client web"""
    pass


class ClientWebUpdate(BaseModel):
    """Schema for updating client web (all optional)"""
    nom: Optional[str] = Field(None, min_length=2, max_length=200)
    email: Optional[EmailStr] = None
    site_web: Optional[str] = None
    telephone: Optional[str] = None
    notes: Optional[str] = None


class ClientWebResponse(ClientWebBase):
    """Schema for client web response"""
    id: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class ClientWebList(BaseModel):
    """Schema for paginated list of clients web"""
    total: int
    page: int
    page_size: int
    clients: List[ClientWebResponse]


# ============================================================
# HEALTH CHECK SCHEMAS
# ============================================================

class HealthResponse(BaseModel):
    """Schema for health check response"""
    status: str
    database: str
    version: str = "1.0.0"


# ============================================================
# SUBSCRIPTION SCHEMAS — Phase 1-S1
# ============================================================

class SubscriptionPlanEnum(str, Enum):
    starter = "starter"
    pro = "pro"
    enterprise = "enterprise"
    custom = "custom"


class SubscriptionStatusEnum(str, Enum):
    pending = "pending"
    active = "active"
    cancelled = "cancelled"
    expired = "expired"


class BillingCycleEnum(str, Enum):
    monthly = "monthly"
    quarterly = "quarterly"
    yearly = "yearly"


class SubscriptionCreate(BaseModel):
    """Schema for creating a new subscription"""
    user_id: int
    product_id: Optional[int] = None
    plan_type: SubscriptionPlanEnum = SubscriptionPlanEnum.starter
    billing_cycle: BillingCycleEnum = BillingCycleEnum.monthly
    price: float = Field(..., gt=0, description="Price in currency units")
    currency: str = Field(default="XOF", max_length=3)
    auto_renew: bool = True
    trial_ends_at: Optional[datetime] = None
    notes: Optional[str] = None


class SubscriptionUpdate(BaseModel):
    """Schema for updating a subscription"""
    plan_type: Optional[SubscriptionPlanEnum] = None
    status: Optional[SubscriptionStatusEnum] = None
    billing_cycle: Optional[BillingCycleEnum] = None
    price: Optional[float] = Field(None, gt=0)
    auto_renew: Optional[bool] = None
    end_date: Optional[datetime] = None
    notes: Optional[str] = None


class SubscriptionResponse(BaseModel):
    """Schema for subscription response"""
    id: int
    user_id: int
    product_id: Optional[int]
    plan_type: str
    status: str
    billing_cycle: str
    price: float
    currency: str
    start_date: datetime
    end_date: Optional[datetime]
    next_billing_date: Optional[datetime]
    cancelled_at: Optional[datetime]
    payment_provider: Optional[str]
    payment_provider_id: Optional[str]
    last_payment_date: Optional[datetime]
    last_payment_status: Optional[str]
    trial_ends_at: Optional[datetime]
    auto_renew: bool
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    # Computed fields
    is_active: bool = Field(default=False)
    days_remaining: Optional[int] = None
    
    class Config:
        from_attributes = True


class SubscriptionList(BaseModel):
    """Schema for paginated list of subscriptions"""
    total: int
    page: int
    page_size: int
    subscriptions: List[SubscriptionResponse]


class SubscriptionCancelRequest(BaseModel):
    """Schema for cancelling a subscription"""
    reason: Optional[str] = Field(None, max_length=500, description="Reason for cancellation")
    cancel_immediately: bool = Field(default=False, description="Cancel now vs at end of billing period")
    timestamp: datetime = Field(default_factory=datetime.now)

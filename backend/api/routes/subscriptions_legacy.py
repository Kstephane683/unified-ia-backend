"""
Subscription routes for legacy ePerformance subscriptions table.
REST API endpoints for subscription CRUD operations.
Phase 1-S1: Routes CRUD Subscriptions
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import Optional

from backend.core.database import get_db
from backend.core.models_legacy import SubscriptionLegacy
from backend.services.subscription_service_legacy import SubscriptionServiceLegacy
from backend.api.schemas_legacy import (
    SubscriptionLegacyCreate,
    SubscriptionLegacyUpdate,
    SubscriptionLegacyResponse,
    SubscriptionLegacyList,
    SubscriptionCancelRequest,
)


router = APIRouter(prefix="/api/subscriptions", tags=["Subscriptions"])


def _subscription_to_response(subscription: SubscriptionLegacy) -> SubscriptionLegacyResponse:
    """Helper to convert SQLAlchemy model to Pydantic response with computed fields"""
    return SubscriptionLegacyResponse(
        id=subscription.id,
        user_id=subscription.user_id,
        candidat_id=subscription.candidat_id,
        type=subscription.type,
        niveau=subscription.niveau,
        montant_mensuel=float(subscription.montant_mensuel),
        devise=subscription.devise,
        engagement_mois=subscription.engagement_mois,
        date_debut=subscription.date_debut,
        date_fin=subscription.date_fin,
        prochaine_facturation=subscription.prochaine_facturation,
        derniere_facturation=subscription.derniere_facturation,
        statut=subscription.statut,
        auto_renew=subscription.auto_renew,
        facturation_jour=subscription.facturation_jour,
        cancelled_at=subscription.cancelled_at,
        cancellation_reason=subscription.cancellation_reason,
        created_at=subscription.created_at,
        updated_at=subscription.updated_at,
        is_active=subscription.is_active(),
        days_remaining=subscription.days_remaining()
    )



@router.post("", response_model=SubscriptionLegacyResponse, status_code=status.HTTP_201_CREATED)
def create_subscription(
    data: SubscriptionLegacyCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new subscription.
    
    - **user_id**: User ID (required)
    - **type**: accompagnement or module_standalone
    - **niveau**: essentielle, croissance, or acceleration (for accompagnement)
    - **montant_mensuel**: Monthly amount in currency
    - **engagement_mois**: Commitment period in months
    - **date_debut**: Start date
    """
    subscription = SubscriptionServiceLegacy.create_subscription(db, data)
    return _subscription_to_response(subscription)


@router.get("/{subscription_id}", response_model=SubscriptionLegacyResponse)
def get_subscription(
    subscription_id: int,
    db: Session = Depends(get_db)
):
    """
    Get a subscription by ID.
    """
    subscription = SubscriptionServiceLegacy.get_subscription(db, subscription_id)
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subscription {subscription_id} not found"
        )
    
    return _subscription_to_response(subscription)


@router.get("/user/{user_id}", response_model=SubscriptionLegacyList)
def get_user_subscriptions(
    user_id: int,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    statut: Optional[str] = Query(None, description="Filter by status"),
    db: Session = Depends(get_db)
):
    """
    Get all subscriptions for a specific user.
    
    Supports pagination and filtering by status.
    """
    skip = (page - 1) * page_size
    
    subscriptions, total = SubscriptionServiceLegacy.get_user_subscriptions(
        db, user_id, skip=skip, limit=page_size, statut=statut
    )
    
    # Convert to response objects
    subscription_responses = [_subscription_to_response(sub) for sub in subscriptions]
    
    return SubscriptionLegacyList(
        total=total,
        page=page,
        page_size=page_size,
        subscriptions=subscription_responses
    )


@router.get("", response_model=SubscriptionLegacyList)
def list_subscriptions(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    statut: Optional[str] = Query(None, description="Filter by status"),
    type: Optional[str] = Query(None, description="Filter by type"),
    niveau: Optional[str] = Query(None, description="Filter by niveau"),
    db: Session = Depends(get_db)
):
    """
    List all subscriptions (admin function).
    
    Supports pagination and filtering by status, type, and niveau.
    """
    skip = (page - 1) * page_size
    
    subscriptions, total = SubscriptionServiceLegacy.list_subscriptions(
        db, skip=skip, limit=page_size, statut=statut, type=type, niveau=niveau
    )
    
    # Add computed fields to each subscription
    subscription_responses = []
    for sub in subscriptions:
        response = _subscription_to_response(sub)
        
        
        subscription_responses.append(response)
    
    return SubscriptionLegacyList(
        total=total,
        page=page,
        page_size=page_size,
        subscriptions=subscription_responses
    )


@router.patch("/{subscription_id}", response_model=SubscriptionLegacyResponse)
def update_subscription(
    subscription_id: int,
    data: SubscriptionLegacyUpdate,
    db: Session = Depends(get_db)
):
    """
    Update a subscription.
    
    Can update: statut, niveau, montant_mensuel, auto_renew, prochaine_facturation
    """
    subscription = SubscriptionServiceLegacy.update_subscription(db, subscription_id, data)
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subscription {subscription_id} not found"
        )
    
    return _subscription_to_response(subscription)


@router.post("/{subscription_id}/cancel", response_model=SubscriptionLegacyResponse)
def cancel_subscription(
    subscription_id: int,
    request: SubscriptionCancelRequest,
    db: Session = Depends(get_db)
):
    """
    Cancel a subscription.
    
    - **cancel_immediately**: If true, cancels immediately. If false, cancels at end of period.
    - **reason**: Optional cancellation reason
    """
    subscription = SubscriptionServiceLegacy.cancel_subscription(db, subscription_id, request)
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subscription {subscription_id} not found"
        )
    
    return _subscription_to_response(subscription)


@router.post("/{subscription_id}/activate", response_model=SubscriptionLegacyResponse)
def activate_subscription(
    subscription_id: int,
    db: Session = Depends(get_db)
):
    """
    Activate a subscription (called after payment confirmation).
    
    Updates status to 'active' and records payment date.
    """
    subscription = SubscriptionServiceLegacy.activate_subscription(db, subscription_id)
    
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subscription {subscription_id} not found"
        )
    
    return _subscription_to_response(subscription)


@router.get("/expiring/soon", response_model=SubscriptionLegacyList)
def get_expiring_subscriptions(
    days_ahead: int = Query(7, ge=1, le=30, description="Days to look ahead"),
    db: Session = Depends(get_db)
):
    """
    Get subscriptions expiring within specified days.
    
    Used for sending renewal notifications.
    """
    subscriptions = SubscriptionServiceLegacy.get_expiring_subscriptions(db, days_ahead)
    
    # Add computed fields to each subscription
    subscription_responses = []
    for sub in subscriptions:
        response = _subscription_to_response(sub)
        
        
        subscription_responses.append(response)
    
    return SubscriptionLegacyList(
        total=len(subscription_responses),
        page=1,
        page_size=len(subscription_responses),
        subscriptions=subscription_responses
    )

"""
Subscription routes - REST API endpoints for subscription management.
Phase 1-S1 - ePerformance API Flow unified system.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from backend.core.database import get_db
from backend.api.schemas import (
    SubscriptionCreate, SubscriptionUpdate, SubscriptionCancelRequest,
    SubscriptionResponse, SubscriptionList
)
from backend.services.subscription_service import SubscriptionService

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


@router.post("", response_model=SubscriptionResponse, status_code=201)
def create_subscription(
    data: SubscriptionCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new subscription.
    
    Workflow:
    1. Validate user exists
    2. Create subscription with status=pending
    3. Return subscription (client proceeds to payment)
    4. Payment webhook will activate the subscription
    
    Example:
    ```json
    {
      "user_id": 1,
      "plan_type": "pro",
      "billing_cycle": "monthly",
      "price": 50000,
      "currency": "XOF",
      "auto_renew": true
    }
    ```
    """
    try:
        subscription = SubscriptionService.create_subscription(db, data)
        
        # Add computed fields
        response = SubscriptionResponse.model_validate(subscription)
        response.is_active = subscription.is_active()
        response.days_remaining = subscription.days_remaining()
        
        return response
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.get("/{subscription_id}", response_model=SubscriptionResponse)
def get_subscription(
    subscription_id: int,
    db: Session = Depends(get_db)
):
    """
    Get subscription details by ID.
    """
    subscription = SubscriptionService.get_subscription(db, subscription_id)
    
    if not subscription:
        raise HTTPException(status_code=404, detail=f"Subscription {subscription_id} not found")
    
    # Add computed fields
    response = SubscriptionResponse.model_validate(subscription)
    response.is_active = subscription.is_active()
    response.days_remaining = subscription.days_remaining()
    
    return response


@router.get("/user/{user_id}", response_model=SubscriptionList)
def get_user_subscriptions(
    user_id: int,
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db)
):
    """
    Get all subscriptions for a user.
    
    Query params:
    - status: Filter by status (pending, active, cancelled, expired)
    - page: Page number (default: 1)
    - page_size: Items per page (default: 10, max: 100)
    """
    subscriptions, total = SubscriptionService.get_user_subscriptions(
        db, user_id, status, page, page_size
    )
    
    # Add computed fields
    subscription_responses = []
    for sub in subscriptions:
        response = SubscriptionResponse.model_validate(sub)
        response.is_active = sub.is_active()
        response.days_remaining = sub.days_remaining()
        subscription_responses.append(response)
    
    return SubscriptionList(
        total=total,
        page=page,
        page_size=page_size,
        subscriptions=subscription_responses
    )


@router.get("", response_model=SubscriptionList)
def list_subscriptions(
    status: Optional[str] = Query(None, description="Filter by status"),
    plan_type: Optional[str] = Query(None, description="Filter by plan type"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db)
):
    """
    List all subscriptions (admin use).
    
    Query params:
    - status: Filter by status
    - plan_type: Filter by plan type (starter, pro, enterprise, custom)
    - page: Page number (default: 1)
    - page_size: Items per page (default: 20, max: 100)
    """
    subscriptions, total = SubscriptionService.list_subscriptions(
        db, status, plan_type, page, page_size
    )
    
    # Add computed fields
    subscription_responses = []
    for sub in subscriptions:
        response = SubscriptionResponse.model_validate(sub)
        response.is_active = sub.is_active()
        response.days_remaining = sub.days_remaining()
        subscription_responses.append(response)
    
    return SubscriptionList(
        total=total,
        page=page,
        page_size=page_size,
        subscriptions=subscription_responses
    )


@router.patch("/{subscription_id}", response_model=SubscriptionResponse)
def update_subscription(
    subscription_id: int,
    data: SubscriptionUpdate,
    db: Session = Depends(get_db)
):
    """
    Update subscription details.
    
    Allowed updates:
    - plan_type: Change plan
    - status: Change status (admin only)
    - billing_cycle: Change billing frequency
    - price: Update price
    - auto_renew: Enable/disable auto-renewal
    - end_date: Set end date
    - notes: Add notes
    
    Example:
    ```json
    {
      "plan_type": "enterprise",
      "price": 150000,
      "auto_renew": true
    }
    ```
    """
    try:
        subscription = SubscriptionService.update_subscription(db, subscription_id, data)
        
        if not subscription:
            raise HTTPException(status_code=404, detail=f"Subscription {subscription_id} not found")
        
        # Add computed fields
        response = SubscriptionResponse.model_validate(subscription)
        response.is_active = subscription.is_active()
        response.days_remaining = subscription.days_remaining()
        
        return response
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.post("/{subscription_id}/cancel", response_model=SubscriptionResponse)
def cancel_subscription(
    subscription_id: int,
    cancel_request: SubscriptionCancelRequest,
    db: Session = Depends(get_db)
):
    """
    Cancel a subscription.
    
    Options:
    - cancel_immediately: Cancel now (default: false = cancel at end of period)
    - reason: Optional cancellation reason
    
    Example:
    ```json
    {
      "reason": "Switching to annual plan",
      "cancel_immediately": false
    }
    ```
    """
    try:
        subscription = SubscriptionService.cancel_subscription(
            db, subscription_id, cancel_request
        )
        
        if not subscription:
            raise HTTPException(status_code=404, detail=f"Subscription {subscription_id} not found")
        
        # Add computed fields
        response = SubscriptionResponse.model_validate(subscription)
        response.is_active = subscription.is_active()
        response.days_remaining = subscription.days_remaining()
        
        return response
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.post("/{subscription_id}/activate", response_model=SubscriptionResponse)
def activate_subscription(
    subscription_id: int,
    payment_provider: str = Query(..., description="Payment provider (stripe, paypal, etc.)"),
    payment_provider_id: str = Query(..., description="External subscription ID"),
    db: Session = Depends(get_db)
):
    """
    Activate a subscription after payment confirmation.
    
    Called by payment webhook handler.
    Transitions subscription from pending → active.
    
    Query params:
    - payment_provider: stripe, paypal, mtn_momo, orange_money
    - payment_provider_id: External subscription ID from provider
    """
    subscription = SubscriptionService.activate_subscription(
        db, subscription_id, payment_provider, payment_provider_id
    )
    
    if not subscription:
        raise HTTPException(status_code=404, detail=f"Subscription {subscription_id} not found")
    
    # Add computed fields
    response = SubscriptionResponse.model_validate(subscription)
    response.is_active = subscription.is_active()
    response.days_remaining = subscription.days_remaining()
    
    return response


@router.get("/expiring/soon", response_model=SubscriptionList)
def get_expiring_subscriptions(
    days: int = Query(7, ge=1, le=30, description="Days threshold"),
    db: Session = Depends(get_db)
):
    """
    Get subscriptions expiring soon (for notifications).
    
    Query params:
    - days: Number of days threshold (default: 7, max: 30)
    
    Returns subscriptions expiring within the threshold period.
    """
    subscriptions = SubscriptionService.get_expiring_subscriptions(db, days)
    
    # Add computed fields
    subscription_responses = []
    for sub in subscriptions:
        response = SubscriptionResponse.model_validate(sub)
        response.is_active = sub.is_active()
        response.days_remaining = sub.days_remaining()
        subscription_responses.append(response)
    
    return SubscriptionList(
        total=len(subscriptions),
        page=1,
        page_size=len(subscriptions),
        subscriptions=subscription_responses
    )

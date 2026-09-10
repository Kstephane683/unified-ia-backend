"""
Subscription service - Business logic for subscriptions management.
Phase 1-S1 - ePerformance API Flow unified system.

Agents: public-apis, ruflo, deer-flow
"""

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from backend.core.models import Subscription, User
from backend.api.schemas import (
    SubscriptionCreate, SubscriptionUpdate, SubscriptionCancelRequest,
    SubscriptionResponse
)


class SubscriptionService:
    """Service for managing subscriptions"""
    
    @staticmethod
    def create_subscription(db: Session, data: SubscriptionCreate) -> Subscription:
        """
        Create a new subscription.
        
        Workflow (inspired by ruflo):
        1. Validate user exists
        2. Create subscription with status=pending
        3. Calculate next_billing_date based on billing_cycle
        4. Return subscription (payment flow will activate it)
        """
        # Validate user exists
        user = db.query(User).filter(User.id == data.user_id).first()
        if not user:
            raise ValueError(f"User with id {data.user_id} not found")
        
        # Calculate next billing date
        if data.billing_cycle == "monthly":
            next_billing = datetime.now() + timedelta(days=30)
        elif data.billing_cycle == "quarterly":
            next_billing = datetime.now() + timedelta(days=90)
        elif data.billing_cycle == "yearly":
            next_billing = datetime.now() + timedelta(days=365)
        else:
            next_billing = datetime.now() + timedelta(days=30)
        
        # Create subscription
        subscription = Subscription(
            user_id=data.user_id,
            product_id=data.product_id,
            plan_type=data.plan_type,
            status="pending",  # Will be activated after payment
            billing_cycle=data.billing_cycle,
            price=data.price,
            currency=data.currency,
            start_date=datetime.now(),
            next_billing_date=next_billing,
            auto_renew=data.auto_renew,
            trial_ends_at=data.trial_ends_at,
            notes=data.notes
        )
        
        db.add(subscription)
        db.commit()
        db.refresh(subscription)
        
        return subscription
    
    @staticmethod
    def get_subscription(db: Session, subscription_id: int) -> Optional[Subscription]:
        """Get subscription by ID"""
        return db.query(Subscription).filter(Subscription.id == subscription_id).first()
    
    @staticmethod
    def get_user_subscriptions(
        db: Session, 
        user_id: int,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 10
    ) -> Tuple[List[Subscription], int]:
        """
        Get subscriptions for a user with pagination.
        
        Args:
            db: Database session
            user_id: User ID
            status: Filter by status (optional)
            page: Page number (1-indexed)
            page_size: Items per page
        
        Returns:
            Tuple of (subscriptions list, total count)
        """
        query = db.query(Subscription).filter(Subscription.user_id == user_id)
        
        if status:
            query = query.filter(Subscription.status == status)
        
        total = query.count()
        
        subscriptions = query.order_by(Subscription.created_at.desc()) \
            .offset((page - 1) * page_size) \
            .limit(page_size) \
            .all()
        
        return subscriptions, total
    
    @staticmethod
    def list_subscriptions(
        db: Session,
        status: Optional[str] = None,
        plan_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Tuple[List[Subscription], int]:
        """
        List all subscriptions with filters (admin use).
        
        Returns:
            Tuple of (subscriptions list, total count)
        """
        query = db.query(Subscription)
        
        if status:
            query = query.filter(Subscription.status == status)
        
        if plan_type:
            query = query.filter(Subscription.plan_type == plan_type)
        
        total = query.count()
        
        subscriptions = query.order_by(Subscription.created_at.desc()) \
            .offset((page - 1) * page_size) \
            .limit(page_size) \
            .all()
        
        return subscriptions, total
    
    @staticmethod
    def update_subscription(
        db: Session, 
        subscription_id: int, 
        data: SubscriptionUpdate
    ) -> Optional[Subscription]:
        """
        Update subscription details.
        
        State transitions (inspired by deer-flow):
        - pending → active (after payment)
        - active → cancelled (user cancels)
        - active → expired (payment failed)
        - cancelled → active (reactivation)
        """
        subscription = db.query(Subscription).filter(
            Subscription.id == subscription_id
        ).first()
        
        if not subscription:
            return None
        
        # Update fields
        if data.plan_type is not None:
            subscription.plan_type = data.plan_type
        
        if data.status is not None:
            subscription.status = data.status
            
            # Handle state transitions
            if data.status == "cancelled" and subscription.status != "cancelled":
                subscription.cancelled_at = datetime.now()
        
        if data.billing_cycle is not None:
            subscription.billing_cycle = data.billing_cycle
            
            # Recalculate next billing date
            if data.billing_cycle == "monthly":
                subscription.next_billing_date = datetime.now() + timedelta(days=30)
            elif data.billing_cycle == "quarterly":
                subscription.next_billing_date = datetime.now() + timedelta(days=90)
            elif data.billing_cycle == "yearly":
                subscription.next_billing_date = datetime.now() + timedelta(days=365)
        
        if data.price is not None:
            subscription.price = data.price
        
        if data.auto_renew is not None:
            subscription.auto_renew = data.auto_renew
        
        if data.end_date is not None:
            subscription.end_date = data.end_date
        
        if data.notes is not None:
            subscription.notes = data.notes
        
        subscription.updated_at = datetime.now()
        
        db.commit()
        db.refresh(subscription)
        
        return subscription
    
    @staticmethod
    def cancel_subscription(
        db: Session,
        subscription_id: int,
        cancel_request: SubscriptionCancelRequest
    ) -> Optional[Subscription]:
        """
        Cancel a subscription.
        
        Args:
            subscription_id: Subscription ID
            cancel_request: Cancellation details
        
        Returns:
            Updated subscription or None if not found
        """
        subscription = db.query(Subscription).filter(
            Subscription.id == subscription_id
        ).first()
        
        if not subscription:
            return None
        
        # Only active or pending subscriptions can be cancelled
        if subscription.status not in ["active", "pending"]:
            raise ValueError(f"Cannot cancel subscription with status: {subscription.status}")
        
        subscription.status = "cancelled"
        subscription.cancelled_at = datetime.now()
        
        # Add cancellation reason to notes
        if cancel_request.reason:
            reason_note = f"\n[CANCELLED {datetime.now().strftime('%Y-%m-%d')}] {cancel_request.reason}"
            subscription.notes = (subscription.notes or "") + reason_note
        
        # If immediate cancellation, set end_date to now
        if cancel_request.cancel_immediately:
            subscription.end_date = datetime.now()
            subscription.auto_renew = False
        else:
            # Cancel at end of billing period
            if subscription.next_billing_date:
                subscription.end_date = subscription.next_billing_date
            subscription.auto_renew = False
        
        subscription.updated_at = datetime.now()
        
        db.commit()
        db.refresh(subscription)
        
        return subscription
    
    @staticmethod
    def activate_subscription(
        db: Session,
        subscription_id: int,
        payment_provider: str,
        payment_provider_id: str
    ) -> Optional[Subscription]:
        """
        Activate a subscription after successful payment.
        Called by payment webhook handler.
        
        Args:
            subscription_id: Subscription ID
            payment_provider: Payment provider name (stripe, paypal, etc.)
            payment_provider_id: External subscription ID from provider
        """
        subscription = db.query(Subscription).filter(
            Subscription.id == subscription_id
        ).first()
        
        if not subscription:
            return None
        
        subscription.status = "active"
        subscription.payment_provider = payment_provider
        subscription.payment_provider_id = payment_provider_id
        subscription.last_payment_date = datetime.now()
        subscription.last_payment_status = "success"
        subscription.updated_at = datetime.now()
        
        db.commit()
        db.refresh(subscription)
        
        return subscription
    
    @staticmethod
    def get_expiring_subscriptions(
        db: Session,
        days_threshold: int = 7
    ) -> List[Subscription]:
        """
        Get subscriptions expiring soon (for notification).
        
        Args:
            days_threshold: Number of days before expiration
        
        Returns:
            List of subscriptions expiring within threshold
        """
        threshold_date = datetime.now() + timedelta(days=days_threshold)
        
        subscriptions = db.query(Subscription).filter(
            and_(
                Subscription.status == "active",
                Subscription.next_billing_date <= threshold_date,
                Subscription.auto_renew == False
            )
        ).all()
        
        return subscriptions

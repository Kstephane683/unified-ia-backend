"""
Subscription service for legacy ePerformance subscriptions table.
Business logic for subscription management using existing table structure.
"""

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from datetime import datetime, date, timedelta

from backend.core.models_legacy import SubscriptionLegacy, ProductLegacy
from backend.api.schemas_legacy import (
    SubscriptionLegacyCreate,
    SubscriptionLegacyUpdate,
    SubscriptionCancelRequest,
)


class SubscriptionServiceLegacy:
    """Service layer for subscription management (legacy format)"""
    
    @staticmethod
    def create_subscription(db: Session, data: SubscriptionLegacyCreate) -> SubscriptionLegacy:
        """
        Create a new subscription.
        
        Args:
            db: Database session
            data: Subscription creation data
            
        Returns:
            Created subscription instance
        """
        # Calculate end date based on commitment period
        date_fin = data.date_debut + timedelta(days=data.engagement_mois * 30)
        
        # Calculate first billing date
        prochaine_facturation = data.date_debut + timedelta(days=30)
        
        subscription = SubscriptionLegacy(
            user_id=data.user_id,
            candidat_id=data.candidat_id,
            type=data.type,
            niveau=data.niveau,
            montant_mensuel=data.montant_mensuel,
            devise=data.devise,
            engagement_mois=data.engagement_mois,
            date_debut=data.date_debut,
            date_fin=date_fin,
            prochaine_facturation=prochaine_facturation,
            statut='active',
            auto_renew=data.auto_renew,
            facturation_jour=data.facturation_jour,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        
        db.add(subscription)
        db.commit()
        db.refresh(subscription)
        
        return subscription
    
    @staticmethod
    def get_subscription(db: Session, subscription_id: int) -> Optional[SubscriptionLegacy]:
        """Get subscription by ID"""
        return db.query(SubscriptionLegacy).filter(
            SubscriptionLegacy.id == subscription_id
        ).first()
    
    @staticmethod
    def get_user_subscriptions(
        db: Session,
        user_id: int,
        skip: int = 0,
        limit: int = 20,
        statut: Optional[str] = None
    ) -> tuple[List[SubscriptionLegacy], int]:
        """
        Get all subscriptions for a user with pagination.
        
        Returns:
            Tuple of (subscriptions list, total count)
        """
        query = db.query(SubscriptionLegacy).filter(
            SubscriptionLegacy.user_id == user_id
        )
        
        if statut:
            query = query.filter(SubscriptionLegacy.statut == statut)
        
        total = query.count()
        subscriptions = query.order_by(
            SubscriptionLegacy.created_at.desc()
        ).offset(skip).limit(limit).all()
        
        return subscriptions, total
    
    @staticmethod
    def list_subscriptions(
        db: Session,
        skip: int = 0,
        limit: int = 50,
        statut: Optional[str] = None,
        type: Optional[str] = None,
        niveau: Optional[str] = None
    ) -> tuple[List[SubscriptionLegacy], int]:
        """
        List all subscriptions with filters (admin function).
        
        Returns:
            Tuple of (subscriptions list, total count)
        """
        query = db.query(SubscriptionLegacy)
        
        if statut:
            query = query.filter(SubscriptionLegacy.statut == statut)
        if type:
            query = query.filter(SubscriptionLegacy.type == type)
        if niveau:
            query = query.filter(SubscriptionLegacy.niveau == niveau)
        
        total = query.count()
        subscriptions = query.order_by(
            SubscriptionLegacy.created_at.desc()
        ).offset(skip).limit(limit).all()
        
        return subscriptions, total
    
    @staticmethod
    def update_subscription(
        db: Session,
        subscription_id: int,
        data: SubscriptionLegacyUpdate
    ) -> Optional[SubscriptionLegacy]:
        """
        Update subscription fields.
        
        Args:
            db: Database session
            subscription_id: Subscription ID
            data: Fields to update
            
        Returns:
            Updated subscription or None if not found
        """
        subscription = db.query(SubscriptionLegacy).filter(
            SubscriptionLegacy.id == subscription_id
        ).first()
        
        if not subscription:
            return None
        
        # Update fields if provided
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(subscription, field, value)
        
        subscription.updated_at = datetime.now()
        
        db.commit()
        db.refresh(subscription)
        
        return subscription
    
    @staticmethod
    def cancel_subscription(
        db: Session,
        subscription_id: int,
        request: SubscriptionCancelRequest
    ) -> Optional[SubscriptionLegacy]:
        """
        Cancel a subscription.
        
        Args:
            db: Database session
            subscription_id: Subscription ID
            request: Cancellation details
            
        Returns:
            Updated subscription or None if not found
        """
        subscription = db.query(SubscriptionLegacy).filter(
            SubscriptionLegacy.id == subscription_id
        ).first()
        
        if not subscription:
            return None
        
        if request.cancel_immediately:
            # Cancel immediately
            subscription.statut = 'cancelled'
            subscription.cancelled_at = datetime.now()
            subscription.auto_renew = False
        else:
            # Cancel at end of period
            subscription.auto_renew = False
            subscription.cancelled_at = datetime.now()
            # Statut stays 'active' until date_fin
        
        subscription.cancellation_reason = request.reason
        subscription.updated_at = datetime.now()
        
        db.commit()
        db.refresh(subscription)
        
        return subscription
    
    @staticmethod
    def activate_subscription(
        db: Session,
        subscription_id: int
    ) -> Optional[SubscriptionLegacy]:
        """
        Activate a subscription (called after payment confirmation).
        
        Args:
            db: Database session
            subscription_id: Subscription ID
            
        Returns:
            Activated subscription or None if not found
        """
        subscription = db.query(SubscriptionLegacy).filter(
            SubscriptionLegacy.id == subscription_id
        ).first()
        
        if not subscription:
            return None
        
        subscription.statut = 'active'
        subscription.derniere_facturation = date.today()
        
        # Calculate next billing date
        if subscription.prochaine_facturation:
            subscription.prochaine_facturation = subscription.prochaine_facturation + timedelta(days=30)
        
        subscription.updated_at = datetime.now()
        
        db.commit()
        db.refresh(subscription)
        
        return subscription
    
    @staticmethod
    def get_expiring_subscriptions(
        db: Session,
        days_ahead: int = 7
    ) -> List[SubscriptionLegacy]:
        """
        Get subscriptions expiring within specified days.
        Used for sending renewal notifications.
        
        Args:
            db: Database session
            days_ahead: Number of days to look ahead
            
        Returns:
            List of expiring subscriptions
        """
        target_date = date.today() + timedelta(days=days_ahead)
        
        return db.query(SubscriptionLegacy).filter(
            and_(
                SubscriptionLegacy.statut == 'active',
                SubscriptionLegacy.date_fin <= target_date,
                SubscriptionLegacy.date_fin >= date.today()
            )
        ).all()

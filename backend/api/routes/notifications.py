"""
Notifications API Routes
FastAPI endpoints for multi-channel notification system

Endpoints:
- POST   /api/notifications/send           - Send notification
- GET    /api/notifications/{id}           - Get notification status
- GET    /api/notifications/user/{user_id} - User notification history
- POST   /api/notifications/retry          - Retry failed notifications
- GET    /api/preferences/{user_id}        - Get user preferences
- PUT    /api/preferences/{user_id}        - Update user preferences  
- POST   /api/preferences/{user_id}/unsubscribe - Unsubscribe user
- GET    /api/notifications/stats          - Get system statistics

Author: ePerformance IA System
Date: 2026-09-10
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, EmailStr

from backend.database import get_db
from backend.communication.notification_service import NotificationService, NotificationPriority
from backend.communication.core.models import (
    Notification,
    UserNotificationPreference,
    NotificationLog,
    NotificationTemplate
)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


# ═══════════════════════════════════════════════════════════════════════
#  REQUEST / RESPONSE SCHEMAS
# ═══════════════════════════════════════════════════════════════════════

class SendNotificationRequest(BaseModel):
    """Request to send a notification"""
    user_id: int = Field(..., description="Target user ID")
    template_code: str = Field(..., description="Template identifier")
    variables: Dict[str, Any] = Field(default_factory=dict, description="Template variables")
    priority: NotificationPriority = Field(default=NotificationPriority.MEDIUM)
    preferred_channel: Optional[str] = Field(None, description="Force specific channel")
    idempotency_key: Optional[str] = Field(None, description="Unique key to prevent duplicates")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional tracking data")
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": 42,
                "template_code": "order_confirmation",
                "variables": {
                    "order_id": "CMD-20260910-001",
                    "customer_name": "Fatou Diallo",
                    "total": "45 000 FCFA",
                    "delivery_date": "12 septembre 2026"
                },
                "priority": "high",
                "metadata": {
                    "order_id": "CMD-20260910-001",
                    "shop_id": 123
                }
            }
        }


class NotificationResponse(BaseModel):
    """Notification status response"""
    id: int
    user_id: int
    channel: str
    status: str
    priority: str
    template_code: Optional[str] = None
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    opened_at: Optional[datetime] = None
    clicked_at: Optional[datetime] = None
    created_at: datetime
    attempts: int
    error: Optional[str] = None
    fallback_from_channel: Optional[str] = None
    
    class Config:
        from_attributes = True


class UserPreferencesResponse(BaseModel):
    """User notification preferences"""
    user_id: int
    enabled: bool
    email_enabled: bool
    whatsapp_enabled: bool = False
    telegram_enabled: bool = False
    sms_enabled: bool = False
    in_app_enabled: bool = True
    frequency: str
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    timezone: str = "UTC"
    
    class Config:
        from_attributes = True


class UpdatePreferencesRequest(BaseModel):
    """Update user preferences"""
    enabled: Optional[bool] = None
    email_enabled: Optional[bool] = None
    whatsapp_enabled: Optional[bool] = None
    telegram_enabled: Optional[bool] = None
    sms_enabled: Optional[bool] = None
    in_app_enabled: Optional[bool] = None
    frequency: Optional[str] = Field(None, pattern="^(realtime|daily|weekly)$")
    quiet_hours_start: Optional[str] = Field(None, pattern="^([0-1][0-9]|2[0-3]):[0-5][0-9]$")
    quiet_hours_end: Optional[str] = Field(None, pattern="^([0-1][0-9]|2[0-3]):[0-5][0-9]$")
    timezone: Optional[str] = None


class NotificationStatsResponse(BaseModel):
    """System statistics"""
    total_sent: int
    total_delivered: int
    total_failed: int
    total_pending: int
    by_channel: Dict[str, int]
    by_status: Dict[str, int]
    delivery_rate: float
    avg_delivery_time_seconds: Optional[float] = None


# ═══════════════════════════════════════════════════════════════════════
#  DEPENDENCY INJECTION
# ═══════════════════════════════════════════════════════════════════════

def get_notification_service(db: Session = Depends(get_db)) -> NotificationService:
    """
    Create NotificationService instance with config from environment
    
    TODO: Load config from environment variables or config file
    """
    
    # Email config (Brevo)
    email_config = {
        "api_key": "xkeysib-YOUR_BREVO_KEY",  # TODO: Load from env
        "sender_email": "notifications@eperformance.pro",
        "sender_name": "ePerformance",
        "admin_bcc_email": "admin@eperformance.pro"
    }
    
    # WhatsApp config
    whatsapp_config = {
        "phone_number_id": "1079505398586828",
        "access_token": "",  # TODO: Load from env
        "waba_id": ""  # TODO: Load from env
    }
    
    # Telegram config
    telegram_config = {
        "default_bot_token": "8760593501:AAFky23ITJHGGOi96D0V-dbGEFHL_0_4vPg"
    }
    
    return NotificationService(
        db=db,
        email_config=email_config,
        whatsapp_config=whatsapp_config,
        telegram_config=telegram_config,
        redis_client=None  # TODO: Initialize Redis client
    )


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════════════════════════

@router.post("/send", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def send_notification(
    request: SendNotificationRequest,
    service: NotificationService = Depends(get_notification_service)
):
    """
    Send a notification to a user
    
    The system will automatically:
    - Select the best channel based on user preferences
    - Fallback to alternative channels if primary fails
    - Track delivery status
    - Respect user's opt-out preferences
    - Prevent duplicate sends (idempotence)
    
    Returns:
        Dict with notification_id, channel_used, status, etc.
    """
    
    result = await service.send_notification(
        user_id=request.user_id,
        template_code=request.template_code,
        variables=request.variables,
        priority=request.priority,
        preferred_channel=request.preferred_channel,
        idempotency_key=request.idempotency_key,
        metadata=request.metadata
    )
    
    if not result["success"] and result.get("error_code") not in ["USER_OPTED_OUT", "duplicate"]:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error", "Failed to send notification")
        )
    
    return result


@router.get("/{notification_id}", response_model=NotificationResponse)
def get_notification(
    notification_id: int,
    db: Session = Depends(get_db)
):
    """
    Get notification status by ID
    
    Returns full details including delivery tracking, attempts, errors, etc.
    """
    
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification {notification_id} not found"
        )
    
    # Get template code
    template = db.query(NotificationTemplate).filter(
        NotificationTemplate.id == notification.template_id
    ).first()
    
    response = NotificationResponse.model_validate(notification)
    response.template_code = template.code if template else None
    
    return response


@router.get("/user/{user_id}", response_model=List[NotificationResponse])
def get_user_notifications(
    user_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status_filter: Optional[str] = Query(None, pattern="^(sent|delivered|failed|pending)$"),
    channel_filter: Optional[str] = Query(None, pattern="^(email|whatsapp|telegram|sms|in_app)$"),
    db: Session = Depends(get_db)
):
    """
    Get notification history for a user
    
    Supports pagination and filtering by status/channel.
    """
    
    query = db.query(Notification).filter(Notification.user_id == user_id)
    
    if status_filter:
        query = query.filter(Notification.status == status_filter)
    
    if channel_filter:
        query = query.filter(Notification.channel == channel_filter)
    
    notifications = query.order_by(Notification.created_at.desc()).offset(offset).limit(limit).all()
    
    # Enrich with template codes
    results = []
    for notif in notifications:
        template = db.query(NotificationTemplate).filter(
            NotificationTemplate.id == notif.template_id
        ).first()
        
        resp = NotificationResponse.model_validate(notif)
        resp.template_code = template.code if template else None
        results.append(resp)
    
    return results


@router.post("/retry", response_model=Dict[str, Any])
async def retry_failed_notifications(
    max_age_hours: int = Query(24, ge=1, le=168),
    service: NotificationService = Depends(get_notification_service)
):
    """
    Retry all failed notifications within the last N hours
    
    Default: 24 hours
    Maximum: 168 hours (7 days)
    
    Returns:
        Dict with retry statistics (success, failed, skipped counts)
    """
    
    result = await service.retry_failed_notifications(max_age_hours=max_age_hours)
    
    return {
        "success": True,
        "statistics": result,
        "message": f"Retried notifications from last {max_age_hours} hours"
    }


@router.get("/preferences/{user_id}", response_model=UserPreferencesResponse)
def get_user_preferences(
    user_id: int,
    db: Session = Depends(get_db)
):
    """
    Get user notification preferences
    
    If user has no preferences, returns default settings.
    """
    
    preferences = db.query(UserNotificationPreference).filter(
        UserNotificationPreference.user_id == user_id
    ).first()
    
    if not preferences:
        # Return defaults
        return UserPreferencesResponse(
            user_id=user_id,
            enabled=True,
            email_enabled=True,
            whatsapp_enabled=False,
            telegram_enabled=False,
            sms_enabled=False,
            in_app_enabled=True,
            frequency="realtime",
            timezone="UTC"
        )
    
    return UserPreferencesResponse.model_validate(preferences)


@router.put("/preferences/{user_id}", response_model=UserPreferencesResponse)
def update_user_preferences(
    user_id: int,
    request: UpdatePreferencesRequest,
    db: Session = Depends(get_db)
):
    """
    Update user notification preferences
    
    Only provided fields are updated (partial update).
    """
    
    preferences = db.query(UserNotificationPreference).filter(
        UserNotificationPreference.user_id == user_id
    ).first()
    
    # Create if doesn't exist
    if not preferences:
        preferences = UserNotificationPreference(user_id=user_id)
        db.add(preferences)
    
    # Update provided fields
    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(preferences, field, value)
    
    preferences.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(preferences)
    
    return UserPreferencesResponse.model_validate(preferences)


@router.post("/preferences/{user_id}/unsubscribe", response_model=Dict[str, Any])
def unsubscribe_user(
    user_id: int,
    db: Session = Depends(get_db)
):
    """
    Unsubscribe user from all notifications
    
    Sets enabled=False. User can re-subscribe by updating preferences.
    """
    
    preferences = db.query(UserNotificationPreference).filter(
        UserNotificationPreference.user_id == user_id
    ).first()
    
    if not preferences:
        preferences = UserNotificationPreference(user_id=user_id)
        db.add(preferences)
    
    preferences.enabled = False
    preferences.updated_at = datetime.utcnow()
    
    db.commit()
    
    return {
        "success": True,
        "message": f"User {user_id} has been unsubscribed from all notifications"
    }


@router.get("/stats", response_model=NotificationStatsResponse)
def get_notification_stats(
    since_hours: int = Query(24, ge=1, le=720),
    db: Session = Depends(get_db)
):
    """
    Get system-wide notification statistics
    
    Default: Last 24 hours
    Maximum: Last 720 hours (30 days)
    """
    
    cutoff = datetime.utcnow() - timedelta(hours=since_hours)
    
    # Total counts
    total_sent = db.query(Notification).filter(
        Notification.created_at >= cutoff,
        Notification.status == "sent"
    ).count()
    
    total_delivered = db.query(Notification).filter(
        Notification.created_at >= cutoff,
        Notification.status == "delivered"
    ).count()
    
    total_failed = db.query(Notification).filter(
        Notification.created_at >= cutoff,
        Notification.status == "failed"
    ).count()
    
    total_pending = db.query(Notification).filter(
        Notification.created_at >= cutoff,
        Notification.status.in_(["queued", "processing"])
    ).count()
    
    # By channel
    by_channel_raw = db.execute(
        """
        SELECT channel, COUNT(*) as count
        FROM notifications
        WHERE created_at >= :cutoff
        GROUP BY channel
        """,
        {"cutoff": cutoff}
    ).fetchall()
    
    by_channel = {row.channel: row.count for row in by_channel_raw}
    
    # By status
    by_status_raw = db.execute(
        """
        SELECT status, COUNT(*) as count
        FROM notifications
        WHERE created_at >= :cutoff
        GROUP BY status
        """,
        {"cutoff": cutoff}
    ).fetchall()
    
    by_status = {row.status: row.count for row in by_status_raw}
    
    # Delivery rate
    total = total_sent + total_delivered + total_failed
    delivery_rate = (total_sent + total_delivered) / total if total > 0 else 0.0
    
    # Average delivery time
    avg_delivery_time_raw = db.execute(
        """
        SELECT AVG(TIMESTAMPDIFF(SECOND, created_at, sent_at)) as avg_seconds
        FROM notifications
        WHERE created_at >= :cutoff
        AND sent_at IS NOT NULL
        """,
        {"cutoff": cutoff}
    ).fetchone()
    
    avg_delivery_time = avg_delivery_time_raw.avg_seconds if avg_delivery_time_raw else None
    
    return NotificationStatsResponse(
        total_sent=total_sent,
        total_delivered=total_delivered,
        total_failed=total_failed,
        total_pending=total_pending,
        by_channel=by_channel,
        by_status=by_status,
        delivery_rate=round(delivery_rate, 4),
        avg_delivery_time_seconds=round(avg_delivery_time, 2) if avg_delivery_time else None
    )


@router.get("/templates", response_model=List[Dict[str, Any]])
def list_templates(
    db: Session = Depends(get_db)
):
    """
    List all available notification templates
    
    Useful for frontend dropdowns and documentation.
    """
    
    templates = db.query(NotificationTemplate).filter(
        NotificationTemplate.active == True
    ).all()
    
    return [
        {
            "code": t.code,
            "name": t.name,
            "description": t.description,
            "category": t.category,
            "channels": {
                "email": t.email_enabled,
                "whatsapp": getattr(t, "whatsapp_enabled", False),
                "telegram": getattr(t, "telegram_enabled", False),
                "sms": getattr(t, "sms_enabled", False)
            }
        }
        for t in templates
    ]


# ═══════════════════════════════════════════════════════════════════════
#  WEBHOOKS (Provider callbacks)
# ═══════════════════════════════════════════════════════════════════════

@router.post("/webhooks/brevo")
async def brevo_webhook(
    payload: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    Webhook endpoint for Brevo delivery events
    
    Events: delivered, opened, clicked, bounced, soft_bounced, blocked, etc.
    
    Doc: https://developers.brevo.com/docs/transactional-webhooks
    """
    
    event = payload.get("event")
    message_id = payload.get("message-id")
    
    if not message_id:
        return {"success": False, "error": "Missing message-id"}
    
    # Find notification by provider_message_id
    notification = db.query(Notification).filter(
        Notification.provider_message_id == message_id
    ).first()
    
    if not notification:
        return {"success": False, "error": "Notification not found"}
    
    # Update status
    if event == "delivered":
        notification.status = "delivered"
        notification.delivered_at = datetime.utcnow()
    elif event == "opened":
        notification.opened_at = datetime.utcnow()
    elif event in ["bounced", "soft_bounced", "blocked"]:
        notification.status = "bounced"
    elif event == "click":
        notification.clicked_at = datetime.utcnow()
    
    db.commit()
    
    return {"success": True}


@router.post("/webhooks/whatsapp")
async def whatsapp_webhook(
    payload: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    Webhook endpoint for WhatsApp Cloud API delivery events
    
    Events: sent, delivered, read, failed
    
    Doc: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/components
    """
    
    # WhatsApp webhook payload structure
    entry = payload.get("entry", [{}])[0]
    changes = entry.get("changes", [{}])[0]
    value = changes.get("value", {})
    statuses = value.get("statuses", [])
    
    for status_obj in statuses:
        message_id = status_obj.get("id")
        status_value = status_obj.get("status")
        
        # Find notification
        notification = db.query(Notification).filter(
            Notification.provider_message_id == message_id
        ).first()
        
        if not notification:
            continue
        
        # Update status
        if status_value == "delivered":
            notification.status = "delivered"
            notification.delivered_at = datetime.utcnow()
        elif status_value == "read":
            notification.opened_at = datetime.utcnow()
        elif status_value == "failed":
            notification.status = "failed"
            notification.error = status_obj.get("errors", [{}])[0].get("message")
        
        db.commit()
    
    return {"success": True}

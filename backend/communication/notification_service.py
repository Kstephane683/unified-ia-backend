"""
Notification Service - Orchestrateur principal du système de communication

Gère l'envoi multi-canal avec fallback automatique, retry logic, et tracking complet.

Architecture:
- Event-Driven avec Redis Streams (publication dans "notifications" stream)
- Circuit breaker par provider
- Priority queues (critical, high, medium, low)
- Fallback cascade: Email → WhatsApp → Telegram
- RGPD compliant (respect des préférences utilisateur)

Author: ePerformance IA System
Date: 2026-09-10
"""

import asyncio
import json
import hashlib
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from enum import Enum
import logging

from sqlalchemy.orm import Session
from sqlalchemy import and_

from backend.communication.core.models import (
    Notification,
    NotificationChannel,
    NotificationTemplate,
    UserNotificationPreference,
    NotificationLog,
    NotificationQueue
)
from backend.communication.providers.email_provider import EmailProvider
from backend.communication.providers.whatsapp_provider import WhatsAppProvider
from backend.communication.providers.telegram_provider import TelegramProvider

logger = logging.getLogger(__name__)


class NotificationPriority(str, Enum):
    """Niveaux de priorité"""
    CRITICAL = "critical"  # Alerte sécurité, paiement échoué
    HIGH = "high"          # Confirmation commande, OTP
    MEDIUM = "medium"      # Newsletters, offres
    LOW = "low"            # Rapports hebdomadaires


class NotificationService:
    """
    Service orchestrateur de notifications multi-canal
    
    Features:
    - Auto-fallback selon préférences utilisateur
    - Retry avec exponential backoff
    - Circuit breaker (désactive provider si taux d'échec > 50%)
    - Idempotence (évite doublons via idempotency_key)
    - RGPD compliance (respect opt-out)
    - Audit trail complet
    """
    
    # Circuit breaker config
    CIRCUIT_BREAKER_THRESHOLD = 0.5  # 50% d'échec
    CIRCUIT_BREAKER_WINDOW = 300     # 5 minutes
    
    # Retry config
    MAX_RETRIES = 3
    RETRY_DELAYS = [60, 300, 900]  # 1min, 5min, 15min
    
    def __init__(
        self,
        db: Session,
        email_config: Optional[Dict[str, Any]] = None,
        whatsapp_config: Optional[Dict[str, Any]] = None,
        telegram_config: Optional[Dict[str, Any]] = None,
        redis_client: Optional[Any] = None
    ):
        """
        Initialize notification service
        
        Args:
            db: SQLAlchemy session
            email_config: Config for EmailProvider (api_key, sender_email, etc.)
            whatsapp_config: Config for WhatsAppProvider
            telegram_config: Config for TelegramProvider
            redis_client: Redis client for streams (optional)
        """
        self.db = db
        self.redis = redis_client
        
        # Initialize providers
        self.email_provider = EmailProvider(**(email_config or {}))
        self.whatsapp_provider = WhatsAppProvider(**(whatsapp_config or {}))
        self.telegram_provider = TelegramProvider(**(telegram_config or {}))
        
        # Circuit breaker state (in-memory, move to Redis for multi-worker)
        self._circuit_state: Dict[str, Dict[str, Any]] = {
            "email": {"failures": 0, "total": 0, "window_start": datetime.utcnow()},
            "whatsapp": {"failures": 0, "total": 0, "window_start": datetime.utcnow()},
            "telegram": {"failures": 0, "total": 0, "window_start": datetime.utcnow()}
        }
    
    async def send_notification(
        self,
        user_id: int,
        template_code: str,
        variables: Dict[str, Any],
        priority: NotificationPriority = NotificationPriority.MEDIUM,
        preferred_channel: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send notification to user with automatic channel selection and fallback
        
        Args:
            user_id: Target user ID
            template_code: Template identifier (e.g., "welcome_email")
            variables: Template variables (e.g., {"user_name": "Fatou"})
            priority: Notification priority level
            preferred_channel: Force specific channel (optional)
            idempotency_key: Unique key to prevent duplicates (optional, auto-generated if None)
            metadata: Additional tracking data (optional)
        
        Returns:
            Dict with status, notification_id, channel_used, etc.
        
        Example:
            result = await service.send_notification(
                user_id=42,
                template_code="order_confirmation",
                variables={
                    "order_id": "CMD-001",
                    "customer_name": "Fatou",
                    "total": "45000 FCFA"
                },
                priority=NotificationPriority.HIGH
            )
        """
        
        # Generate idempotency key if not provided
        if not idempotency_key:
            idempotency_key = self._generate_idempotency_key(user_id, template_code, variables)
        
        # Check if already sent (idempotence)
        existing = self.db.query(Notification).filter_by(
            idempotency_key=idempotency_key
        ).first()
        
        if existing:
            logger.info(
                f"Notification already sent (idempotent)",
                extra={"notification_id": existing.id, "idempotency_key": idempotency_key}
            )
            return {
                "success": True,
                "notification_id": existing.id,
                "status": "duplicate",
                "message": "Notification already sent"
            }
        
        # Load template
        template = self.db.query(NotificationTemplate).filter_by(code=template_code).first()
        if not template:
            logger.error(f"Template not found: {template_code}")
            return {
                "success": False,
                "error": f"Template '{template_code}' not found",
                "error_code": "TEMPLATE_NOT_FOUND"
            }
        
        # Load user preferences
        preferences = self.db.query(UserNotificationPreference).filter_by(
            user_id=user_id
        ).first()
        
        # Check if user opted out
        if preferences and not preferences.enabled:
            logger.info(f"User {user_id} has disabled notifications")
            return {
                "success": False,
                "error": "User has opted out of notifications",
                "error_code": "USER_OPTED_OUT"
            }
        
        # Determine channel cascade (priority order)
        channels = self._determine_channel_cascade(
            template=template,
            preferences=preferences,
            preferred_channel=preferred_channel
        )
        
        if not channels:
            logger.error(f"No available channel for user {user_id}")
            return {
                "success": False,
                "error": "No notification channel available",
                "error_code": "NO_CHANNEL"
            }
        
        # Create notification record
        notification = Notification(
            user_id=user_id,
            template_id=template.id,
            channel=channels[0],  # Primary channel
            priority=priority.value,
            status="queued",
            idempotency_key=idempotency_key,
            variables=json.dumps(variables, ensure_ascii=False),
            metadata=json.dumps(metadata or {}, ensure_ascii=False),
            scheduled_at=datetime.utcnow(),
            attempts=0
        )
        
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)
        
        logger.info(
            f"Notification queued",
            extra={
                "notification_id": notification.id,
                "user_id": user_id,
                "template": template_code,
                "channel": channels[0]
            }
        )
        
        # Attempt to send through cascade
        result = await self._send_with_fallback(
            notification=notification,
            channels=channels,
            template=template,
            variables=variables
        )
        
        # Update notification status
        notification.status = result["status"]
        notification.channel = result.get("channel_used", channels[0])
        notification.provider_message_id = result.get("message_id")
        notification.sent_at = datetime.utcnow() if result["success"] else None
        notification.error = result.get("error")
        notification.attempts += 1
        
        # Track fallback
        if result.get("fallback_from_channel"):
            notification.fallback_from_channel = result["fallback_from_channel"]
        
        self.db.commit()
        
        # Log event
        self._log_notification_event(
            notification_id=notification.id,
            event="sent" if result["success"] else "failed",
            details=result
        )
        
        # Publish to Redis Stream (for analytics/webhook processing)
        if self.redis:
            await self._publish_to_stream(notification, result)
        
        return {
            "success": result["success"],
            "notification_id": notification.id,
            "channel_used": result.get("channel_used"),
            "status": result["status"],
            "message_id": result.get("message_id"),
            "error": result.get("error")
        }
    
    async def _send_with_fallback(
        self,
        notification: Notification,
        channels: List[str],
        template: NotificationTemplate,
        variables: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Try sending through channels in cascade until success
        
        Returns:
            Dict with success, status, channel_used, message_id, etc.
        """
        
        last_error = None
        fallback_from = None
        
        for channel in channels:
            # Check circuit breaker
            if self._is_circuit_open(channel):
                logger.warning(f"Circuit breaker OPEN for {channel}, skipping")
                fallback_from = channel
                continue
            
            logger.info(f"Attempting to send via {channel}")
            
            try:
                # Select provider and prepare payload
                if channel == "email":
                    result = await self._send_via_email(notification, template, variables)
                elif channel == "whatsapp":
                    result = await self._send_via_whatsapp(notification, template, variables)
                elif channel == "telegram":
                    result = await self._send_via_telegram(notification, template, variables)
                else:
                    logger.error(f"Unknown channel: {channel}")
                    continue
                
                # Update circuit breaker
                self._record_attempt(channel, success=result["success"])
                
                if result["success"]:
                    logger.info(
                        f"Notification sent successfully via {channel}",
                        extra={"notification_id": notification.id, "message_id": result.get("message_id")}
                    )
                    return {
                        "success": True,
                        "status": "sent",
                        "channel_used": channel,
                        "message_id": result.get("message_id"),
                        "fallback_from_channel": fallback_from,
                        "provider_response": result
                    }
                else:
                    # Failed, try next channel
                    logger.warning(
                        f"Failed to send via {channel}: {result.get('error')}",
                        extra={"notification_id": notification.id}
                    )
                    last_error = result.get("error")
                    fallback_from = channel
            
            except Exception as e:
                logger.exception(f"Exception sending via {channel}")
                last_error = str(e)
                fallback_from = channel
                self._record_attempt(channel, success=False)
        
        # All channels failed
        logger.error(
            f"All channels failed for notification {notification.id}",
            extra={"channels_tried": channels, "last_error": last_error}
        )
        
        return {
            "success": False,
            "status": "failed",
            "error": last_error or "All channels failed",
            "channels_tried": channels
        }
    
    async def _send_via_email(
        self,
        notification: Notification,
        template: NotificationTemplate,
        variables: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send via Email provider"""
        
        # Get recipient email from user
        user = self.db.execute(
            "SELECT email FROM users WHERE id = :user_id",
            {"user_id": notification.user_id}
        ).fetchone()
        
        if not user or not user.email:
            return {"success": False, "error": "User email not found"}
        
        payload = {
            "recipient_email": user.email,
            "recipient_name": variables.get("user_name", ""),
            "subject": template.email_subject,
            "html_content": self._render_template(template.email_body, variables),
            "template_id": template.brevo_template_id if hasattr(template, "brevo_template_id") else None,
            "params": variables
        }
        
        return await self.email_provider.send(payload)
    
    async def _send_via_whatsapp(
        self,
        notification: Notification,
        template: NotificationTemplate,
        variables: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send via WhatsApp provider"""
        
        # Get recipient phone from user
        user = self.db.execute(
            "SELECT phone FROM users WHERE id = :user_id",
            {"user_id": notification.user_id}
        ).fetchone()
        
        if not user or not user.phone:
            return {"success": False, "error": "User phone not found"}
        
        payload = {
            "to": user.phone,
            "template_name": template.whatsapp_template_name if hasattr(template, "whatsapp_template_name") else None,
            "language": "fr",
            "components": self._build_whatsapp_components(template, variables)
        }
        
        return await self.whatsapp_provider.send(payload)
    
    async def _send_via_telegram(
        self,
        notification: Notification,
        template: NotificationTemplate,
        variables: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send via Telegram provider"""
        
        # Get recipient Telegram chat_id from user
        user = self.db.execute(
            "SELECT telegram_chat_id FROM users WHERE id = :user_id",
            {"user_id": notification.user_id}
        ).fetchone()
        
        if not user or not user.telegram_chat_id:
            return {"success": False, "error": "User Telegram chat_id not found"}
        
        payload = {
            "chat_id": user.telegram_chat_id,
            "message": self._render_template(template.telegram_message if hasattr(template, "telegram_message") else template.email_body, variables),
            "parse_mode": "HTML"
        }
        
        return await self.telegram_provider.send(payload)
    
    def _determine_channel_cascade(
        self,
        template: NotificationTemplate,
        preferences: Optional[UserNotificationPreference],
        preferred_channel: Optional[str]
    ) -> List[str]:
        """
        Determine the cascade of channels to try (in order)
        
        Logic:
        1. If preferred_channel specified, start with it
        2. Else use user preferences
        3. Fallback to template's default channels
        4. Apply user's disabled channels
        
        Returns:
            List of channel codes in priority order
        """
        
        # Start with template's supported channels
        template_channels = []
        if template.email_enabled:
            template_channels.append("email")
        if hasattr(template, "whatsapp_enabled") and template.whatsapp_enabled:
            template_channels.append("whatsapp")
        if hasattr(template, "telegram_enabled") and template.telegram_enabled:
            template_channels.append("telegram")
        if hasattr(template, "sms_enabled") and template.sms_enabled:
            template_channels.append("sms")
        
        # If no channels enabled in template, fallback to email
        if not template_channels:
            template_channels = ["email"]
        
        # Apply user preferences
        if preferences:
            # Remove disabled channels
            if not preferences.email_enabled:
                template_channels = [c for c in template_channels if c != "email"]
            if hasattr(preferences, "whatsapp_enabled") and not preferences.whatsapp_enabled:
                template_channels = [c for c in template_channels if c != "whatsapp"]
            if hasattr(preferences, "telegram_enabled") and not preferences.telegram_enabled:
                template_channels = [c for c in template_channels if c != "telegram"]
            if hasattr(preferences, "sms_enabled") and not preferences.sms_enabled:
                template_channels = [c for c in template_channels if c != "sms"]
        
        # If preferred channel specified, move it to front
        if preferred_channel and preferred_channel in template_channels:
            template_channels.remove(preferred_channel)
            template_channels.insert(0, preferred_channel)
        
        return template_channels
    
    def _render_template(self, template_text: str, variables: Dict[str, Any]) -> str:
        """
        Simple template rendering (replace {{variable}} with value)
        
        For production, consider using Jinja2
        """
        result = template_text
        for key, value in variables.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result
    
    def _build_whatsapp_components(
        self,
        template: NotificationTemplate,
        variables: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Build WhatsApp template components from variables
        
        Example:
            variables = {"order_id": "CMD-001", "total": "45000 FCFA"}
            
            Returns:
            [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": "CMD-001"},
                        {"type": "text", "text": "45000 FCFA"}
                    ]
                }
            ]
        """
        
        # Extract ordered parameter list from template metadata
        # (assuming template has whatsapp_param_order = ["order_id", "total"])
        param_order = []
        if hasattr(template, "whatsapp_param_order") and template.whatsapp_param_order:
            try:
                param_order = json.loads(template.whatsapp_param_order)
            except:
                pass
        
        if not param_order:
            # Fallback: use all variables in alphabetical order
            param_order = sorted(variables.keys())
        
        parameters = []
        for key in param_order:
            if key in variables:
                parameters.append({
                    "type": "text",
                    "text": str(variables[key])
                })
        
        return [
            {
                "type": "body",
                "parameters": parameters
            }
        ] if parameters else []
    
    def _generate_idempotency_key(
        self,
        user_id: int,
        template_code: str,
        variables: Dict[str, Any]
    ) -> str:
        """Generate unique idempotency key"""
        
        # Hash user_id + template + critical variables
        payload = f"{user_id}:{template_code}:{json.dumps(variables, sort_keys=True)}"
        return hashlib.sha256(payload.encode()).hexdigest()[:32]
    
    def _log_notification_event(
        self,
        notification_id: int,
        event: str,
        details: Dict[str, Any]
    ):
        """Log notification event to database"""
        
        log_entry = NotificationLog(
            notification_id=notification_id,
            event=event,
            details=json.dumps(details, ensure_ascii=False),
            created_at=datetime.utcnow()
        )
        self.db.add(log_entry)
        self.db.commit()
    
    async def _publish_to_stream(self, notification: Notification, result: Dict[str, Any]):
        """Publish notification event to Redis Stream"""
        
        if not self.redis:
            return
        
        event = {
            "notification_id": notification.id,
            "user_id": notification.user_id,
            "channel": result.get("channel_used", notification.channel),
            "status": result["status"],
            "timestamp": datetime.utcnow().isoformat(),
            "success": result["success"]
        }
        
        try:
            await self.redis.xadd("notifications", event)
        except Exception as e:
            logger.error(f"Failed to publish to Redis Stream: {e}")
    
    def _is_circuit_open(self, channel: str) -> bool:
        """Check if circuit breaker is open for this channel"""
        
        state = self._circuit_state.get(channel)
        if not state:
            return False
        
        # Reset window if expired
        if datetime.utcnow() - state["window_start"] > timedelta(seconds=self.CIRCUIT_BREAKER_WINDOW):
            state["failures"] = 0
            state["total"] = 0
            state["window_start"] = datetime.utcnow()
            return False
        
        # Check failure rate
        if state["total"] > 10:  # Minimum sample size
            failure_rate = state["failures"] / state["total"]
            return failure_rate > self.CIRCUIT_BREAKER_THRESHOLD
        
        return False
    
    def _record_attempt(self, channel: str, success: bool):
        """Record attempt for circuit breaker tracking"""
        
        state = self._circuit_state.get(channel)
        if not state:
            return
        
        state["total"] += 1
        if not success:
            state["failures"] += 1
    
    async def retry_failed_notifications(self, max_age_hours: int = 24) -> Dict[str, Any]:
        """
        Retry failed notifications within the last N hours
        
        Args:
            max_age_hours: Only retry notifications newer than this
        
        Returns:
            Dict with retry statistics
        """
        
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        
        failed = self.db.query(Notification).filter(
            and_(
                Notification.status == "failed",
                Notification.created_at >= cutoff,
                Notification.attempts < self.MAX_RETRIES
            )
        ).all()
        
        logger.info(f"Retrying {len(failed)} failed notifications")
        
        results = {"success": 0, "failed": 0, "skipped": 0}
        
        for notification in failed:
            # Load template and variables
            template = self.db.query(NotificationTemplate).get(notification.template_id)
            variables = json.loads(notification.variables)
            
            # Determine channels (skip the one that failed)
            preferences = self.db.query(UserNotificationPreference).filter_by(
                user_id=notification.user_id
            ).first()
            
            channels = self._determine_channel_cascade(template, preferences, None)
            
            # Remove the channel that previously failed
            if notification.fallback_from_channel and notification.fallback_from_channel in channels:
                channels.remove(notification.fallback_from_channel)
            
            if not channels:
                results["skipped"] += 1
                continue
            
            # Retry
            result = await self._send_with_fallback(notification, channels, template, variables)
            
            # Update notification
            notification.status = result["status"]
            notification.attempts += 1
            if result["success"]:
                notification.sent_at = datetime.utcnow()
                notification.channel = result["channel_used"]
                results["success"] += 1
            else:
                results["failed"] += 1
            
            self.db.commit()
            
            # Brief delay to avoid rate limits
            await asyncio.sleep(0.5)
        
        logger.info(f"Retry completed: {results}")
        return results

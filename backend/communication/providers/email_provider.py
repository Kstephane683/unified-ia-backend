"""
Email Provider using Brevo (formerly SendInBlue) API v3.
Handles transactional and marketing emails with automatic BCC to admin.
"""

import httpx
from typing import Dict, Any, Optional, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class EmailProvider:
    """
    Provider for sending emails via Brevo API v3
    
    Features:
    - Automatic BCC to admin (REQUIRED - admin copié sur TOUS les emails)
    - Template rendering with variables
    - Attachment support
    - Tracking (opens, clicks)
    - SMTP headers (Reply-To, List-Unsubscribe)
    - Retry on failure
    """
    
    def __init__(
        self,
        api_key: str,
        sender_email: str = "notifications@eperformance.pro",
        sender_name: str = "ePerformance",
        admin_bcc_email: str = "ballo@eperformance.pro"
    ):
        self.api_key = api_key
        self.sender_email = sender_email
        self.sender_name = sender_name
        self.admin_bcc_email = admin_bcc_email  # IMPORTANT: Admin copié sur TOUS les emails
        self.api_url = "https://api.brevo.com/v3/smtp/email"
        
    async def send(self, notification: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send email via Brevo API
        
        Args:
            notification: Dict with keys:
                - recipient_email: str
                - recipient_name: str (optional)
                - subject: str
                - html_content: str
                - text_content: str (optional, fallback)
                - reply_to: str (optional)
                - attachments: List[Dict] (optional)
                - headers: Dict[str, str] (optional)
                - tags: List[str] (optional, for analytics)
                - template_id: int (optional, use Brevo template)
                - template_params: Dict (optional, for template)
                
        Returns:
            Dict with success status, message_id, and provider info
        """
        
        try:
            # Build email payload
            payload = self._build_payload(notification)
            
            # Send via Brevo API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.api_url,
                    headers={
                        "api-key": self.api_key,
                        "content-type": "application/json",
                        "accept": "application/json"
                    },
                    json=payload,
                    timeout=30.0
                )
                
                # Handle response
                if response.status_code == 201:
                    data = response.json()
                    
                    logger.info(
                        f"Email sent successfully via Brevo",
                        extra={
                            "message_id": data.get("messageId"),
                            "recipient": notification["recipient_email"],
                            "notification_id": notification.get("id")
                        }
                    )
                    
                    return {
                        "success": True,
                        "message_id": data.get("messageId"),
                        "provider": "brevo",
                        "sent_at": datetime.utcnow().isoformat(),
                        "response": data
                    }
                    
                else:
                    error_msg = f"Brevo API error: {response.status_code}"
                    error_detail = response.text
                    
                    logger.error(
                        error_msg,
                        extra={
                            "status_code": response.status_code,
                            "response": error_detail,
                            "notification_id": notification.get("id")
                        }
                    )
                    
                    return {
                        "success": False,
                        "error": error_msg,
                        "error_code": str(response.status_code),
                        "response": error_detail
                    }
                    
        except httpx.TimeoutException:
            logger.error("Brevo API timeout", extra={"notification_id": notification.get("id")})
            return {
                "success": False,
                "error": "Brevo API timeout after 30s",
                "error_code": "TIMEOUT"
            }
            
        except Exception as e:
            logger.exception("Unexpected error sending email", extra={"notification_id": notification.get("id")})
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}",
                "error_code": "EXCEPTION"
            }
    
    def _build_payload(self, notification: Dict[str, Any]) -> Dict[str, Any]:
        """Build Brevo API payload from notification"""
        
        payload = {
            "sender": {
                "email": self.sender_email,
                "name": self.sender_name
            },
            "to": [
                {
                    "email": notification["recipient_email"],
                    "name": notification.get("recipient_name", "")
                }
            ],
            # IMPORTANT: BCC admin automatique sur TOUS les emails
            "bcc": [
                {
                    "email": self.admin_bcc_email,
                    "name": "Admin ePerformance"
                }
            ]
        }
        
        # Template Brevo ou contenu direct
        if notification.get("template_id"):
            # Utiliser template Brevo
            payload["templateId"] = notification["template_id"]
            payload["params"] = notification.get("template_params", {})
        else:
            # Contenu direct
            payload["subject"] = notification["subject"]
            payload["htmlContent"] = notification["html_content"]
            
            # Fallback plain text
            if notification.get("text_content"):
                payload["textContent"] = notification["text_content"]
        
        # Reply-To (optionnel)
        if notification.get("reply_to"):
            payload["replyTo"] = {
                "email": notification["reply_to"],
                "name": notification.get("reply_to_name", "")
            }
        
        # Headers personnalisés
        headers = notification.get("headers", {})
        
        # RGPD: List-Unsubscribe header (RFC 2369 + RFC 8058)
        if notification.get("unsubscribe_url"):
            headers["List-Unsubscribe"] = f"<{notification['unsubscribe_url']}>"
            headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        
        # Tracking ID
        if notification.get("id"):
            headers["X-Notification-ID"] = str(notification["id"])
        
        if headers:
            payload["headers"] = headers
        
        # Tags pour analytics (max 10)
        if notification.get("tags"):
            payload["tags"] = notification["tags"][:10]
        
        # Attachments
        if notification.get("attachments"):
            payload["attachment"] = [
                {
                    "name": att["filename"],
                    "content": att["content_base64"]  # Base64 encoded
                }
                for att in notification["attachments"]
            ]
        
        return payload
    
    async def get_delivery_status(self, message_id: str) -> Dict[str, Any]:
        """
        Get email delivery status from Brevo
        
        Statuses: delivered, soft_bounced, hard_bounced, opened, clicked
        """
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.brevo.com/v3/smtp/statistics/events",
                    headers={
                        "api-key": self.api_key,
                        "accept": "application/json"
                    },
                    params={
                        "messageId": message_id,
                        "limit": 1
                    },
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    events = data.get("events", [])
                    
                    if events:
                        latest_event = events[0]
                        return {
                            "success": True,
                            "status": latest_event.get("event"),  # delivered, opened, clicked, etc.
                            "timestamp": latest_event.get("date"),
                            "data": latest_event
                        }
                    else:
                        return {
                            "success": True,
                            "status": "pending",
                            "message": "No events found yet"
                        }
                else:
                    return {
                        "success": False,
                        "error": f"Brevo API error: {response.status_code}"
                    }
                    
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def send_bulk(self, notifications: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Send multiple emails in batch (max 1000 per call)
        
        More efficient than individual sends for newsletters, etc.
        """
        
        if len(notifications) > 1000:
            raise ValueError("Brevo bulk send limited to 1000 emails per call")
        
        try:
            # Build bulk payload
            recipients = []
            for notif in notifications:
                recipient = {
                    "email": notif["recipient_email"],
                    "name": notif.get("recipient_name", "")
                }
                
                # Template params per recipient
                if notif.get("template_params"):
                    recipient["params"] = notif["template_params"]
                
                recipients.append(recipient)
            
            payload = {
                "sender": {
                    "email": self.sender_email,
                    "name": self.sender_name
                },
                "to": recipients,
                "bcc": [{"email": self.admin_bcc_email}],  # BCC admin
                "templateId": notifications[0].get("template_id"),
                "subject": notifications[0].get("subject"),
                "htmlContent": notifications[0].get("html_content")
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.api_url,
                    headers={
                        "api-key": self.api_key,
                        "content-type": "application/json"
                    },
                    json=payload,
                    timeout=60.0  # Longer timeout for bulk
                )
                
                if response.status_code == 201:
                    data = response.json()
                    
                    return [
                        {
                            "success": True,
                            "message_id": data.get("messageId"),
                            "provider": "brevo"
                        }
                        for _ in notifications
                    ]
                else:
                    error = {
                        "success": False,
                        "error": f"Brevo bulk send error: {response.status_code}",
                        "response": response.text
                    }
                    return [error for _ in notifications]
                    
        except Exception as e:
            error = {
                "success": False,
                "error": str(e)
            }
            return [error for _ in notifications]

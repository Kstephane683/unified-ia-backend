"""
Telegram Provider using Bot API
Handles messages via Telegram bots with rich formatting and interactive buttons.

Avantages vs WhatsApp:
- Pas d'approbation préalable de templates
- Messages gratuits illimités
- Support HTML/Markdown complet
- Boutons inline et callbacks
- Fichiers jusqu'à 2 GB

Documentation: https://core.telegram.org/bots/api
"""

import httpx
from typing import Dict, Any, Optional, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class TelegramProvider:
    """
    Provider for Telegram Bot API
    
    Features:
    - Rich text formatting (HTML/Markdown)
    - Inline keyboards with callbacks
    - Media messages (photos, videos, documents)
    - File size: Up to 2 GB
    - No rate limit for notifications
    - Multi-tenant support (different bot per client)
    """
    
    API_BASE_URL = "https://api.telegram.org"
    
    def __init__(self, default_bot_token: Optional[str] = None):
        """
        Initialize Telegram provider
        
        Args:
            default_bot_token: Default bot token (optional, can be per-notification)
        """
        self.default_bot_token = default_bot_token
        
    async def send(self, notification: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send Telegram message
        
        Args:
            notification: Dict with keys:
                - bot_token: str (optional if default_bot_token set)
                - chat_id: str (user's Telegram chat ID)
                - message: str (text content, HTML/Markdown)
                - parse_mode: str (optional, "HTML" or "Markdown", default "HTML")
                - reply_markup: Dict (optional, inline keyboard)
                - disable_notification: bool (optional, silent message)
                - photo: str (optional, photo URL)
                - document: str (optional, document URL)
                
        Returns:
            Dict with success status, message_id, and provider info
        """
        
        bot_token = notification.get("bot_token", self.default_bot_token)
        
        if not bot_token:
            return {
                "success": False,
                "error": "No bot_token provided",
                "error_code": "MISSING_TOKEN"
            }
        
        chat_id = notification["chat_id"]
        
        try:
            # Determine message type
            if notification.get("photo"):
                result = await self._send_photo(bot_token, chat_id, notification)
            elif notification.get("document"):
                result = await self._send_document(bot_token, chat_id, notification)
            else:
                result = await self._send_text(bot_token, chat_id, notification)
            
            return result
            
        except httpx.TimeoutException:
            logger.error("Telegram API timeout")
            return {
                "success": False,
                "error": "Telegram API timeout after 30s",
                "error_code": "TIMEOUT"
            }
            
        except Exception as e:
            logger.exception("Unexpected error sending Telegram message")
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}",
                "error_code": "EXCEPTION"
            }
    
    async def _send_text(
        self, 
        bot_token: str, 
        chat_id: str, 
        notification: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send text message"""
        
        url = f"{self.API_BASE_URL}/bot{bot_token}/sendMessage"
        
        payload = {
            "chat_id": chat_id,
            "text": notification["message"],
            "parse_mode": notification.get("parse_mode", "HTML"),
            "disable_web_page_preview": notification.get("disable_web_page_preview", True),
            "disable_notification": notification.get("disable_notification", False)
        }
        
        # Inline keyboard (boutons)
        if notification.get("reply_markup"):
            payload["reply_markup"] = notification["reply_markup"]
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=30.0)
            
            if response.status_code == 200:
                data = response.json()
                message_id = data["result"]["message_id"]
                
                logger.info(
                    f"Telegram message sent successfully",
                    extra={
                        "message_id": message_id,
                        "chat_id": chat_id
                    }
                )
                
                return {
                    "success": True,
                    "message_id": str(message_id),
                    "provider": "telegram",
                    "sent_at": datetime.utcnow().isoformat(),
                    "response": data
                }
            else:
                error_data = response.json()
                error_msg = error_data.get("description", "Unknown error")
                
                logger.error(
                    f"Telegram API error: {error_msg}",
                    extra={
                        "error_code": error_data.get("error_code"),
                        "chat_id": chat_id
                    }
                )
                
                return {
                    "success": False,
                    "error": error_msg,
                    "error_code": str(error_data.get("error_code", response.status_code)),
                    "response": error_data
                }
    
    async def _send_photo(
        self,
        bot_token: str,
        chat_id: str,
        notification: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send photo with caption"""
        
        url = f"{self.API_BASE_URL}/bot{bot_token}/sendPhoto"
        
        payload = {
            "chat_id": chat_id,
            "photo": notification["photo"],  # URL or file_id
            "caption": notification.get("message", ""),
            "parse_mode": notification.get("parse_mode", "HTML"),
            "disable_notification": notification.get("disable_notification", False)
        }
        
        if notification.get("reply_markup"):
            payload["reply_markup"] = notification["reply_markup"]
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=30.0)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "message_id": str(data["result"]["message_id"]),
                    "provider": "telegram"
                }
            else:
                return {
                    "success": False,
                    "error": response.json().get("description", "Error sending photo"),
                    "error_code": str(response.status_code)
                }
    
    async def _send_document(
        self,
        bot_token: str,
        chat_id: str,
        notification: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send document (PDF, etc.)"""
        
        url = f"{self.API_BASE_URL}/bot{bot_token}/sendDocument"
        
        payload = {
            "chat_id": chat_id,
            "document": notification["document"],  # URL or file_id
            "caption": notification.get("message", ""),
            "parse_mode": notification.get("parse_mode", "HTML"),
            "disable_notification": notification.get("disable_notification", False)
        }
        
        if notification.get("reply_markup"):
            payload["reply_markup"] = notification["reply_markup"]
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=30.0)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "message_id": str(data["result"]["message_id"]),
                    "provider": "telegram"
                }
            else:
                return {
                    "success": False,
                    "error": response.json().get("description", "Error sending document"),
                    "error_code": str(response.status_code)
                }
    
    async def edit_message(
        self,
        bot_token: str,
        chat_id: str,
        message_id: int,
        new_text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Edit an existing message (useful for updating statuses)"""
        
        url = f"{self.API_BASE_URL}/bot{bot_token}/editMessageText"
        
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": new_text,
            "parse_mode": parse_mode
        }
        
        if reply_markup:
            payload["reply_markup"] = reply_markup
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=10.0)
                
                if response.status_code == 200:
                    return {"success": True}
                else:
                    return {
                        "success": False,
                        "error": response.json().get("description", "Edit failed")
                    }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def delete_message(
        self,
        bot_token: str,
        chat_id: str,
        message_id: int
    ) -> Dict[str, Any]:
        """Delete a message"""
        
        url = f"{self.API_BASE_URL}/bot{bot_token}/deleteMessage"
        
        payload = {
            "chat_id": chat_id,
            "message_id": message_id
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=10.0)
                
                if response.status_code == 200:
                    return {"success": True}
                else:
                    return {
                        "success": False,
                        "error": response.json().get("description", "Delete failed")
                    }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def answer_callback_query(
        self,
        bot_token: str,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False
    ) -> Dict[str, Any]:
        """
        Answer callback query from inline button
        
        Used when user clicks on inline button to show feedback
        """
        
        url = f"{self.API_BASE_URL}/bot{bot_token}/answerCallbackQuery"
        
        payload = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert
        }
        
        if text:
            payload["text"] = text
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=10.0)
                
                if response.status_code == 200:
                    return {"success": True}
                else:
                    return {
                        "success": False,
                        "error": response.json().get("description", "Answer failed")
                    }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    @staticmethod
    def build_inline_keyboard(buttons: List[List[Dict[str, str]]]) -> Dict:
        """
        Build inline keyboard markup
        
        Args:
            buttons: List of button rows, each row is list of buttons
            
        Button types:
        - URL: {"text": "Label", "url": "https://..."}
        - Callback: {"text": "Label", "callback_data": "action_id"}
        
        Example:
            buttons = [
                [{"text": "✅ Confirmer", "callback_data": "confirm"}],
                [
                    {"text": "📞 Appeler", "url": "tel:+2250151170666"},
                    {"text": "🌐 Site web", "url": "https://eperformance.pro"}
                ]
            ]
        
        Returns:
            Dict ready for reply_markup parameter
        """
        
        return {
            "inline_keyboard": buttons
        }
    
    @staticmethod
    def escape_markdown(text: str) -> str:
        """Escape special characters for Markdown parse_mode"""
        
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        
        return text


# ═══════════════════════════════════════════════════════════════════════
#  EXEMPLES D'UTILISATION TELEGRAM
# ═══════════════════════════════════════════════════════════════════════

TELEGRAM_USAGE_EXAMPLES = """
╔══════════════════════════════════════════════════════════════════════╗
║  EXEMPLES D'UTILISATION - TELEGRAM PROVIDER                          ║
╚══════════════════════════════════════════════════════════════════════╝

──────────────────────────────────────────────────────────────────────
1. MESSAGE TEXTE SIMPLE
──────────────────────────────────────────────────────────────────────

```python
provider = TelegramProvider()

await provider.send({
    "bot_token": "8760593501:AAFky23ITJHGGOi96D0V-dbGEFHL_0_4vPg",
    "chat_id": "8441274889",
    "message": "Bonjour ! Votre commande #CMD001 est confirmée."
})
```

──────────────────────────────────────────────────────────────────────
2. MESSAGE HTML FORMATÉ
──────────────────────────────────────────────────────────────────────

```python
await provider.send({
    "bot_token": BOT_TOKEN,
    "chat_id": CHAT_ID,
    "message": '''
<b>✅ Commande confirmée</b>

Bonjour <b>Fatou</b>,

Votre commande <code>#CMD20260910-001</code> a bien été enregistrée.

<b>📦 Articles:</b>
  • Robe rouge x1 — 25 000 FCFA
  • Sac à main x1 — 20 000 FCFA

<b>💰 Total:</b> 45 000 FCFA
<b>🚚 Livraison:</b> 2-3 jours

Merci de votre confiance !
— La Belle Boutique
    ''',
    "parse_mode": "HTML"
})
```

Tags HTML supportés:
• <b>gras</b> / <strong>gras</strong>
• <i>italique</i> / <em>italique</em>
• <u>souligné</u>
• <s>barré</s>
• <code>code</code>
• <pre>bloc de code</pre>
• <a href="URL">lien</a>

──────────────────────────────────────────────────────────────────────
3. MESSAGE AVEC BOUTONS INLINE
──────────────────────────────────────────────────────────────────────

```python
from backend.communication.providers.telegram_provider import TelegramProvider

keyboard = TelegramProvider.build_inline_keyboard([
    [
        {"text": "🔍 Suivre ma commande", "url": "https://eperformance.pro/orders/CMD001"}
    ],
    [
        {"text": "📞 Contacter", "url": "https://wa.me/2250151170666"},
        {"text": "❌ Annuler", "callback_data": "cancel_order_CMD001"}
    ]
])

await provider.send({
    "bot_token": BOT_TOKEN,
    "chat_id": CHAT_ID,
    "message": "<b>Votre commande est prête !</b>\\n\\nQue souhaitez-vous faire ?",
    "parse_mode": "HTML",
    "reply_markup": keyboard
})
```

──────────────────────────────────────────────────────────────────────
4. MESSAGE AVEC IMAGE
──────────────────────────────────────────────────────────────────────

```python
await provider.send({
    "bot_token": BOT_TOKEN,
    "chat_id": CHAT_ID,
    "photo": "https://eperformance.pro/images/product123.jpg",
    "message": '''
<b>✨ Nouveau produit disponible !</b>

Robe d'été - Collection 2026
Prix: 35 000 FCFA

Découvrez toute la collection sur notre site.
    ''',
    "parse_mode": "HTML",
    "reply_markup": TelegramProvider.build_inline_keyboard([
        [{"text": "🛒 Commander maintenant", "url": "https://eperformance.pro/products/123"}]
    ])
})
```

──────────────────────────────────────────────────────────────────────
5. MODIFIER UN MESSAGE EXISTANT (Update status)
──────────────────────────────────────────────────────────────────────

```python
# Utile pour mettre à jour le statut de livraison

# Envoi initial
result = await provider.send({
    "bot_token": BOT_TOKEN,
    "chat_id": CHAT_ID,
    "message": "📦 Votre colis est <b>en préparation</b>...",
    "parse_mode": "HTML"
})

message_id = result["message_id"]

# ... 1h plus tard, mise à jour
await provider.edit_message(
    bot_token=BOT_TOKEN,
    chat_id=CHAT_ID,
    message_id=int(message_id),
    new_text="📦 Votre colis est <b>en transit</b> ! 🚚\\n\\nLivraison prévue: Demain 15h",
    parse_mode="HTML"
)

# ... Livraison effectuée
await provider.edit_message(
    bot_token=BOT_TOKEN,
    chat_id=CHAT_ID,
    message_id=int(message_id),
    new_text="✅ Votre colis a été <b>livré</b> !\\n\\nMerci de votre confiance.",
    parse_mode="HTML"
)
```

──────────────────────────────────────────────────────────────────────
6. MESSAGE SILENCIEUX (Pas de notification sonore)
──────────────────────────────────────────────────────────────────────

```python
# Utile pour notifications non-urgentes (rapports quotidiens, etc.)

await provider.send({
    "bot_token": BOT_TOKEN,
    "chat_id": CHAT_ID,
    "message": "📊 Rapport quotidien disponible",
    "disable_notification": True  # Pas de son
})
```

──────────────────────────────────────────────────────────────────────
7. ALERTES ADMIN (Pour monitoring système)
──────────────────────────────────────────────────────────────────────

```python
# Envoyer alerte Telegram admin en cas de problème

async def alert_admin(severity: str, title: str, details: str):
    emoji = {"info": "ℹ️", "warning": "⚠️", "error": "❌", "critical": "🚨"}[severity]
    
    await TelegramProvider().send({
        "bot_token": ADMIN_BOT_TOKEN,
        "chat_id": ADMIN_CHAT_ID,
        "message": f'''
{emoji} <b>{title}</b>

<b>Sévérité:</b> {severity.upper()}
<b>Timestamp:</b> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

<b>Détails:</b>
{details}
        ''',
        "parse_mode": "HTML",
        "reply_markup": TelegramProvider.build_inline_keyboard([
            [{"text": "🔍 Voir logs", "url": "https://logs.eperformance.pro"}]
        ])
    })

# Usage
await alert_admin(
    severity="critical",
    title="Taux d'échec email élevé",
    details="15% des emails ont échoué dans la dernière heure (attendu: 2%)"
)
```

╚══════════════════════════════════════════════════════════════════════╝
"""

# Guide disponible via TELEGRAM_USAGE_EXAMPLES (commenté le print pour éviter affichage à l'import)
# print(TELEGRAM_USAGE_EXAMPLES)

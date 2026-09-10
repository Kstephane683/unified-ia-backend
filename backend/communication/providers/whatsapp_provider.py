"""
WhatsApp Provider using Meta Cloud API v21.0
Handles message templates approved by Meta for transactional notifications.

IMPORTANT: 
- Tous les messages WhatsApp Business API doivent utiliser des TEMPLATES PRÉ-APPROUVÉS
- Les templates sont créés dans Meta Business Manager
- Approbation Meta: 24-48h
- Les templates ne sont PAS pour la discussion libre, uniquement pour notifications

Documentation Meta:
https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-message-templates
"""

import httpx
from typing import Dict, Any, Optional, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class WhatsAppProvider:
    """
    Provider for WhatsApp Business Cloud API (Meta)
    
    Features:
    - Send template messages (pre-approved)
    - Media messages (images, documents, videos)
    - Interactive buttons
    - Delivery status tracking
    - Rate limiting (80 msg/sec)
    
    Limitations:
    - TOUS les messages doivent utiliser des templates approuvés
    - 24h window pour répondre aux messages entrants
    - Pas de messages promotionnels non-sollicités
    """
    
    def __init__(
        self,
        phone_number_id: str,
        access_token: str,
        api_version: str = "v21.0"
    ):
        """
        Initialize WhatsApp provider
        
        Args:
            phone_number_id: WhatsApp Business Phone Number ID (from Meta Business)
            access_token: Access token (90 days validity)
            api_version: Meta Graph API version
        """
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.api_version = api_version
        self.api_url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
        
    async def send(self, notification: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send WhatsApp template message
        
        Args:
            notification: Dict with keys:
                - recipient_phone: str (format: +225XXXXXXXXX)
                - template_name: str (nom du template Meta approuvé)
                - template_language: str (default: "fr")
                - template_params: List[str] (variables du template)
                - header_media: Dict (optional, image/video/document)
                - buttons: List[Dict] (optional, dynamic button URLs)
                
        Returns:
            Dict with success status, message_id (WAMID), and provider info
        """
        
        try:
            # Build WhatsApp payload
            payload = self._build_template_payload(notification)
            
            # Send via Meta Cloud API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.api_url,
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json"
                    },
                    json=payload,
                    timeout=30.0
                )
                
                # Handle response
                if response.status_code == 200:
                    data = response.json()
                    message_id = data["messages"][0]["id"]  # WAMID format
                    
                    logger.info(
                        f"WhatsApp message sent successfully",
                        extra={
                            "message_id": message_id,
                            "recipient": notification["recipient_phone"],
                            "template": notification["template_name"]
                        }
                    )
                    
                    return {
                        "success": True,
                        "message_id": message_id,
                        "provider": "whatsapp_cloud",
                        "sent_at": datetime.utcnow().isoformat(),
                        "response": data
                    }
                    
                else:
                    error_data = response.json()
                    error_msg = error_data.get("error", {}).get("message", "Unknown error")
                    error_code = error_data.get("error", {}).get("code", response.status_code)
                    
                    logger.error(
                        f"WhatsApp API error: {error_msg}",
                        extra={
                            "error_code": error_code,
                            "recipient": notification["recipient_phone"],
                            "template": notification["template_name"]
                        }
                    )
                    
                    return {
                        "success": False,
                        "error": error_msg,
                        "error_code": str(error_code),
                        "response": error_data
                    }
                    
        except httpx.TimeoutException:
            logger.error("WhatsApp API timeout")
            return {
                "success": False,
                "error": "WhatsApp Cloud API timeout after 30s",
                "error_code": "TIMEOUT"
            }
            
        except Exception as e:
            logger.exception("Unexpected error sending WhatsApp message")
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}",
                "error_code": "EXCEPTION"
            }
    
    def _build_template_payload(self, notification: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build WhatsApp template message payload
        
        Format Meta Cloud API:
        https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages#template-object
        """
        
        recipient_phone = notification["recipient_phone"]
        
        # Remove + prefix if present (Meta expects without +)
        if recipient_phone.startswith("+"):
            recipient_phone = recipient_phone[1:]
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_phone,
            "type": "template",
            "template": {
                "name": notification["template_name"],
                "language": {
                    "code": notification.get("template_language", "fr")
                }
            }
        }
        
        # Components (header, body, buttons)
        components = []
        
        # 1. HEADER (si image/video/document)
        if notification.get("header_media"):
            header_media = notification["header_media"]
            header_component = {
                "type": "header",
                "parameters": []
            }
            
            if header_media["type"] == "image":
                header_component["parameters"].append({
                    "type": "image",
                    "image": {
                        "link": header_media["url"]
                    }
                })
            elif header_media["type"] == "video":
                header_component["parameters"].append({
                    "type": "video",
                    "video": {
                        "link": header_media["url"]
                    }
                })
            elif header_media["type"] == "document":
                header_component["parameters"].append({
                    "type": "document",
                    "document": {
                        "link": header_media["url"],
                        "filename": header_media.get("filename", "document.pdf")
                    }
                })
            
            components.append(header_component)
        
        # 2. BODY (variables textuelles)
        if notification.get("template_params"):
            body_params = []
            for param in notification["template_params"]:
                body_params.append({
                    "type": "text",
                    "text": str(param)
                })
            
            components.append({
                "type": "body",
                "parameters": body_params
            })
        
        # 3. BUTTONS (URLs dynamiques)
        if notification.get("buttons"):
            for i, button in enumerate(notification["buttons"]):
                if button["type"] == "url" and button.get("url_suffix"):
                    components.append({
                        "type": "button",
                        "sub_type": "url",
                        "index": str(i),
                        "parameters": [
                            {
                                "type": "text",
                                "text": button["url_suffix"]
                            }
                        ]
                    })
        
        if components:
            payload["template"]["components"] = components
        
        return payload
    
    async def get_delivery_status(self, message_id: str) -> Dict[str, Any]:
        """
        Get WhatsApp message delivery status
        
        Statuses: sent, delivered, read, failed
        
        Note: Requires webhook configuration in Meta Business Manager
        """
        
        # Meta ne fournit pas d'API GET pour les statuts
        # Les statuts sont reçus via WEBHOOK uniquement
        # Voir: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/components
        
        return {
            "success": False,
            "error": "WhatsApp status requires webhook configuration. Check notification_logs table for webhook events.",
            "message": "Configure webhook URL in Meta Business Manager to receive delivery statuses"
        }
    
    async def send_text_message(
        self, 
        recipient_phone: str, 
        text: str
    ) -> Dict[str, Any]:
        """
        Send simple text message (only works within 24h window after user message)
        
        IMPORTANT: Cette méthode ne fonctionne QUE si :
        1. L'utilisateur a envoyé un message dans les dernières 24h
        2. OU vous avez une session active (conversation existante)
        
        Pour notifications proactives, utilisez TOUJOURS send() avec template
        """
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_phone.lstrip("+"),
            "type": "text",
            "text": {
                "preview_url": False,
                "body": text
            }
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.api_url,
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json"
                    },
                    json=payload,
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "success": True,
                        "message_id": data["messages"][0]["id"],
                        "provider": "whatsapp_cloud"
                    }
                else:
                    error_data = response.json()
                    return {
                        "success": False,
                        "error": error_data.get("error", {}).get("message", "Unknown error"),
                        "error_code": str(error_data.get("error", {}).get("code", response.status_code))
                    }
                    
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def send_media_message(
        self,
        recipient_phone: str,
        media_type: str,  # image, video, document, audio
        media_url: str,
        caption: Optional[str] = None,
        filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send media message (24h window required)
        
        Pour notifications proactives avec média, utilisez template avec header_media
        """
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_phone.lstrip("+"),
            "type": media_type,
            media_type: {
                "link": media_url
            }
        }
        
        if caption and media_type in ["image", "video"]:
            payload[media_type]["caption"] = caption
        
        if filename and media_type == "document":
            payload[media_type]["filename"] = filename
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.api_url,
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json"
                    },
                    json=payload,
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "success": True,
                        "message_id": data["messages"][0]["id"]
                    }
                else:
                    return {
                        "success": False,
                        "error": response.text
                    }
                    
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


# ═══════════════════════════════════════════════════════════════════════
#  GUIDE COMPLET: CRÉATION DE TEMPLATES WHATSAPP DANS META BUSINESS MANAGER
# ═══════════════════════════════════════════════════════════════════════

WHATSAPP_TEMPLATE_CREATION_GUIDE = """
╔══════════════════════════════════════════════════════════════════════╗
║  GUIDE COMPLET: CRÉER DES TEMPLATES WHATSAPP BUSINESS API           ║
╚══════════════════════════════════════════════════════════════════════╝

📍 URL: https://business.facebook.com/latest/whatsapp_manager/message_templates

══════════════════════════════════════════════════════════════════════
 INFORMATIONS REQUISES POUR CONFIGURER WHATSAPP BUSINESS
══════════════════════════════════════════════════════════════════════

Pour créer et gérer les templates, j'ai besoin de:

1. ✅ Phone Number ID (déjà fourni)
   → 1079505398586828

2. ❓ Access Token (à fournir ou regénérer)
   - Durée: 90 jours
   - Générer: business.facebook.com → WhatsApp → API Setup
   - Permissions requises:
     • whatsapp_business_messaging
     • whatsapp_business_management
   
3. ❓ WhatsApp Business Account ID (WABA ID)
   - Format: 10-15 chiffres
   - Trouvé dans: WhatsApp Manager → Settings → Business Info
   
4. ❓ Votre numéro WhatsApp Business
   - Format: +225XXXXXXXXX
   - Le numéro depuis lequel les messages seront envoyés
   - Doit être vérifié dans Meta Business Manager

5. ❓ Business Manager ID
   - Pour lier l'app et les permissions
   
══════════════════════════════════════════════════════════════════════
 ÉTAPES POUR CRÉER UN TEMPLATE WHATSAPP
══════════════════════════════════════════════════════════════════════

Étape 1: ACCÉDER À L'INTERFACE
------------------------------
1. Aller sur: https://business.facebook.com
2. Sélectionner votre Business Manager
3. Menu: WhatsApp Manager → Message templates
4. Cliquer "Create Template"

Étape 2: CHOISIR LA CATÉGORIE
------------------------------
Meta impose 3 catégories:

• MARKETING
  → Promotions, offres, nouveautés
  → Nécessite opt-in explicite de l'utilisateur
  → Exemple: "Nouvelle collection disponible"

• UTILITY
  → Notifications transactionnelles
  → Confirmations, mises à jour, rappels
  → Exemple: "Votre commande a été expédiée"

• AUTHENTICATION
  → Codes OTP, vérification
  → Uniquement pour authentification
  → Exemple: "Votre code de vérification: 123456"

⚠️ IMPORTANT: Choisir la mauvaise catégorie = refus automatique

Étape 3: NOMMER LE TEMPLATE
----------------------------
Règles Meta strictes:
• Minuscules uniquement
• Underscores autorisés (pas d'espaces)
• Lettres, chiffres, underscores
• Pas d'accents, caractères spéciaux

✅ BON: order_confirmation, shipping_update, new_product_launch
❌ MAUVAIS: Order-Confirmation, Commande!, nouvelle offre

Étape 4: SÉLECTIONNER LA LANGUE
--------------------------------
• Français (fr)
• Un template par langue (créer "order_confirmation_en" si besoin)

Étape 5: COMPOSER LE MESSAGE
-----------------------------

A. HEADER (Optionnel)
   3 types possibles:
   
   1) TEXTE (max 60 caractères)
      Exemple: "✅ Commande confirmée"
      
   2) IMAGE
      Format: JPG, PNG
      Taille: Max 5 MB
      Ratio: 1:1 ou 16:9 recommandé
      URL: Hébergement HTTPS requis
      
   3) VIDEO
      Format: MP4
      Taille: Max 16 MB
      
   4) DOCUMENT
      Format: PDF principalement
      Taille: Max 100 MB

B. BODY (Obligatoire, max 1024 caractères)
   
   Variables: {{1}}, {{2}}, {{3}}, etc.
   Maximum: 10 variables par template
   
   ✅ BON EXEMPLE:
   ```
   Bonjour {{1}},
   
   Votre commande #{{2}} a bien été enregistrée.
   
   📦 Articles: {{3}}
   💰 Total: {{4}}
   🚚 Livraison estimée: {{5}}
   
   Merci de votre confiance !
   — {{6}}
   ```
   
   ❌ MAUVAIS (refusé par Meta):
   ```
   ACHETEZ MAINTENANT !!! 🔥🔥🔥
   OFFRE LIMITÉE !!!
   CLIQUEZ ICI VITE !!!
   ```
   
   Raisons de refus:
   • Trop de MAJUSCULES
   • Trop d'emojis répétés
   • Langue agressive/urgente
   • Promesses exagérées
   • Fautes d'orthographe

C. FOOTER (Optionnel, max 60 caractères)
   
   Texte simple, sans variables
   Exemple: "Propulsé par ePerformance"

D. BUTTONS (Optionnel, max 10 boutons)
   
   3 types:
   
   1) CALL TO ACTION - URL
      Texte: max 25 caractères
      URL: Statique OU dynamique avec {{1}}
      
      Exemples:
      • "Voir ma commande" → https://eperformance.pro/orders/{{1}}
      • "Suivre le colis" → https://track.com/{{1}}
      
   2) CALL TO ACTION - PHONE
      Texte: max 25 caractères
      Numéro: Format international
      
      Exemple: "Nous appeler" → +2250151170666
      
   3) QUICK REPLY
      Texte: max 25 caractères
      Pas d'URL (juste pour réponse rapide)
      
      Exemples: "Oui", "Non merci", "Plus d'infos"

Étape 6: AJOUTER DES EXEMPLES (OBLIGATOIRE)
--------------------------------------------
Meta EXIGE des exemples concrets pour chaque variable

Si votre body est:
```
Bonjour {{1}}, votre commande #{{2}} pour {{3}} est confirmée.
```

Fournir:
• {{1}} = "Fatou"
• {{2}} = "CMD20260910-001"
• {{3}} = "2 articles (45 000 FCFA)"

⚠️ Les exemples doivent être RÉALISTES
❌ "test", "xxx", "123" → Refusé
✅ Vraies données d'exemple

Étape 7: SOUMETTRE POUR APPROBATION
------------------------------------
• Délai: 24-48h en moyenne
• Notification par email
• Statuts possibles:
  - PENDING: En attente
  - APPROVED: ✅ Prêt à utiliser
  - REJECTED: ❌ Refusé (avec raison)

Si refusé:
1. Lire attentivement la raison
2. Corriger (souvent: ton trop commercial, fautes, MAJUSCULES)
3. Resoumettre

══════════════════════════════════════════════════════════════════════
 10 TEMPLATES RECOMMANDÉS POUR EPERFORMANCE
══════════════════════════════════════════════════════════════════════

Voici les templates à créer EN PRIORITÉ (copier-coller dans Meta):

─────────────────────────────────────────────────────────────────────
1. ORDER_CONFIRMATION (Catégorie: UTILITY)
─────────────────────────────────────────────────────────────────────
Nom: order_confirmation
Langue: Français (fr)

Header: (Aucun, ou image logo boutique)

Body:
```
Bonjour {{1}},

Votre commande #{{2}} a bien été enregistrée chez {{3}}.

📦 Articles: {{4}}
💰 Total: {{5}}
🚚 Livraison estimée: {{6}}

Merci de votre confiance !
```

Footer: ePerformance

Buttons:
• [URL] "Suivre ma commande" → https://eperformance.pro/orders/{{1}}
• [PHONE] "Nous contacter" → +2250151170666

Exemples:
{{1}} = Fatou Kouassi
{{2}} = CMD20260910-001
{{3}} = La Belle Boutique
{{4}} = 2 articles
{{5}} = 45 000 FCFA
{{6}} = 2-3 jours

─────────────────────────────────────────────────────────────────────
2. SHIPPING_UPDATE (Catégorie: UTILITY)
─────────────────────────────────────────────────────────────────────
Nom: shipping_update
Langue: Français (fr)

Body:
```
📦 Votre colis est en route !

Commande: #{{1}}
Statut: {{2}}
Livraison prévue: {{3}}

Numéro de suivi: {{4}}
```

Buttons:
• [URL] "Suivre en temps réel" → https://track.com/{{1}}

Exemples:
{{1}} = CMD20260910-001
{{2}} = En transit vers Abidjan
{{3}} = Demain avant 18h
{{4}} = TRK-2026091012345

─────────────────────────────────────────────────────────────────────
3. PAYMENT_RECEIVED (Catégorie: UTILITY)
─────────────────────────────────────────────────────────────────────
Nom: payment_received
Langue: Français (fr)

Body:
```
✅ Paiement reçu

Bonjour {{1}},

Nous avons bien reçu votre paiement de {{2}}.

🧾 Référence: {{3}}
📅 Date: {{4}}

Votre reçu est disponible via le lien ci-dessous.
```

Buttons:
• [URL] "Télécharger le reçu" → https://eperformance.pro/receipts/{{1}}

Exemples:
{{1}} = Fatou
{{2}} = 45 000 FCFA
{{3}} = PAY-20260910-001
{{4}} = 10/09/2026 à 14:30

─────────────────────────────────────────────────────────────────────
4. ABANDONED_CART (Catégorie: MARKETING)
─────────────────────────────────────────────────────────────────────
Nom: abandoned_cart
Langue: Français (fr)

⚠️ MARKETING = Nécessite opt-in client

Body:
```
Bonjour {{1}},

Vous avez oublié des articles dans votre panier:

{{2}}

Total: {{3}}

🎁 Offre spéciale: {{4}}

Valable 24h uniquement.
```

Buttons:
• [URL] "Finaliser ma commande" → https://eperformance.pro/cart/{{1}}
• [QUICK_REPLY] "Non merci"

Exemples:
{{1}} = Fatou
{{2}} = • Robe rouge (taille M)\n• Sac à main noir
{{3}} = 35 000 FCFA
{{4}} = Livraison gratuite si vous finalisez maintenant

─────────────────────────────────────────────────────────────────────
5. APPOINTMENT_REMINDER (Catégorie: UTILITY)
─────────────────────────────────────────────────────────────────────
Nom: appointment_reminder
Langue: Français (fr)

Body:
```
📅 Rappel de rendez-vous

Bonjour {{1}},

Votre rendez-vous est prévu:

🕐 {{2}}
📍 {{3}}
👤 Avec: {{4}}

À bientôt !
```

Buttons:
• [URL] "Confirmer" → https://eperformance.pro/appointments/{{1}}/confirm
• [URL] "Annuler" → https://eperformance.pro/appointments/{{1}}/cancel

Exemples:
{{1}} = Fatou
{{2}} = Demain, 10/09/2026 à 15h00
{{3}} = Salon Belle Allure, Cocody
{{4}} = Marie (coiffeuse)

─────────────────────────────────────────────────────────────────────
6. PASSWORD_RESET (Catégorie: AUTHENTICATION)
─────────────────────────────────────────────────────────────────────
Nom: password_reset_otp
Langue: Français (fr)

Body:
```
🔐 Code de vérification

Bonjour {{1}},

Votre code de vérification ePerformance:

{{2}}

⏰ Valable 10 minutes.

Si vous n'avez pas demandé ce code, ignorez ce message.
```

Footer: ePerformance - Sécurité

Exemples:
{{1}} = Fatou
{{2}} = 847293

─────────────────────────────────────────────────────────────────────
7. WELCOME_MESSAGE (Catégorie: UTILITY)
─────────────────────────────────────────────────────────────────────
Nom: welcome_new_customer
Langue: Français (fr)

Header: (Image logo ePerformance)

Body:
```
Bienvenue {{1}} ! 🎉

Merci de rejoindre {{2}}.

Votre compte a été créé avec succès.

Commencez dès maintenant à profiter de nos services.
```

Buttons:
• [URL] "Découvrir" → https://eperformance.pro/welcome

Exemples:
{{1}} = Fatou
{{2}} = ePerformance

─────────────────────────────────────────────────────────────────────
8. DELIVERY_CONFIRMATION (Catégorie: UTILITY)
─────────────────────────────────────────────────────────────────────
Nom: delivery_confirmed
Langue: Français (fr)

Body:
```
✅ Livraison effectuée

Bonjour {{1}},

Votre commande #{{2}} a été livrée avec succès.

📍 Livrée à: {{3}}
🕐 Le: {{4}}

Nous espérons que vous êtes satisfait !
```

Buttons:
• [URL] "Donner mon avis" → https://eperformance.pro/reviews/{{1}}

Exemples:
{{1}} = Fatou
{{2}} = CMD20260910-001
{{3}} = Cocody, Abidjan
{{4}} = 10/09/2026 à 16:45

─────────────────────────────────────────────────────────────────────
9. ACCOUNT_ALERT (Catégorie: UTILITY)
─────────────────────────────────────────────────────────────────────
Nom: account_security_alert
Langue: Français (fr)

Body:
```
⚠️ Alerte de sécurité

Bonjour {{1}},

Une activité inhabituelle a été détectée sur votre compte:

{{2}}

📅 {{3}}
📍 {{4}}

Si ce n'est pas vous, sécurisez votre compte immédiatement.
```

Buttons:
• [URL] "Sécuriser mon compte" → https://eperformance.pro/security

Exemples:
{{1}} = Fatou
{{2}} = Nouvelle connexion depuis un appareil inconnu
{{3}} = 10/09/2026 à 14:30
{{4}} = Abidjan, Côte d'Ivoire

─────────────────────────────────────────────────────────────────────
10. SUBSCRIPTION_RENEWAL (Catégorie: UTILITY)
─────────────────────────────────────────────────────────────────────
Nom: subscription_renewal_reminder
Langue: Français (fr)

Body:
```
🔔 Renouvellement d'abonnement

Bonjour {{1}},

Votre abonnement {{2}} expire le {{3}}.

💰 Montant: {{4}}

Renouvelez dès maintenant pour continuer à profiter de nos services.
```

Buttons:
• [URL] "Renouveler" → https://eperformance.pro/subscriptions/{{1}}/renew

Exemples:
{{1}} = Fatou
{{2}} = Plan Croissance
{{3}} = 15/09/2026
{{4}} = 50 000 FCFA/mois

══════════════════════════════════════════════════════════════════════
 CHECKLIST AVANT SOUMISSION
══════════════════════════════════════════════════════════════════════

Pour MAXIMISER les chances d'approbation:

✅ Catégorie correcte (UTILITY pour transactionnel, MARKETING pour promo)
✅ Nom en snake_case (minuscules + underscores)
✅ Ton professionnel (pas d'exclamations excessives)
✅ Orthographe parfaite
✅ Exemples réalistes (pas "test" ou "xxx")
✅ Variables correctes ({{1}}, {{2}}, pas {{nom}})
✅ Emojis modérés (1-2 par section max)
✅ Pas de promesses exagérées
✅ Respect des limites (1024 chars body, 60 chars header/footer)
✅ URLs valides dans les boutons
✅ Numéro de téléphone au format international

══════════════════════════════════════════════════════════════════════
 APRÈS APPROBATION: UTILISATION DANS LE CODE
══════════════════════════════════════════════════════════════════════

Une fois approuvé, utiliser comme ceci:

```python
from backend.communication.providers.whatsapp_provider import WhatsAppProvider

provider = WhatsAppProvider(
    phone_number_id="1079505398586828",
    access_token="VOTRE_ACCESS_TOKEN"
)

# Envoyer confirmation de commande
result = await provider.send({
    "recipient_phone": "+2250701234567",
    "template_name": "order_confirmation",
    "template_language": "fr",
    "template_params": [
        "Fatou Kouassi",           # {{1}}
        "CMD20260910-001",         # {{2}}
        "La Belle Boutique",       # {{3}}
        "2 articles",              # {{4}}
        "45 000 FCFA",             # {{5}}
        "2-3 jours"                # {{6}}
    ],
    "buttons": [
        {
            "type": "url",
            "url_suffix": "CMD20260910-001"  # Pour URL dynamique
        }
    ]
})

if result["success"]:
    print(f"✅ Message envoyé: {result['message_id']}")
else:
    print(f"❌ Erreur: {result['error']}")
```

══════════════════════════════════════════════════════════════════════
 INFORMATIONS À FOURNIR
══════════════════════════════════════════════════════════════════════

Pour que je puisse finaliser l'intégration, fournissez:

1. ✅ Phone Number ID: 1079505398586828 (déjà fourni)

2. ❓ Access Token (à générer)
   Générer sur: https://business.facebook.com/settings/whatsapp-business-accounts/
   → Durée: 90 jours
   → À renouveler périodiquement

3. ❓ WhatsApp Business Account ID (WABA ID)
   Trouvé dans: WhatsApp Manager → Settings

4. ❓ Votre numéro WhatsApp Business professionnel
   Format: +225XXXXXXXXX
   (Le numéro depuis lequel les notifications seront envoyées)

5. ❓ Souhaitez-vous que je vous aide à configurer le webhook
   pour recevoir les statuts de livraison et les messages entrants?
   
   Webhook URL suggéré: https://api.eperformance.pro/webhooks/whatsapp
   (Je peux créer ce endpoint si besoin)

╚══════════════════════════════════════════════════════════════════════╝
"""

# Guide disponible via WHATSAPP_TEMPLATE_CREATION_GUIDE (commenté le print pour éviter affichage à l'import)
# print(WHATSAPP_TEMPLATE_CREATION_GUIDE)

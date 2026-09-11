"""
ActionExecutor - Exécution des actions post-réponse
Phase 1-J3 : Actions concrètes déclenchées par le chatbot

Actions supportées :
1. lead_capture : Capturer un lead (nom, tel, email) → DB + Notification
2. create_diagnostic : Créer un diagnostic en DB après collecte données
3. schedule_callback : Programmer un rappel commercial
4. escalate_to_human : Escalader vers un conseiller humain
5. send_resource : Envoyer un document/lien (ebook, formation, etc.)
6. track_conversion : Tracker une conversion (inscription, achat, etc.)
"""
from typing import Dict, Optional, List, Any
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import re
import os

from .models import ChatbotLead, ChatbotConversation

# Import NotificationService (Phase 1-S1.3)
try:
    from ..communication.notification_service import NotificationService
except ImportError:
    NotificationService = None


class ActionExecutor:
    """
    Exécuteur d'actions chatbot
    Déclenche des actions concrètes basées sur les réponses générées
    """
    
    # Types d'actions supportées
    ACTION_TYPES = [
        'lead_capture',
        'create_diagnostic',
        'schedule_callback',
        'escalate_to_human',
        'send_resource',
        'track_conversion'
    ]
    
    def __init__(self, db: Session):
        """
        Initialiser l'executor
        
        Args:
            db: Session SQLAlchemy
        """
        self.db = db
        
        # Configuration NotificationService depuis variables d'environnement
        if NotificationService:
            email_config = {
                'api_key': os.getenv('BREVO_API_KEY', ''),
                'sender_email': os.getenv('BREVO_SENDER_EMAIL', 'notifications@eperformance.pro'),
                'sender_name': os.getenv('BREVO_SENDER_NAME', 'ePerformance')
            }
            
            whatsapp_config = {
                'access_token': os.getenv('WHATSAPP_ACCESS_TOKEN', ''),
                'phone_number_id': os.getenv('WHATSAPP_PHONE_NUMBER_ID', '')
            }
            
            telegram_config = {
                'bot_token': os.getenv('TELEGRAM_BOT_TOKEN', ''),
                'admin_chat_id': os.getenv('TELEGRAM_ADMIN_CHAT_ID', '')
            }
            
            # Activer seulement si au moins une config est présente
            if email_config['api_key'] or telegram_config['bot_token']:
                try:
                    self.notification_service = NotificationService(
                        db=db,
                        email_config=email_config,
                        whatsapp_config=whatsapp_config,
                        telegram_config=telegram_config
                    )
                    print("✅ NotificationService activé (Email, WhatsApp, Telegram)")
                except Exception as e:
                    print(f"⚠️  NotificationService init failed: {e}")
                    self.notification_service = None
            else:
                print("⚠️  NotificationService désactivé (aucune clé API)")
                self.notification_service = None
        else:
            print("⚠️  NotificationService module non disponible")
            self.notification_service = None
    
    async def execute_actions(
        self,
        actions: List[Dict[str, Any]],
        conversation_id: str,
        site_id: str,
        message: str,
        response: str,
        context: Dict
    ) -> List[Dict[str, Any]]:
        """
        Exécuter une liste d'actions
        
        Args:
            actions: Liste d'actions à exécuter
                Format : [{"type": "lead_capture", "data": {...}}, ...]
            conversation_id: ID de la conversation
            site_id: ID du site
            message: Message utilisateur
            response: Réponse générée
            context: Context complet
        
        Returns:
            Liste des résultats d'exécution
            [{"action": "lead_capture", "success": True, "result": {...}}, ...]
        """
        results = []
        
        for action in actions:
            action_type = action.get('type')
            action_data = action.get('data', {})
            
            if action_type not in self.ACTION_TYPES:
                results.append({
                    'action': action_type,
                    'success': False,
                    'error': f'Unknown action type: {action_type}'
                })
                continue
            
            try:
                # Exécuter l'action selon son type
                if action_type == 'lead_capture':
                    result = await self._execute_lead_capture(
                        conversation_id, site_id, action_data, message, response, context
                    )
                
                elif action_type == 'create_diagnostic':
                    result = await self._execute_create_diagnostic(
                        conversation_id, site_id, action_data, context
                    )
                
                elif action_type == 'schedule_callback':
                    result = await self._execute_schedule_callback(
                        conversation_id, site_id, action_data, context
                    )
                
                elif action_type == 'escalate_to_human':
                    result = await self._execute_escalate_to_human(
                        conversation_id, site_id, action_data, message, context
                    )
                
                elif action_type == 'send_resource':
                    result = await self._execute_send_resource(
                        conversation_id, site_id, action_data, context
                    )
                
                elif action_type == 'track_conversion':
                    result = await self._execute_track_conversion(
                        conversation_id, site_id, action_data, context
                    )
                
                else:
                    result = {'success': False, 'error': 'Not implemented'}
                
                results.append({
                    'action': action_type,
                    'success': result.get('success', False),
                    'result': result
                })
            
            except Exception as e:
                self.db.rollback()
                print(f"❌ Error executing action {action_type}: {e}")
                import traceback
                traceback.print_exc()
                
                results.append({
                    'action': action_type,
                    'success': False,
                    'error': str(e)
                })
        
        return results
    
    async def _execute_lead_capture(
        self,
        conversation_id: str,
        site_id: str,
        action_data: Dict,
        message: str,
        response: str,
        context: Dict
    ) -> Dict:
        """
        ACTION : Capturer un lead
        
        1. Sauvegarder en chatbot_leads
        2. Mettre à jour conversation.lead_captured = True
        3. Envoyer notification Telegram CRITICAL + Email
        
        action_data doit contenir :
        - name : Nom du lead
        - phone : Téléphone (optionnel mais recommandé)
        - email : Email (optionnel)
        - intent : Intent de capture (ex: "order_intent")
        - notes : Notes additionnelles (optionnel)
        """
        try:
            # Valider les données minimales
            lead_name = action_data.get('name', '').strip()
            lead_phone = action_data.get('phone', '').strip()
            lead_email = action_data.get('email', '').strip()
            
            if not lead_name:
                return {'success': False, 'error': 'Missing lead name'}
            
            # Créer le lead en DB
            lead = ChatbotLead(
                conversation_id=conversation_id,
                site_id=site_id,
                lead_name=lead_name,
                lead_phone=lead_phone or None,
                lead_email=lead_email or None,
                lead_intent=action_data.get('intent', 'unknown'),
                lead_source='chatbot',
                lead_status='new',
                lead_temperature='hot',  # Lead capturé = hot par défaut
                capture_message=message,
                capture_response=response,
                notes=action_data.get('notes', '')
            )
            
            self.db.add(lead)
            self.db.commit()
            self.db.refresh(lead)
            
            # Mettre à jour la conversation
            conversation = self.db.query(ChatbotConversation).filter_by(
                conversation_id=conversation_id
            ).first()
            
            if conversation:
                conversation.lead_captured = True
                conversation.lead_id = lead.id
                self.db.commit()
            
            # Envoyer les notifications
            notification_results = []
            
            if self.notification_service:
                # Notification Telegram CRITICAL (immédiate)
                telegram_result = await self._send_telegram_notification(
                    lead=lead,
                    conversation_id=conversation_id,
                    site_id=site_id
                )
                notification_results.append({
                    'channel': 'telegram',
                    'success': telegram_result.get('success', False)
                })
                
                # Notification Email (récap)
                email_result = await self._send_email_notification(
                    lead=lead,
                    conversation_id=conversation_id,
                    site_id=site_id
                )
                notification_results.append({
                    'channel': 'email',
                    'success': email_result.get('success', False)
                })
            
            return {
                'success': True,
                'lead_id': lead.id,
                'lead_name': lead_name,
                'notifications_sent': notification_results
            }
        
        except Exception as e:
            self.db.rollback()
            print(f"❌ Lead capture failed: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _send_telegram_notification(
        self,
        lead: ChatbotLead,
        conversation_id: str,
        site_id: str
    ) -> Dict:
        """
        Envoyer notification Telegram CRITICAL pour lead chaud
        """
        if not self.notification_service:
            return {'success': False, 'error': 'NotificationService not available'}
        
        try:
            # Template message
            message = f"""
🔥 **LEAD CHAUD - Chatbot IA**

👤 **Nom** : {lead.lead_name}
📞 **Tél** : {lead.lead_phone or 'Non renseigné'}
📧 **Email** : {lead.lead_email or 'Non renseigné'}

🎯 **Intent** : {lead.lead_intent}
🌡️ **Température** : {lead.lead_temperature.upper()}
🌐 **Site** : {site_id}

💬 **Message capture** :
_{lead.capture_message[:200]}_

⏰ **À contacter IMMÉDIATEMENT** (lead chaud !)

🔗 Conversation : /admin/chatbot/conversations/{conversation_id}
"""
            
            # Envoyer via NotificationService
            result = await self.notification_service.send_notification(
                channel='telegram',
                recipient='team',  # Canal équipe commercial
                template='chatbot_lead_hot',
                priority='CRITICAL',
                data={
                    'lead_name': lead.lead_name,
                    'lead_phone': lead.lead_phone,
                    'lead_email': lead.lead_email,
                    'intent': lead.lead_intent,
                    'conversation_url': f"/admin/chatbot/conversations/{conversation_id}",
                    'message': message
                }
            )
            
            return {'success': True, 'result': result}
        
        except Exception as e:
            print(f"❌ Telegram notification failed: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _send_email_notification(
        self,
        lead: ChatbotLead,
        conversation_id: str,
        site_id: str
    ) -> Dict:
        """
        Envoyer notification Email récap lead
        """
        if not self.notification_service:
            return {'success': False, 'error': 'NotificationService not available'}
        
        try:
            # Template email
            subject = f"[Chatbot] Nouveau lead : {lead.lead_name}"
            
            # Envoyer via NotificationService
            result = await self.notification_service.send_notification(
                channel='email',
                recipient='commercial@eperformance.pro',  # TODO: config dynamique
                template='chatbot_lead_recap',
                priority='HIGH',
                data={
                    'lead_name': lead.lead_name,
                    'lead_phone': lead.lead_phone,
                    'lead_email': lead.lead_email,
                    'intent': lead.lead_intent,
                    'temperature': lead.lead_temperature,
                    'site_id': site_id,
                    'conversation_url': f"https://admin.eperformance.pro/chatbot/conversations/{conversation_id}",
                    'subject': subject
                }
            )
            
            return {'success': True, 'result': result}
        
        except Exception as e:
            print(f"❌ Email notification failed: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _execute_create_diagnostic(
        self,
        conversation_id: str,
        site_id: str,
        action_data: Dict,
        context: Dict
    ) -> Dict:
        """
        ACTION : Créer un diagnostic business
        
        action_data doit contenir :
        - budget_pub_mensuel : Budget publicitaire mensuel
        - clients_acquis_mois : Nombre de clients acquis/mois
        - marge_moyenne : Marge moyenne par client (optionnel)
        - process_conversion : Description du processus actuel
        """
        try:
            # Extraire les données
            budget = action_data.get('budget_pub_mensuel', 0)
            clients = action_data.get('clients_acquis_mois', 0)
            marge = action_data.get('marge_moyenne', 0)
            
            # Calculer le CAC
            cac = budget / clients if clients > 0 else 0
            
            # Calculer le LTV (simplifié)
            ltv = marge * 3  # Hypothèse : 3 achats en moyenne
            
            # Identifier les failles
            failles = []
            if cac > ltv * 0.3:
                failles.append("CAC trop élevé (>30% du LTV)")
            if clients < 10:
                failles.append("Volume d'acquisition insuffisant")
            if marge < 50000:
                failles.append("Marge moyenne faible")
            
            # TODO: Sauvegarder en table diagnostics (à créer)
            # Pour l'instant, juste retourner le résultat
            
            diagnostic_result = {
                'cac': cac,
                'ltv': ltv,
                'marge': marge,
                'ratio_cac_ltv': (cac / ltv * 100) if ltv > 0 else 0,
                'failles': failles,
                'score_sante': 100 - len(failles) * 25  # Score simplifié
            }
            
            return {
                'success': True,
                'diagnostic': diagnostic_result
            }
        
        except Exception as e:
            self.db.rollback()
            print(f"❌ Diagnostic creation failed: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _execute_schedule_callback(
        self,
        conversation_id: str,
        site_id: str,
        action_data: Dict,
        context: Dict
    ) -> Dict:
        """
        ACTION : Programmer un rappel commercial
        
        action_data doit contenir :
        - callback_date : Date/heure souhaitée (ISO format ou texte)
        - callback_reason : Raison du rappel
        """
        try:
            callback_date_str = action_data.get('callback_date', '')
            callback_reason = action_data.get('callback_reason', 'Demande de rappel chatbot')
            
            # Parser la date (simplifiée)
            # TODO: Parsing intelligent de dates naturelles ("demain 14h", "dans 2 jours", etc.)
            callback_date = datetime.utcnow() + timedelta(hours=24)  # Par défaut : dans 24h
            
            # TODO: Créer une tâche/reminder en DB
            # Pour l'instant, juste notification
            
            if self.notification_service:
                await self.notification_service.send_notification(
                    channel='telegram',
                    recipient='team',
                    template='chatbot_callback_scheduled',
                    priority='NORMAL',
                    data={
                        'conversation_id': conversation_id,
                        'callback_date': callback_date.isoformat(),
                        'callback_reason': callback_reason
                    }
                )
            
            return {
                'success': True,
                'callback_date': callback_date.isoformat(),
                'callback_reason': callback_reason
            }
        
        except Exception as e:
            self.db.rollback()
            print(f"❌ Callback scheduling failed: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _execute_escalate_to_human(
        self,
        conversation_id: str,
        site_id: str,
        action_data: Dict,
        message: str,
        context: Dict
    ) -> Dict:
        """
        ACTION : Escalader vers un conseiller humain
        
        1. Marquer la conversation comme "needs_human"
        2. Notifier l'équipe
        3. Retourner un message d'attente
        """
        try:
            escalation_reason = action_data.get('reason', 'Complex query')
            
            # Mettre à jour la conversation
            conversation = self.db.query(ChatbotConversation).filter_by(
                conversation_id=conversation_id
            ).first()
            
            if conversation:
                conversation.status = 'needs_human'
                conversation.escalation_reason = escalation_reason
                conversation.escalated_at = datetime.utcnow()
                self.db.commit()
            
            # Notifier l'équipe
            if self.notification_service:
                await self.notification_service.send_notification(
                    channel='telegram',
                    recipient='support',
                    template='chatbot_escalation',
                    priority='HIGH',
                    data={
                        'conversation_id': conversation_id,
                        'reason': escalation_reason,
                        'last_message': message[:200]
                    }
                )
            
            return {
                'success': True,
                'escalation_reason': escalation_reason,
                'message': "Un conseiller va prendre le relais sous peu."
            }
        
        except Exception as e:
            self.db.rollback()
            print(f"❌ Escalation failed: {e}")
            return {'success': False, 'error': str(e)}
            return {'success': False, 'error': str(e)}
    
    async def _execute_send_resource(
        self,
        conversation_id: str,
        site_id: str,
        action_data: Dict,
        context: Dict
    ) -> Dict:
        """
        ACTION : Envoyer une ressource (lien, document, vidéo)
        
        action_data doit contenir :
        - resource_type : Type de ressource (ebook, video, article, etc.)
        - resource_url : URL de la ressource
        - resource_title : Titre de la ressource
        """
        try:
            resource_type = action_data.get('resource_type', 'link')
            resource_url = action_data.get('resource_url', '')
            resource_title = action_data.get('resource_title', 'Ressource')
            
            # TODO: Logger l'envoi de ressource pour analytics
            
            return {
                'success': True,
                'resource_type': resource_type,
                'resource_url': resource_url,
                'resource_title': resource_title,
                'message': f"📚 {resource_title} : {resource_url}"
            }
        
        except Exception as e:
            self.db.rollback()
            print(f"❌ Send resource failed: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _execute_track_conversion(
        self,
        conversation_id: str,
        site_id: str,
        action_data: Dict,
        context: Dict
    ) -> Dict:
        """
        ACTION : Tracker une conversion
        
        action_data doit contenir :
        - conversion_type : Type de conversion (signup, purchase, booking, etc.)
        - conversion_value : Valeur monétaire (optionnel)
        """
        try:
            conversion_type = action_data.get('conversion_type', 'unknown')
            conversion_value = action_data.get('conversion_value', 0)
            
            # TODO: Créer un event analytics spécifique
            # Pour l'instant, juste logger
            
            print(f"✅ Conversion tracked: {conversion_type} (value: {conversion_value})")
            
            return {
                'success': True,
                'conversion_type': conversion_type,
                'conversion_value': conversion_value
            }
        
        except Exception as e:
            self.db.rollback()
            print(f"❌ Track conversion failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def detect_actions_in_response(
        self,
        response: str,
        message: str,
        intent: str,
        context: Dict
    ) -> List[Dict[str, Any]]:
        """
        Détecter automatiquement les actions à exécuter
        basées sur le contenu de la réponse et l'intent
        
        Patterns :
        - Si réponse contient un téléphone/email → lead_capture
        - Si intent = "order_intent" → lead_capture
        - Si réponse contient "diagnostic" + données → create_diagnostic
        
        Returns:
            Liste d'actions détectées
        """
        actions = []
        
        # Détection lead capture (email/téléphone dans le message utilisateur)
        if self._detect_contact_info(message):
            contact_info = self._extract_contact_info(message)
            if contact_info.get('name') or contact_info.get('phone') or contact_info.get('email'):
                actions.append({
                    'type': 'lead_capture',
                    'data': {
                        'name': contact_info.get('name', 'Lead Chatbot'),
                        'phone': contact_info.get('phone'),
                        'email': contact_info.get('email'),
                        'intent': intent,
                        'notes': f"Auto-détecté depuis message: {message[:100]}"
                    }
                })
        
        # Intent spécifiques → actions automatiques
        if intent == 'order_intent' and not actions:
            # Si order intent mais pas de contact détecté, proposer de demander
            # (l'agent devrait demander dans sa réponse)
            pass
        
        return actions
    
    def _detect_contact_info(self, text: str) -> bool:
        """Détecter si le texte contient des infos de contact"""
        # Patterns téléphone (africain principalement)
        phone_patterns = [
            r'\+?\d{10,}',  # 10+ chiffres
            r'\d{2}[-.\s]?\d{2}[-.\s]?\d{2}[-.\s]?\d{2}',  # Format XX XX XX XX
        ]
        
        # Pattern email
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        
        for pattern in phone_patterns:
            if re.search(pattern, text):
                return True
        
        if re.search(email_pattern, text):
            return True
        
        return False
    
    def _extract_contact_info(self, text: str) -> Dict[str, Optional[str]]:
        """Extraire les infos de contact du texte"""
        info = {
            'name': None,
            'phone': None,
            'email': None
        }
        
        # Extraire email
        email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
        if email_match:
            info['email'] = email_match.group(0)
        
        # Extraire téléphone (simplifié)
        phone_match = re.search(r'\+?\d{10,}', text)
        if phone_match:
            info['phone'] = phone_match.group(0)
        
        # Extraire nom (très basique, patterns courants)
        name_patterns = [
            r"je\s+m['\"]?appelle\s+([A-Z][a-zà-ÿ]+(?:\s+[A-Z][a-zà-ÿ]+)?)",
            r"mon\s+nom\s+est\s+([A-Z][a-zà-ÿ]+(?:\s+[A-Z][a-zà-ÿ]+)?)",
            r"c['\"]?est\s+([A-Z][a-zà-ÿ]+(?:\s+[A-Z][a-zà-ÿ]+)?)",
        ]
        
        for pattern in name_patterns:
            name_match = re.search(pattern, text, re.IGNORECASE)
            if name_match:
                info['name'] = name_match.group(1)
                break
        
        return info

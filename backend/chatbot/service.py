"""
ChatbotService - Orchestrateur principal du chatbot
Phase 1-S1.4 : Pipeline complet de traitement des messages

Pipeline :
1. Load context (ContextBuilder)
2. Detect intent (IntentDetector)
3. Route to agent (AgentRouter)
4. Generate response (ResponseGenerator)
5. Execute actions (ActionExecutor)
6. Save to DB
7. Track analytics
"""
from typing import Dict, Optional, List
from sqlalchemy.orm import Session
from datetime import datetime
import uuid
import time

from .intent_detector import IntentDetector
from .context_builder import ContextBuilder
from .agent_router import AgentRouter
from .response_generator import ResponseGenerator
from .action_executor import ActionExecutor
from .models import (
    ChatbotConversation,
    ChatbotMessage,
    ChatbotAnalytics
)


class ChatbotService:
    """
    Service principal du chatbot
    Orchestrateur du pipeline complet de traitement
    """
    
    def __init__(self, db: Session, agents_dir: str = None, config_path: str = None):
        """
        Initialiser le service chatbot
        
        Args:
            db: Session SQLAlchemy
            agents_dir: Path vers dossier agents/ (optionnel)
            config_path: Path vers config_ia.json (optionnel)
        """
        from pathlib import Path
        
        self.db = db
        self.intent_detector = IntentDetector()
        self.context_builder = ContextBuilder(db)
        self.agent_router = AgentRouter()
        
        # Déterminer agents_dir
        if not agents_dir:
            # Chercher dans plusieurs emplacements
            possible_paths = [
                Path(__file__).parent / "agents",
                Path(__file__).parent.parent / "agents",
                Path("/home/ballo/OX6A/unified_ia_system/backend/agents"),
            ]
            for path in possible_paths:
                if path.exists():
                    agents_dir = path
                    break
            
            if not agents_dir:
                agents_dir = Path(__file__).parent / "agents"
        
        self.response_generator = ResponseGenerator(agents_dir=agents_dir, config_path=config_path)
        self.action_executor = ActionExecutor(db)
    
    async def process_message(
        self,
        site_id: str,
        message: str,
        conversation_id: Optional[str] = None,
        user_id: Optional[int] = None,
        visitor_info: Optional[Dict] = None,
        message_history: Optional[List[Dict]] = None
    ) -> Dict:
        """
        Traiter un message utilisateur (pipeline complet)
        
        Args:
            site_id: ID du site (multi-tenant)
            message: Message utilisateur
            conversation_id: ID conversation (généré si None)
            user_id: ID utilisateur si connecté
            visitor_info: Infos visiteur (browser, IP, etc.)
            message_history: Historique fourni par le client
        
        Returns:
            {
                'conversation_id': str,
                'response': str,
                'intent': str,
                'intent_confidence': float,
                'agent_used': str,
                'suggestions': List[str],
                'actions': List[Dict],
                'processing_time_ms': int
            }
        """
        start_time = time.time()
        
        # Générer conversation_id si nouvelle conversation
        if not conversation_id:
            conversation_id = self._generate_conversation_id()
            is_new_conversation = True
        else:
            is_new_conversation = False
        
        try:
            # 1. Charger/créer la conversation
            conversation = await self._get_or_create_conversation(
                conversation_id=conversation_id,
                site_id=site_id,
                user_id=user_id,
                visitor_info=visitor_info
            )
            
            # 2. Sauvegarder le message utilisateur
            user_message = self._save_message(
                conversation_id=conversation_id,
                role='user',
                content=message
            )
            
            # 3. Build context (historique + user profile + diagnostics + site config)
            context = self.context_builder.build_context(
                conversation_id=conversation_id,
                site_id=site_id,
                user_id=user_id,
                message_history=message_history,
                visitor_info=visitor_info
            )
            
            # 4. Detect intent
            intent, intent_confidence, intent_metadata = self.intent_detector.detect(
                message=message,
                context=context
            )
            
            # 5. Route to agent (Phase 1-J3)
            agent_key, agent_metadata = self.agent_router.route(
                intent=intent,
                context=context,
                intent_metadata=intent_metadata
            )
            
            # 6. Generate response (Phase 1-J3)
            response_text, generation_metadata = await self.response_generator.generate_response(
                agent_key=agent_key,
                agent_metadata=agent_metadata,
                message=message,
                context=context,
                intent=intent,
                intent_metadata=intent_metadata
            )
            
            # 7. Detect and execute actions (Phase 1-J3)
            detected_actions = self.action_executor.detect_actions_in_response(
                response=response_text,
                message=message,
                intent=intent,
                context=context
            )
            
            actions_executed = []
            if detected_actions:
                actions_executed = await self.action_executor.execute_actions(
                    actions=detected_actions,
                    conversation_id=conversation_id,
                    site_id=site_id,
                    message=message,
                    response=response_text,
                    context=context
                )
            
            # Agent utilisé et suggestions
            agent_used = agent_key
            suggestions = self._generate_suggestions(intent)
            
            # 8. Sauvegarder la réponse assistant
            assistant_message = self._save_message(
                conversation_id=conversation_id,
                role='assistant',
                content=response_text,
                intent=intent,
                intent_confidence=intent_confidence,
                agent_used=agent_used,
                suggestions=suggestions,
                actions_executed=actions_executed,
                context_data=context,
                llm_provider=generation_metadata.get('llm_provider'),
                llm_tokens_used=generation_metadata.get('llm_tokens_used')
            )
            
            # 9. Mettre à jour la conversation
            self._update_conversation(conversation_id)
            
            # 10. Track analytics
            self._track_event(
                site_id=site_id,
                conversation_id=conversation_id,
                event_type='message_processed',
                event_category='engagement',
                event_data={
                    'intent': intent,
                    'intent_confidence': intent_confidence,
                    'is_new_conversation': is_new_conversation
                },
                visitor_info=visitor_info
            )
            
            # Calculer le temps de traitement
            processing_time_ms = int((time.time() - start_time) * 1000)
            
            return {
                'conversation_id': conversation_id,
                'response': response_text,
                'intent': intent,
                'intent_confidence': intent_confidence,
                'agent_used': agent_used,
                'suggestions': suggestions,
                'actions': actions_executed,
                'processing_time_ms': processing_time_ms,
                'context_sources': context.get('sources', [])
            }
        
        except Exception as e:
            # Log error et retourner une réponse d'erreur
            print(f"Error processing message: {e}")
            import traceback
            traceback.print_exc()
            
            self._track_event(
                site_id=site_id,
                conversation_id=conversation_id or 'unknown',
                event_type='error',
                event_category='error',
                event_data={
                    'error': str(e),
                    'message_preview': message[:100]
                },
                visitor_info=visitor_info
            )
            
            return {
                'conversation_id': conversation_id or 'error',
                'response': "Désolé, une erreur s'est produite. Notre équipe a été notifiée. Pouvez-vous reformuler votre question ?",
                'intent': 'error',
                'intent_confidence': 0.0,
                'agent_used': 'error_handler',
                'suggestions': ['Contacter le support', 'Réessayer'],
                'actions': [],
                'processing_time_ms': int((time.time() - start_time) * 1000),
                'error': str(e)
            }
    
    async def _get_or_create_conversation(
        self,
        conversation_id: str,
        site_id: str,
        user_id: Optional[int],
        visitor_info: Optional[Dict]
    ) -> ChatbotConversation:
        """Charger ou créer une conversation"""
        # Essayer de charger
        conversation = self.db.query(ChatbotConversation).filter_by(
            conversation_id=conversation_id
        ).first()
        
        if conversation:
            return conversation
        
        # Créer nouvelle conversation
        conversation = ChatbotConversation(
            conversation_id=conversation_id,
            site_id=site_id,
            user_id=user_id,
            visitor_ip=visitor_info.get('ip') if visitor_info else None,
            visitor_info=visitor_info,
            status='active'
        )
        
        self.db.add(conversation)
        self.db.commit()
        
        # Track analytics
        self._track_event(
            site_id=site_id,
            conversation_id=conversation_id,
            event_type='conversation_start',
            event_category='engagement',
            event_data={'user_id': user_id},
            visitor_info=visitor_info
        )
        
        return conversation
    
    def _save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        intent: Optional[str] = None,
        intent_confidence: Optional[float] = None,
        agent_used: Optional[str] = None,
        suggestions: Optional[List[str]] = None,
        actions_executed: Optional[List[Dict]] = None,
        context_data: Optional[Dict] = None,
        llm_provider: Optional[str] = None,
        llm_tokens_used: Optional[int] = None
    ) -> ChatbotMessage:
        """Sauvegarder un message dans la DB"""
        message = ChatbotMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            intent=intent,
            intent_confidence=intent_confidence,
            agent_used=agent_used,
            suggestions=suggestions,
            actions_executed=actions_executed,
            context_data=context_data,
            llm_provider=llm_provider,
            llm_tokens_used=llm_tokens_used
        )
        
        self.db.add(message)
        self.db.commit()
        
        return message
    
    def _update_conversation(self, conversation_id: str):
        """Mettre à jour les métriques de la conversation"""
        conversation = self.db.query(ChatbotConversation).filter_by(
            conversation_id=conversation_id
        ).first()
        
        if conversation:
            conversation.message_count += 2  # user + assistant
            conversation.last_message_at = datetime.utcnow()
            self.db.commit()
    
    def _track_event(
        self,
        site_id: str,
        conversation_id: str,
        event_type: str,
        event_category: str,
        event_data: Optional[Dict] = None,
        visitor_info: Optional[Dict] = None
    ):
        """Tracker un event analytics"""
        event = ChatbotAnalytics(
            site_id=site_id,
            conversation_id=conversation_id,
            event_type=event_type,
            event_category=event_category,
            event_data=event_data,
            visitor_ip=visitor_info.get('ip') if visitor_info else None,
            user_agent=visitor_info.get('user_agent') if visitor_info else None,
            referrer=visitor_info.get('referrer') if visitor_info else None
        )
        
        self.db.add(event)
        self.db.commit()
    
    def _generate_conversation_id(self) -> str:
        """Générer un UUID pour nouvelle conversation"""
        return f"conv_{uuid.uuid4().hex[:16]}"
    
    def _generate_temporary_response(self, intent: str, context: Dict) -> str:
        """
        Générer une réponse temporaire (en attendant ResponseGenerator Phase 1-J3)
        """
        site_name = context.get('site', {}).get('site_name', 'ePerformance')
        
        responses = {
            'diagnostic_request': f"Je serais ravi de vous aider à faire un diagnostic de votre business ! Pour commencer, pouvez-vous me dire quel est votre budget publicitaire mensuel actuel et combien de clients vous acquérez en moyenne par mois ?",
            'product_inquiry': f"Nous proposons plusieurs solutions chez {site_name}. Quel type de formation ou service vous intéresse particulièrement ? Marketing digital, publicités Meta Ads, ou stratégies IA ?",
            'order_intent': "Super ! Je vais vous mettre en relation avec notre équipe commerciale. Pouvez-vous me donner votre nom et votre numéro de téléphone pour qu'on puisse vous recontacter rapidement ?",
            'support_question': "Je suis là pour vous aider ! Pouvez-vous me décrire votre problème plus en détail ?",
            'pricing_question': "Nos tarifs varient selon vos besoins. Pour vous proposer l'offre la plus adaptée, pouvez-vous me dire quel type de service vous intéresse ?",
        }
        
        return responses.get(
            intent,
            f"Merci pour votre message ! Comment puis-je vous aider aujourd'hui chez {site_name} ?"
        )
    
    def _generate_suggestions(self, intent: str) -> List[str]:
        """Générer des suggestions de réponse rapide"""
        suggestions_map = {
            'diagnostic_request': [
                "Faire un diagnostic gratuit",
                "En savoir plus sur les diagnostics"
            ],
            'product_inquiry': [
                "Voir les formations",
                "Découvrir les services",
                "Parler à un conseiller"
            ],
            'order_intent': [
                "Obtenir un devis",
                "Prendre rendez-vous"
            ],
            'pricing_question': [
                "Voir les tarifs formations",
                "Demander un devis personnalisé"
            ],
            'general_question': [
                "Faire un diagnostic",
                "Voir nos services",
                "Contacter un conseiller"
            ]
        }
        
        return suggestions_map.get(intent, [
            "En savoir plus",
            "Parler à un conseiller"
        ])
    
    def get_conversation_history(self, conversation_id: str, limit: int = 50) -> Dict:
        """
        Récupérer l'historique complet d'une conversation
        
        Returns:
            {
                'conversation_id': str,
                'messages': List[Dict],
                'metadata': Dict
            }
        """
        conversation = self.db.query(ChatbotConversation).filter_by(
            conversation_id=conversation_id
        ).first()
        
        if not conversation:
            return {'error': 'Conversation not found'}
        
        messages = self.db.query(ChatbotMessage).filter_by(
            conversation_id=conversation_id
        ).order_by(ChatbotMessage.created_at).limit(limit).all()
        
        return {
            'conversation_id': conversation_id,
            'status': conversation.status,
            'started_at': conversation.started_at.isoformat(),
            'message_count': conversation.message_count,
            'lead_captured': conversation.lead_captured,
            'messages': [
                {
                    'role': msg.role,
                    'content': msg.content,
                    'intent': msg.intent,
                    'agent_used': msg.agent_used,
                    'suggestions': msg.suggestions,
                    'timestamp': msg.created_at.isoformat()
                }
                for msg in messages
            ]
        }

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
import re
import uuid
import time

from .intent_detector import IntentDetector
from .context_builder import ContextBuilder
from . import liens_site
from .agent_router import AgentRouter
from .response_generator import ResponseGenerator
from .action_executor import ActionExecutor
from .blog_search import enrichir_contexte
from . import connaissance_site, connaissances, instructions_sectorielles
from .models import (
    ChatbotConversation,
    ChatbotMessage,
    ChatbotAnalytics
)


# ============================================================
# INTENT EXPLICITE DU WIDGET — tâche 6.3-BIS A.8
#
# Le widget envoie `[intent:<nom>] <libellé>` quand le visiteur clique une
# suggestion de l'accueil ou une capacité de l'onglet Aide. Le préfixe est :
#   · RETIRÉ du texte affiché et du texte enregistré (le visiteur ne doit
#     jamais voir cette notation technique) ;
#   · RETIRÉ du texte envoyé au LLM (Mia répond au libellé, pas à une balise) ;
#   · utilisé UNIQUEMENT ici pour choisir l'agent — le mapping intent → agent
#     vit dans `AgentRouter` et n'est jamais exposé au front.
# ============================================================

MOTIF_INTENT_EXPLICITE = re.compile(r'^\s*\[intent:([a-z0-9_]+)\]\s*', re.IGNORECASE)


def extraire_intent_explicite(message: str):
    """(intent, message nettoyé) — intent vaut None si aucun préfixe."""
    correspondance = MOTIF_INTENT_EXPLICITE.match(message or '')
    if not correspondance:
        return None, message
    return correspondance.group(1).lower(), (message or '')[correspondance.end():].strip()


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
        message_history: Optional[List[Dict]] = None,
        image: Optional[Dict] = None
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
            image: Image normalisée (vision.preparer_image) — optionnelle (A.1)
        
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
        # Articles du blog injectés dans cette réponse (tâche 6.8). Initialisé
        # à None pour rester défini même si le pipeline échoue avant l'étape 3bis.
        blog = None
        
        # Intent explicite du widget (clic sur une suggestion) — A.8.
        # Il est extrait AVANT toute écriture : ni la base ni le LLM ne voient
        # la notation `[intent:…]`.
        intent_explicite, message = extraire_intent_explicite(message)
        if not (message or '').strip():
            # Clic sur une suggestion dont le libellé manquerait : on garde le
            # libellé d'origine plutôt que d'envoyer un message vide au LLM.
            message = (message or '').strip() or 'Bonjour'
        
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

            # Photos AVANT traitement (B4) : les déclencheurs de notification
            # (nouveau lead, escalade) comparent l'état APRÈS à celui-ci.
            lead_captured_avant = bool(conversation.lead_captured)
            statut_avant = conversation.status

            # 1bis. Takeover humain: le LLM est en pause sur cette conversation,
            # on enregistre le message et on signale au widget que l'humain parle.
            conv_meta = conversation.conversation_metadata or {}
            if conversation.status == 'escalated' and conv_meta.get('human_active'):
                self._save_message(
                    conversation_id=conversation_id,
                    role='user',
                    content=message
                )
                self._update_conversation(conversation_id)
                return {
                    'conversation_id': conversation_id,
                    'response': '',
                    'intent': 'human_takeover',
                    'intent_confidence': 1.0,
                    'agent_used': None,
                    'suggestions': [],
                    'actions': [],
                    'processing_time_ms': int((time.time() - start_time) * 1000),
                    'human_active': True
                }

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

            # 3bis. Recherche blog (tâche 6.8) — ENRICHISSEMENT NON INTRUSIF.
            #
            # Trois propriétés voulues, dans cet ordre :
            #   · `enrichir_contexte` n'appelle JAMAIS le réseau et n'attend
            #     JAMAIS : si l'index n'est pas déjà en mémoire, elle renvoie
            #     None et la conversation suit son cours normal ;
            #   · elle n'échoue pas : toute erreur est absorbée à l'intérieur,
            #     et le `try` ci-dessous est une seconde barrière — une
            #     recherche cassée ne doit pas pouvoir casser une réponse ;
            #   · sans résultat jugé pertinent, la clé n'est simplement pas
            #     posée : Mia répond comme avant, sans savoir que la recherche
            #     existe.
            # 3ter. Connaissances du PROPRIÉTAIRE (chantier F, 24/09) —
            # priorité maximale : c'est ce qu'il a explicitement enseigné.
            try:
                connaissances.charger_depuis_db(self.db, site_id)
                trouvées = connaissances.chercher(site_id, message)
                if trouvées:
                    context['connaissances'] = trouvées
                    context.setdefault('sources', []).insert(0, 'connaissances')
            except Exception as _connaissances_erreur:  # pragma: no cover - filet
                print(f"[F] Connaissances ignorées: {_connaissances_erreur}")

            # 3quater. Pages du SITE du tenant (chantier E, 24/09) — avant le
            # blog : le contenu du site du client est la première base.
            try:
                site_url = (context.get('site') or {}).get('site_url')
                if site_url:
                    site_pages = connaissance_site.enrichir_contexte(message, site_url)
                    if site_pages:
                        context['site_knowledge'] = site_pages
                        context.setdefault('sources', []).insert(0, 'site')
            except Exception as _site_erreur:  # pragma: no cover - filet
                print(f"[E] Recherche site ignorée: {_site_erreur}")

            try:
                blog = enrichir_contexte(message)
                if blog:
                    context['blog'] = blog
                    context.setdefault('sources', []).append('blog')
            except Exception as _blog_error:  # pragma: no cover - filet
                print(f"[6.8] Recherche blog ignorée: {_blog_error}")
            
            # 4. Detect intent
            # Un intent explicite (clic sur une suggestion du widget) prime sur
            # la détection par mots-clés : le visiteur a dit ce qu'il voulait.
            if intent_explicite:
                intent = intent_explicite
                intent_confidence = 1.0
                intent_metadata = {
                    'method': 'widget_suggestion',
                    'source': 'suggestion_click',
                    'timestamp': datetime.utcnow().isoformat(),
                }
            else:
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

            # 5bis. Override admin: agent assigné manuellement depuis le dashboard
            forced_agent = conv_meta.get('assigned_agent')
            if forced_agent:
                agent_key = forced_agent
            
            # 6. Generate response (Phase 1-J3)
            response_text, generation_metadata = await self.response_generator.generate_response(
                agent_key=agent_key,
                agent_metadata=agent_metadata,
                message=message,
                context=context,
                intent=intent,
                intent_metadata=intent_metadata,
                image=image
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
                    'is_new_conversation': is_new_conversation,
                    'image_jointe': image is not None,
                },
                visitor_info=visitor_info
            )

            # 10ter. Déclencheurs de notification du PROPRIÉTAIRE (B4) —
            # nouveau lead, escalade humaine, nouveau visiteur. Asynchrone et
            # NON BLOQUANT : le visiteur n'attend aucun envoi ; le module ne
            # lève jamais (tout est absorbé et journalisé). Aucun nom d'agent
            # n'apparaît dans les notifications (règle produit).
            try:
                from . import declencheurs
                declencheurs.traiter_apres_message(
                    db=self.db,
                    site_id=site_id,
                    conversation_id=conversation_id,
                    est_nouvelle_conversation=is_new_conversation,
                    lead_captured_avant=lead_captured_avant,
                    statut_avant=statut_avant,
                    actions=actions_executed,
                )
            except Exception as _declenchement_erreur:  # pragma: no cover
                print(f"[B4] déclencheurs ignorés: {_declenchement_erreur}")

            # 10bis. Clic sur une suggestion (A.8) — donnée commerciale.
            # Le widget joint `visitor_info.suggestion_click`
            # {suggestion_id, intent, label, timestamp, session_id}. On
            # l'enregistre comme événement dédié : c'est lui qui dira quelles
            # capacités intéressent réellement les visiteurs.
            clic = (visitor_info or {}).get('suggestion_click')
            if isinstance(clic, dict) and clic:
                self._track_event(
                    site_id=site_id,
                    conversation_id=conversation_id,
                    event_type='suggestion_click',
                    event_category='engagement',
                    event_data={
                        'suggestion_id': clic.get('suggestion_id'),
                        'intent': clic.get('intent') or intent_explicite,
                        'label': clic.get('label'),
                        'client_timestamp': clic.get('timestamp'),
                        'session_id': clic.get('session_id'),
                        # Ce que le backend en a fait — la preuve que le clic
                        # est bien allé jusqu'à la réponse, pas seulement reçu.
                        'agent_used': agent_used,
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
                'context_sources': context.get('sources', []),
                # Articles du blog réellement fournis au modèle (tâche 6.8).
                # None si la recherche n'a rien trouvé de pertinent.
                'blog': blog,
                # Incidence 2026-09-24 (lot C) : vrai quand TOUS les
                # fournisseurs LLM ont échoué (crédit épuisé, API hors ligne)
                # et que la réponse est le texte de repli « système IA
                # temporairement indisponible ». Champ additif : le widget qui
                # l'ignore ne voit aucune différence.
                'ia_indisponible': generation_metadata.get('llm_provider') == 'fallback',
                # Liens directs du site (lot D) : détection lexicale sans LLM,
                # URLs absolues du site du tenant, liste vide si rien ne joue.
                'liens_site': liens_site.liens_pour(
                    site_url=(context.get('site') or {}).get('site_url'),
                    message=message,
                    intent=intent,
                ),
                # Sources de connaissance utilisées (E/F) : pages du site du
                # tenant citées dans la réponse — publiques, l'affichage côté
                # widget est un simple lien.
                'site_pages': (context.get('site_knowledge') or {}).get('pages') or [],
                'connaissances_utilisees': bool(context.get('connaissances')),
            }
        
        except Exception as e:
            # ROLLBACK IMMÉDIAT pour éviter InFailedSqlTransaction
            self.db.rollback()
            
            # Log error et retourner une réponse d'erreur
            print(f"Error processing message: {e}")
            import traceback
            traceback.print_exc()
            
            # NE PAS appeler _track_event() ici (ferait requête DB sur transaction échouée)
            
            return {
                'conversation_id': conversation_id or 'error',
                'response': "Désolé, une erreur s'est produite. Notre équipe a été notifiée. Pouvez-vous reformuler votre demande ?",
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
        """
        Suggestions de réponse rapide (boutons natifs du widget).

        Les neuf intents d'A.8 ont leurs propres suites : après une réponse qui
        démontre une compétence, proposer l'étape suivante de CETTE compétence
        fait avancer la conversation — « En savoir plus / Parler à un
        conseiller » y serait un repli, pas une suite.
        """
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
            ],
            # ---- Les neuf capacités (A.8) : suites de la compétence ----
            'clients': [
                "Par où commencer cette semaine ?",
                "Faire un diagnostic de mon acquisition"
            ],
            'mlm': [
                "Comment structurer mon recrutement ?",
                "Automatiser le suivi de mes contacts"
            ],
            'ventes': [
                "Où je perds le plus de ventes ?",
                "Améliorer mon offre d'entrée"
            ],
            'site_web': [
                "Que mettre sur mon premier écran ?",
                "Faire un diagnostic de mon site actuel"
            ],
            'seo': [
                "Quels mots-clés viser d'abord ?",
                "Être cité par les IA (ChatGPT, Google)"
            ],
            'ads': [
                "Quel budget pour démarrer ?",
                "Améliorer mon offre avant de payer"
            ],
            'social': [
                "Quel rythme de publication tenir ?",
                "Quels formats fonctionnent en Afrique de l'Ouest ?"
            ],
            'ia_auto': [
                "Quelle tâche automatiser en premier ?",
                "Répondre aux prospects automatiquement"
            ],
            'funnel': [
                "Quelle étape perd le plus ?",
                "Faire un diagnostic de mon tunnel"
            ],
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

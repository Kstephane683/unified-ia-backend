"""
AgentRouter - Router intelligent vers les 29 agents spécialisés
Phase 1-J3 : Sélection de l'agent optimal selon l'intent détecté

Mapping Intent → Agent IA avec fallback intelligent
"""
from typing import Dict, Optional, List, Tuple
from pathlib import Path
import re


class AgentRouter:
    """
    Router intelligent qui sélectionne l'agent IA optimal
    pour traiter un intent spécifique
    """
    
    # Mapping Intent → Agent (clé = filename sans extension)
    INTENT_TO_AGENT_MAP = {
        # Sales intents
        'diagnostic_request': 'sales-discovery-coach',
        'product_inquiry': 'sales-offer-lead-gen-strategist',
        'order_intent': 'sales-offer-lead-gen-strategist',
        'objection_handling': 'sales-discovery-coach',
        'pricing_question': 'sales-offer-lead-gen-strategist',
        'negotiation': 'sales-deal-strategist',
        'contract_review': 'sales-engineer',
        'account_strategy': 'sales-account-strategist',
        'sales_process': 'sales-coach',
        'pipeline_review': 'sales-pipeline-analyst',
        'proposal_writing': 'sales-proposal-strategist',
        
        # Marketing intents
        'content_strategy': 'marketing-content-creator',
        'social_media_strategy': 'marketing-social-media-strategist',
        'email_marketing': 'marketing-email-strategist',
        'seo_question': 'marketing-seo-specialist',
        'growth_hacking': 'marketing-growth-hacker',
        'instagram_content': 'marketing-instagram-curator',
        'linkedin_content': 'marketing-linkedin-content-creator',
        'twitter_content': 'marketing-twitter-engager',
        'reddit_strategy': 'marketing-reddit-community-builder',
        'video_optimization': 'marketing-video-optimization-specialist',
        'short_video_editing': 'marketing-short-video-editing-coach',
        'carousel_creation': 'marketing-carousel-growth-engine',
        'pr_communications': 'marketing-pr-communications-manager',
        'multi_platform_publishing': 'marketing-multi-platform-publisher',
        
        # MLM/Parrainage intents (spécifique ePerformance)
        'mlm_advice': 'sales-outbound-strategist',
        'mlm_recruitment': 'sales-outbound-strategist',
        'mlm_automation': 'marketing-growth-hacker',
        
        # Design intents
        'brand_identity': 'design-brand-guardian',
        'image_creation': 'design-image-prompt-engineer',
        'visual_storytelling': 'design-visual-storyteller',
        
        # Research intents
        'market_research': 'research-deep-agent',
        'trend_analysis': 'product-trend-researcher',
        'competitive_analysis': 'research-synthesist',
        'ia_trends': 'research-deep-agent',
        
        # Support & General
        'support_question': 'marketing-email-strategist',  # Support clair et pédago
        'technical_support': 'sales-engineer',
        'general_question': 'sales-discovery-coach',  # Questions ouvertes
        'greeting': 'sales-discovery-coach',
        'fallback': 'sales-discovery-coach',  # Agent par défaut
    }
    
    # Agents par catégorie (pour enrichissement contextuel)
    AGENT_CATEGORIES = {
        'sales': [
            'sales-discovery-coach',
            'sales-offer-lead-gen-strategist',
            'sales-deal-strategist',
            'sales-account-strategist',
            'sales-outbound-strategist',
            'sales-coach',
            'sales-engineer',
            'sales-pipeline-analyst',
            'sales-proposal-strategist',
        ],
        'marketing': [
            'marketing-content-creator',
            'marketing-email-strategist',
            'marketing-social-media-strategist',
            'marketing-seo-specialist',
            'marketing-growth-hacker',
            'marketing-instagram-curator',
            'marketing-linkedin-content-creator',
            'marketing-twitter-engager',
            'marketing-reddit-community-builder',
            'marketing-video-optimization-specialist',
            'marketing-short-video-editing-coach',
            'marketing-carousel-growth-engine',
            'marketing-pr-communications-manager',
            'marketing-multi-platform-publisher',
        ],
        'design': [
            'design-brand-guardian',
            'design-image-prompt-engineer',
            'design-visual-storyteller',
        ],
        'research': [
            'research-deep-agent',
            'research-synthesist',
        ],
        'product': [
            'product-trend-researcher',
        ]
    }
    
    def __init__(self, agents_base_path: str = "agents"):
        """
        Initialiser le router
        
        Args:
            agents_base_path: Chemin vers le dossier agents/
        """
        self.agents_base_path = Path(agents_base_path)
        self._validate_agents_exist()
    
    def route(
        self,
        intent: str,
        context: Dict,
        intent_metadata: Optional[Dict] = None
    ) -> Tuple[str, Dict]:
        """
        Router vers l'agent optimal
        
        Args:
            intent: Intent détecté par IntentDetector
            context: Context du chatbot (historique, user, etc.)
            intent_metadata: Métadonnées supplémentaires de l'intent
        
        Returns:
            (agent_key, routing_metadata)
            - agent_key: Clé de l'agent sélectionné (ex: "sales-discovery-coach")
            - routing_metadata: Infos sur le routing (raison, alternatives, etc.)
        """
        # 1. Mapping direct intent → agent
        agent_key = self.INTENT_TO_AGENT_MAP.get(intent)
        routing_reason = "direct_mapping"
        alternatives = []
        
        # 2. Fallback si intent inconnu
        if not agent_key:
            agent_key = self._fallback_routing(intent, context, intent_metadata)
            routing_reason = "fallback"
        
        # 3. Override contextuel (ex: utilisateur MLM détecté)
        if self._should_override_for_mlm(context, intent):
            alternatives.append(agent_key)
            agent_key = 'sales-outbound-strategist'
            routing_reason = "mlm_override"
        
        # 4. Générer alternatives intelligentes
        if not alternatives:
            alternatives = self._get_alternative_agents(agent_key, intent)
        
        # 5. Métadonnées de routing
        routing_metadata = {
            'agent_selected': agent_key,
            'intent': intent,
            'routing_reason': routing_reason,
            'alternatives': alternatives,
            'agent_category': self._get_agent_category(agent_key),
            'agent_path': self._get_agent_path(agent_key)
        }
        
        return agent_key, routing_metadata
    
    def _fallback_routing(
        self,
        intent: str,
        context: Dict,
        intent_metadata: Optional[Dict]
    ) -> str:
        """
        Routing fallback intelligent quand l'intent n'a pas de mapping direct
        """
        # Analyser l'intent pour détecter des patterns
        intent_lower = intent.lower()
        
        # Keywords → agent mapping
        if any(kw in intent_lower for kw in ['vente', 'client', 'prospect', 'lead']):
            return 'sales-discovery-coach'
        
        if any(kw in intent_lower for kw in ['contenu', 'post', 'social', 'réseaux']):
            return 'marketing-content-creator'
        
        if any(kw in intent_lower for kw in ['seo', 'référencement', 'google']):
            return 'marketing-seo-specialist'
        
        if any(kw in intent_lower for kw in ['design', 'visuel', 'image', 'logo']):
            return 'design-brand-guardian'
        
        if any(kw in intent_lower for kw in ['recherche', 'analyse', 'tendance']):
            return 'research-deep-agent'
        
        if any(kw in intent_lower for kw in ['mlm', 'longrich', 'parrain', 'filleul']):
            return 'sales-outbound-strategist'
        
        # Fallback ultime
        return 'sales-discovery-coach'
    
    def _should_override_for_mlm(self, context: Dict, intent: str) -> bool:
        """
        Déterminer si on doit override vers sales-outbound-strategist
        pour les prospects MLM (80% de la base ePerformance)
        """
        # Analyser le contexte utilisateur
        user_profile = context.get('user_profile', {})
        visitor_info = context.get('visitor_info', {})
        history = context.get('message_history', [])
        
        # Indices MLM dans le profil
        mlm_keywords = ['longrich', 'mlm', 'network marketing', 'parrainage', 'distributeur']
        
        # Check profil utilisateur
        secteur = user_profile.get('secteur_activite', '').lower()
        if any(kw in secteur for kw in mlm_keywords):
            return True
        
        # Check historique conversation
        history_text = ' '.join([msg.get('content', '') for msg in history[-5:]]).lower()
        if any(kw in history_text for kw in mlm_keywords):
            return True
        
        # Check referrer (si vient d'une page MLM)
        referrer = visitor_info.get('referrer', '').lower()
        if any(kw in referrer for kw in ['mlm', 'longrich', 'parrainage']):
            return True
        
        return False
    
    def _get_alternative_agents(self, primary_agent: str, intent: str) -> List[str]:
        """
        Générer une liste d'agents alternatifs pertinents
        (utile pour escalade ou A/B testing futur)
        """
        alternatives = []
        
        # Trouver la catégorie de l'agent principal
        category = self._get_agent_category(primary_agent)
        
        if category:
            # Prendre 2 autres agents de la même catégorie
            same_category = [
                agent for agent in self.AGENT_CATEGORIES[category]
                if agent != primary_agent
            ]
            alternatives.extend(same_category[:2])
        
        # Limiter à 2 alternatives
        return alternatives[:2]
    
    def _get_agent_category(self, agent_key: str) -> Optional[str]:
        """Déterminer la catégorie d'un agent"""
        for category, agents in self.AGENT_CATEGORIES.items():
            if agent_key in agents:
                return category
        return None
    
    def _get_agent_path(self, agent_key: str) -> Optional[str]:
        """
        Obtenir le chemin complet vers le fichier Markdown de l'agent
        
        Returns:
            Path absolu vers le .md ou None si non trouvé
        """
        # Chercher dans toutes les catégories
        for category in self.AGENT_CATEGORIES.keys():
            agent_file = self.agents_base_path / category / f"{agent_key}.md"
            if agent_file.exists():
                return str(agent_file.absolute())
        
        return None
    
    def _validate_agents_exist(self):
        """
        Valider que le dossier agents/ existe et contient les agents
        (warning si manquants, pas d'erreur critique)
        """
        if not self.agents_base_path.exists():
            print(f"⚠️  Warning: Agents directory not found at {self.agents_base_path}")
            print("    AgentRouter will continue but agent persona loading may fail")
            return
        
        # Compter les agents disponibles
        total_expected = sum(len(agents) for agents in self.AGENT_CATEGORIES.values())
        total_found = 0
        
        for category in self.AGENT_CATEGORIES.keys():
            category_path = self.agents_base_path / category
            if category_path.exists():
                total_found += len(list(category_path.glob("*.md")))
        
        if total_found < total_expected:
            print(f"⚠️  Warning: Expected {total_expected} agents, found {total_found}")
            print("    Some agents may be missing from the agents/ directory")
    
    def get_all_agents(self) -> Dict[str, List[str]]:
        """
        Retourner tous les agents disponibles par catégorie
        (utile pour debug et analytics)
        """
        return self.AGENT_CATEGORIES.copy()
    
    def get_intent_coverage(self) -> Dict[str, str]:
        """
        Retourner le mapping complet intent → agent
        (utile pour debug et documentation)
        """
        return self.INTENT_TO_AGENT_MAP.copy()

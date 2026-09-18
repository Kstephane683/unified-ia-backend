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
    #
    # Les valeurs DOIVENT correspondre à un fichier réel de
    # `backend/chatbot/agents/<catégorie>/<clé>.md` : sinon `_get_agent_path`
    # rend None et le persona n'est pas chargé — le LLM répond alors sans
    # expertise. Plusieurs entrées pointaient vers des agents inexistants
    # avant la tâche 6.3-BIS ; elles ont été alignées sur les 27 fichiers réels.
    INTENT_TO_AGENT_MAP = {
        # Sales intents
        'diagnostic_request': 'sales-discovery-coach',
        'product_inquiry': 'sales-offer-lead-gen-strategist',
        'order_intent': 'sales-offer-lead-gen-strategist',
        'objection_handling': 'sales-objection-handler',
        'pricing_question': 'sales-offer-lead-gen-strategist',
        'negotiation': 'sales_expert',
        'contract_review': 'sales_expert',
        'account_strategy': 'sales_expert',
        'sales_process': 'sales-discovery-coach',
        'pipeline_review': 'sales-lead-scorer',
        'proposal_writing': 'sales-offer-lead-gen-strategist',
        
        # Marketing intents
        'content_strategy': 'marketing-content-specialist',
        'social_media_strategy': 'marketing-social-media-manager',
        'email_marketing': 'marketing-email-specialist',
        'seo_question': 'marketing-seo-specialist',
        'technical_seo': 'marketing-seo-specialist',
        'growth_hacking': 'marketing-growth-hacker',
        'instagram_content': 'marketing-social-media-manager',
        'linkedin_content': 'marketing-social-media-manager',
        'twitter_content': 'marketing-social-media-manager',
        'reddit_strategy': 'marketing-social-media-manager',
        'video_optimization': 'marketing-social-media-manager',
        'short_video_editing': 'marketing-social-media-manager',
        'carousel_creation': 'marketing-content-specialist',
        'pr_communications': 'marketing-content-specialist',
        'multi_platform_publishing': 'marketing-social-media-manager',
        'copywriting': 'marketing-copywriter',
        'analytics_reporting': 'marketing-analytics-specialist',
        'whatsapp_marketing': 'marketing-whatsapp-specialist',
        
        # MLM/Parrainage intents (spécifique ePerformance)
        'mlm_advice': 'sales-closer-mlm',
        'mlm_recruitment': 'sales-closer-mlm',
        'mlm_automation': 'marketing-growth-hacker',
        
        # Design intents
        'brand_identity': 'design-brand-identity-specialist',
        'image_creation': 'design-brand-identity-specialist',
        'visual_storytelling': 'design-ux-optimizer',
        
        # Research / Product intents
        'market_research': 'research-market-analyst',
        'trend_analysis': 'product-pricing-strategist',
        'competitive_analysis': 'research-market-analyst',
        'ia_trends': 'marketing-growth-hacker',
        
        # Support & General
        'support_question': 'customer_support',
        'technical_support': 'technical_advisor',
        'technical_advisor': 'technical_advisor',
        'general_question': 'sales-discovery-coach',
        'greeting': 'sales-discovery-coach',
        'fallback': 'sales-discovery-coach',

        # ============================================================
        # LES NEUF CAPACITÉS DES SUGGESTIONS — tâche 6.3-BIS A.8
        #
        # Déclenchées par les suggestions de l'accueil et de l'onglet Aide
        # (payload `[intent:<clé>] <libellé>`). Ce mapping est STRICTEMENT
        # backend : il ne sort jamais autrement que par `metadata.agent_used`,
        # que le widget n'affiche plus (règle A.6).
        #
        # Chaque entrée choisit l'agent dont l'expertise DÉMONTRE la
        # compétence annoncée par le libellé — c'est l'objectif stratégique
        # d'A.8 : une réponse concrète, pas une redirection.
        # ============================================================
        'clients': 'sales-outbound-strategist',       # Trouver plus de clients
        'mlm': 'sales-closer-mlm',                    # Développer mon MLM / parrainage
        'ventes': 'sales_expert',                     # Améliorer mes ventes
        'site_web': 'design-landing-page-specialist', # Créer un site web qui convertit
        'seo': 'marketing-seo-specialist',            # Améliorer mon référencement
        'ads': 'marketing-meta-ads-specialist',       # Lancer une campagne publicitaire
        'social': 'marketing-social-media-manager',   # Gérer mes réseaux sociaux
        'ia_auto': 'marketing-growth-hacker',         # Exploiter l'IA et l'automatisation
        'funnel': 'marketing-funnel-architect',       # Optimiser mon tunnel de conversion
    }

    # Intents qu'un clic de suggestion peut demander (A.8). Sert au contrôle
    # de cohérence : tout intent listé ici DOIT avoir une entrée ci-dessus.
    INTENTS_SUGGESTIONS = (
        'clients', 'mlm', 'ventes', 'site_web', 'seo',
        'ads', 'social', 'ia_auto', 'funnel',
    )
    
    # Agents par catégorie (pour enrichissement contextuel)
    #
    # Tâche 6.3-BIS : cette liste portait des clés qui n'existaient PAS dans
    # `agents/` (les personas n'étaient donc pas chargés) et ignorait une
    # partie des fichiers réels. Elle reflète maintenant exactement le
    # contenu du dossier — 27 fichiers sur 6 catégories.
    AGENT_CATEGORIES = {
        'sales': [
            'sales-callback-scheduler',
            'sales-closer-mlm',
            'sales-discovery-coach',
            'sales_expert',
            'sales-lead-scorer',
            'sales-objection-handler',
            'sales-offer-lead-gen-strategist',
            'sales-outbound-strategist',
            'sales-upsell-specialist',
        ],
        'marketing': [
            'marketing-analytics-specialist',
            'marketing-content-specialist',
            'marketing-copywriter',
            'marketing-email-specialist',
            'marketing-funnel-architect',
            'marketing-growth-hacker',
            'marketing-meta-ads-specialist',
            'marketing-seo-specialist',
            'marketing-social-media-manager',
            'marketing_specialist',
            'marketing-whatsapp-specialist',
        ],
        'design': [
            'design-brand-identity-specialist',
            'design-landing-page-specialist',
            'design-ux-optimizer',
        ],
        'product': [
            'product-pricing-strategist',
            'technical_advisor',
        ],
        'research': [
            'research-market-analyst',
        ],
        'support': [
            'customer_support',
        ],
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
        #    SAUF si l'intent vient d'une suggestion cliquée : le visiteur a
        #    explicitement demandé cette compétence (« Améliorer mon
        #    référencement »), l'override MLM la détournerait (A.8).
        suggestion_explicite = (intent_metadata or {}).get('source') == 'suggestion_click'
        if not suggestion_explicite and self._should_override_for_mlm(context, intent):
            alternatives.append(agent_key)
            agent_key = 'sales-outbound-strategist'
            routing_reason = "mlm_override"
        elif suggestion_explicite:
            routing_reason = "suggestion_intent"
        
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
        # NB (tâche 6.3-BIS) : ContextBuilder remplit la clé `history`, pas
        # `message_history` — l'override MLM ne se déclenchait donc JAMAIS en
        # production. On lit les deux : la première si elle existe, la seconde
        # pour les appelants qui utilisent l'ancien nom.
        history = context.get('history') or context.get('message_history') or []
        
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

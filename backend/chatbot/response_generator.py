"""
ResponseGenerator - Génération de réponses avec LLM et persona agent
Phase 1-J3 : Construction du prompt enrichi + appels LLM (DeepSeek prioritaire)

Pipeline :
1. Charger le persona de l'agent sélectionné (Markdown)
2. Construire le system prompt enrichi (persona + context + instructions)
3. Appel LLM avec fallback (DeepSeek → Claude → GPT)
4. Post-processing de la réponse
"""
from typing import Dict, Optional, List, Tuple
from pathlib import Path
import re
import time

# Import LLM Client unifié
try:
    from ..core.llm_client import LLMClient
except ImportError:
    # Fallback si import échoue
    print("⚠️  Warning: LLMClient import failed, using fallback")
    LLMClient = None


class ResponseGenerator:
    """
    Générateur de réponses avec persona agent et LLM
    """
    
    # Providers par ordre de priorité (coût/performance)
    LLM_PROVIDERS = ['deepseek', 'claude', 'openai']
    
    # Limites de tokens par provider
    TOKEN_LIMITS = {
        'deepseek': {'max_tokens': 2000, 'temperature': 0.7},
        'claude': {'max_tokens': 2000, 'temperature': 0.7},
        'openai': {'max_tokens': 1500, 'temperature': 0.7}
    }
    
    def __init__(self, agents_dir: Path, config_path: str = None):
        """
        Initialiser le générateur
        
        Args:
            agents_dir: Path vers le dossier agents/
            config_path: Chemin vers config_ia.json (optionnel)
        """
        self.agents_dir = agents_dir
        self.agents_base_path = agents_dir  # Compatibilité
        self._agent_cache = {}  # Cache des personas chargés
        
        # Initialiser LLM Client
        if LLMClient:
            self.llm_client = LLMClient(config_path)
        else:
            self.llm_client = None
            print("⚠️  LLMClient non disponible, mode fallback activé")
    
    async def generate_response(
        self,
        agent_key: str,
        agent_metadata: Dict,
        message: str,
        context: Dict,
        intent: str,
        intent_metadata: Optional[Dict] = None
    ) -> Tuple[str, Dict]:
        """
        Générer une réponse avec le persona de l'agent
        
        Args:
            agent_key: Clé de l'agent (ex: "sales-discovery-coach")
            agent_metadata: Métadonnées du routing
            message: Message utilisateur
            context: Context complet (historique, user, etc.)
            intent: Intent détecté
            intent_metadata: Métadonnées de l'intent
        
        Returns:
            (response_text, generation_metadata)
            - response_text: Réponse générée par le LLM
            - generation_metadata: Infos sur la génération (provider, tokens, etc.)
        """
        start_time = time.time()
        
        # 1. Charger le persona de l'agent
        agent_persona = self._load_agent_persona(agent_key, agent_metadata.get('agent_path'))
        
        # 2. Construire le system prompt enrichi
        system_prompt = self._build_system_prompt(
            agent_persona=agent_persona,
            context=context,
            intent=intent,
            agent_key=agent_key
        )
        
        # 3. Construire l'historique de messages pour le LLM
        messages = self._build_messages_history(
            system_prompt=system_prompt,
            message=message,
            context=context
        )
        
        # 4. Appeler le LLM avec fallback
        response_text, provider_used, tokens_used = await self._call_llm_with_fallback(
            messages=messages,
            intent=intent
        )
        
        # 5. Post-processing de la réponse
        response_text = self._post_process_response(response_text, context)
        
        # 6. Métadonnées de génération
        generation_time_ms = int((time.time() - start_time) * 1000)
        
        generation_metadata = {
            'agent_key': agent_key,
            'llm_provider': provider_used,
            'llm_tokens_used': tokens_used,
            'generation_time_ms': generation_time_ms,
            'system_prompt_length': len(system_prompt),
            'persona_loaded': agent_persona is not None
        }
        
        return response_text, generation_metadata
    
    def _load_agent_persona(self, agent_key: str, agent_path: Optional[str]) -> Optional[str]:
        """
        Charger le persona Markdown de l'agent depuis le fichier
        
        Returns:
            Contenu Markdown complet ou None si non trouvé
        """
        # Check cache
        if agent_key in self._agent_cache:
            return self._agent_cache[agent_key]
        
        # Trouver le fichier
        if agent_path and Path(agent_path).exists():
            persona_file = Path(agent_path)
        else:
            # Chercher dans toutes les catégories
            persona_file = None
            for category in ['sales', 'marketing', 'design', 'research', 'product']:
                candidate = self.agents_base_path / category / f"{agent_key}.md"
                if candidate.exists():
                    persona_file = candidate
                    break
        
        if not persona_file or not persona_file.exists():
            print(f"⚠️  Warning: Agent persona not found for {agent_key}")
            return None
        
        # Charger et mettre en cache
        try:
            persona_content = persona_file.read_text(encoding='utf-8')
            self._agent_cache[agent_key] = persona_content
            return persona_content
        except Exception as e:
            print(f"⚠️  Error loading persona for {agent_key}: {e}")
            return None
    
    def _build_system_prompt(
        self,
        agent_persona: Optional[str],
        context: Dict,
        intent: str,
        agent_key: str
    ) -> str:
        """
        Construire le system prompt enrichi
        
        Structure :
        1. Persona de l'agent (Markdown complet)
        2. Context ePerformance (offres, tarifs, clients types)
        3. Context utilisateur (profil, historique, diagnostics)
        4. Instructions spécifiques à l'intent
        5. Contraintes (ton, longueur, format)
        """
        prompt_parts = []
        
        # 1. Persona de l'agent
        if agent_persona:
            prompt_parts.append("# VOTRE IDENTITÉ ET EXPERTISE\n")
            prompt_parts.append(agent_persona)
            prompt_parts.append("\n---\n")
        else:
            # Fallback si persona non chargé
            prompt_parts.append(f"# AGENT : {agent_key}\n")
            prompt_parts.append("Vous êtes un assistant expert ePerformance.\n\n")
        
        # 2. Context ePerformance (offres produits)
        prompt_parts.append(self._get_eperformance_context())
        
        # 3. Context utilisateur
        user_context = self._format_user_context(context)
        if user_context:
            prompt_parts.append("\n# CONTEXT UTILISATEUR\n")
            prompt_parts.append(user_context)
            prompt_parts.append("\n")
        
        # 4. Instructions spécifiques à l'intent
        intent_instructions = self._get_intent_instructions(intent)
        if intent_instructions:
            prompt_parts.append("\n# INSTRUCTIONS POUR CET ÉCHANGE\n")
            prompt_parts.append(intent_instructions)
            prompt_parts.append("\n")
        
        # 5. Contraintes générales
        prompt_parts.append(self._get_general_constraints())
        
        return "".join(prompt_parts)
    
    def _get_business_context(self, context: Dict) -> str:
        """
        Context métier dynamique selon le site_id
        
        Deux cas :
        1. Site ePerformance vitrine → Context ePerformance (nos services)
        2. Site client → Context du client (depuis chatbot_sites table)
        """
        site_config = context.get('site', {})
        site_id = site_config.get('site_id', '')
        
        # Cas 1 : Site ePerformance vitrine (nos propres offres)
        if site_id in ['eperformance_vitrine', 'eperformance_espace_client', '']:
            return self._get_eperformance_context()
        
        # Cas 2 : Site client (context personnalisé depuis DB)
        custom_context = site_config.get('business_context', '')
        if custom_context:
            return f"\n# CONTEXT ENTREPRISE\n\n{custom_context}\n\n---\n"
        
        # Fallback : context générique
        site_name = site_config.get('site_name', 'notre entreprise')
        return f"""
# CONTEXT ENTREPRISE

Vous êtes l'assistant IA de **{site_name}**.

Votre rôle :
1. Comprendre les besoins précis du visiteur
2. Fournir des informations sur les produits/services
3. Répondre aux questions de manière professionnelle
4. Capturer les coordonnées des prospects intéressés
5. Transmettre les leads chauds à l'équipe commerciale

---
"""
    
    def _get_eperformance_context(self) -> str:
        """
        Context ePerformance (UNIQUEMENT pour notre site vitrine)
        """
        return """
# CONTEXT EPERFORMANCE

## Notre Entreprise
ePerformance est une agence spécialisée en marketing digital et systèmes d'acquisition automatisés pour les PME africaines et entrepreneurs (MLM, e-commerce, services).

## Nos Offres Principales

### 1. Pack Découverte - 100 000 FCFA
- Site web professionnel (domaine inclus)
- Chatbot IA intégré (celui-ci !)
- Système de capture de leads automatique
- Formation de base (2h)
- Support 30 jours

### 2. Diagnostic Stratégique Gratuit
- Analyse CAC (Coût d'Acquisition Client)
- Audit marge et conversion
- Identification des 3 failles critiques
- Durée : 5-10 minutes
- Recommandations personnalisées

### 3. Solutions Sectorielles
- **MLM/Parrainage** : Landing page recrutement, tunnel filleules (ex: Longrich)
- **E-commerce** : Boutique + paiement + chatbot vente
- **Services** : Site vitrine + prise RDV automatique
- **Restaurants** : Menu digital + commande en ligne

### 4. Formations
- Meta Ads avancé
- Systèmes IA pour business
- Growth hacking sectoriel
- Prix : 50k à 150k FCFA selon durée

## Résultats Clients Récents
- Distributrice MLM : 47 leads qualifiés/mois
- Restaurant : +60% commandes en ligne
- Coach : Agenda rempli 3 semaines à l'avance
- Réduction CAC de 60% en moyenne

## Votre Rôle
1. Comprendre les besoins précis du visiteur (questions SPIN)
2. Recommander l'offre la plus adaptée (souvent Pack Découverte ou Diagnostic)
3. Capturer les coordonnées pour suivi commercial
4. Transmettre immédiatement les leads chauds à l'équipe

---
"""
    
    def _format_user_context(self, context: Dict) -> str:
        """
        Formater le context utilisateur de manière lisible
        """
        parts = []
        
        # Profil utilisateur
        user_profile = context.get('user_profile', {})
        if user_profile:
            parts.append("## Profil Utilisateur")
            if user_profile.get('nom'):
                parts.append(f"- Nom : {user_profile['nom']}")
            if user_profile.get('secteur_activite'):
                parts.append(f"- Secteur : {user_profile['secteur_activite']}")
            if user_profile.get('is_mlm'):
                parts.append(f"- Type : Distributeur MLM (priorité stratégies parrainage)")
            parts.append("")
        
        # Diagnostics précédents
        diagnostics = context.get('diagnostics', [])
        if diagnostics:
            parts.append("## Diagnostics Précédents")
            for diag in diagnostics[:2]:  # Max 2 derniers
                parts.append(f"- {diag.get('type', 'Diagnostic')} : {diag.get('summary', 'N/A')}")
            parts.append("")
        
        # Historique récent
        history = context.get('message_history', [])
        if len(history) > 0:
            parts.append("## Historique Récent (contexte)")
            for msg in history[-3:]:  # 3 derniers messages
                role = msg.get('role', 'user')
                content_preview = msg.get('content', '')[:100]
                parts.append(f"- **{role}** : {content_preview}...")
            parts.append("")
        
        return "\n".join(parts) if parts else ""
    
    def _get_intent_instructions(self, intent: str) -> str:
        """
        Instructions spécifiques selon l'intent
        """
        instructions = {
            'diagnostic_request': """
Objectif : Collecter les données pour un diagnostic complet (CAC, LTV, conversion).
Posez 3-4 questions SPIN maximum pour obtenir :
- Budget publicitaire mensuel
- Nombre de clients acquis/mois
- Processus de conversion actuel
Proposez ensuite de générer le diagnostic gratuit.
""",
            'product_inquiry': """
Objectif : Comprendre le besoin précis et recommander l'offre adaptée.
Questions à poser :
- Quel est votre objectif principal ? (leads, ventes, visibilité)
- Avez-vous déjà un site web ?
- Budget approximatif ?
Recommandez Pack Découverte (100k) si budget limité, ou diagnostic gratuit d'abord.
""",
            'order_intent': """
Objectif : Capturer le lead IMMÉDIATEMENT (lead chaud !).
1. Confirmer l'intérêt et l'offre concernée
2. Demander : Nom, Téléphone, Email
3. Proposer un créneau d'appel sous 24h
4. Remercier et confirmer la prise de contact
⚠️ Déclencher ACTION : lead_capture + notification_telegram CRITICAL
""",
            'objection_handling': """
Objectif : Comprendre l'objection réelle et la traiter avec empathie.
Framework :
1. Écouter et reformuler l'objection
2. Isoler : "Si ce n'était que ça, vous seriez prêt ?"
3. Répondre avec preuve sociale ou garantie
4. Tester la fermeture
""",
            'mlm_advice': """
Objectif : Positionner ePerformance comme LA solution MLM.
Points clés :
- 80% de nos clients sont MLM (Longrich majoritairement)
- Système automatisé = 70% de prospects en plus
- Résultats : 47 leads qualifiés/mois (moyenne 3 clients récents)
Proposer diagnostic gratuit pour personnaliser la stratégie.
"""
        }
        
        return instructions.get(intent, "")
    
    def _get_general_constraints(self) -> str:
        """
        Contraintes générales (ton, format, longueur)
        """
        return """
# CONTRAINTES GÉNÉRALES

## Ton et Style
- **Ton** : Professionnel mais chaleureux, direct, orienté résultats
- **Tutoiement** : Oui (standard en Afrique francophone)
- **Longueur** : Réponses concises (150-250 mots max)
- **Emojis** : Oui, avec parcimonie (1-2 par réponse)

## Format
- Phrases courtes et impactantes
- Bullets points si liste
- **Appel à l'action clair** à la fin de chaque réponse
- Pas de jargon technique sauf si expertise demandée

## Interdictions
- ❌ Promesses irréalistes ("devenir riche rapidement")
- ❌ Dévaloriser la concurrence
- ❌ Divulguer les prix sans contexte (toujours proposer diagnostic d'abord)
- ❌ Réponses génériques (personnaliser avec le context fourni)

## Priorités
1. Capturer les coordonnées si lead chaud
2. Proposer le diagnostic gratuit (lead magnet principal)
3. Qualifier le besoin avant de recommander une offre
4. Créer de l'urgence authentique (places limitées, promo temporaire)

---

**Maintenant, réponds au message de l'utilisateur en incarnant pleinement ton persona d'agent.**
"""
    
    def _build_messages_history(
        self,
        system_prompt: str,
        message: str,
        context: Dict
    ) -> List[Dict[str, str]]:
        """
        Construire l'historique de messages pour l'API LLM
        
        Format :
        [
            {"role": "system", "content": "..."},
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."},
            {"role": "user", "content": "..."}  # message actuel
        ]
        """
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        # Ajouter l'historique récent (5 derniers échanges max)
        history = context.get('message_history', [])
        for msg in history[-10:]:  # 5 échanges = 10 messages
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            if content:
                messages.append({"role": role, "content": content})
        
        # Ajouter le message actuel
        messages.append({"role": "user", "content": message})
        
        return messages
    
    async def _call_llm_with_fallback(
        self,
        messages: List[Dict[str, str]],
        intent: str
    ) -> Tuple[str, str, int]:
        """
        Appeler le LLM avec fallback automatique
        
        Returns:
            (response_text, provider_used, tokens_used)
        """
        last_error = None
        
        for provider in self.LLM_PROVIDERS:
            try:
                # Paramètres du provider
                params = self.TOKEN_LIMITS.get(provider, {})
                
                # Appel LLM (à adapter selon votre implémentation)
                response = await self._call_llm_provider(
                    provider=provider,
                    messages=messages,
                    **params
                )
                
                if response and response.get('content'):
                    return (
                        response['content'],
                        provider,
                        response.get('tokens_used', 0)
                    )
            
            except Exception as e:
                print(f"⚠️  LLM call failed for {provider}: {e}")
                last_error = e
                continue
        
        # Tous les providers ont échoué
        print(f"❌ All LLM providers failed. Last error: {last_error}")
        return (
            "Désolé, notre système IA est temporairement indisponible. "
            "Un conseiller va vous recontacter sous peu. Puis-je avoir votre numéro ?",
            "fallback",
            0
        )
    
    async def _call_llm_provider(
        self,
        provider: str,
        messages: List[Dict[str, str]],
        max_tokens: int = 2000,
        temperature: float = 0.7
    ) -> Dict:
        """
        Appeler un provider LLM spécifique via LLMClient unifié
        
        Args:
            provider: 'deepseek' | 'claude' | 'openai'
            messages: Messages au format OpenAI
            max_tokens: Limite de tokens
            temperature: Créativité (0.0-2.0)
        
        Returns:
            {
                'content': str,
                'tokens_used': int
            }
        """
        if not self.llm_client:
            # Fallback si LLMClient non disponible
            return {
                'content': "Désolé, notre système IA est temporairement indisponible. Un conseiller va vous recontacter.",
                'tokens_used': 0
            }
        
        # Appeler LLM Client avec fallback automatique
        result = await self.llm_client.chat_completion(
            provider=provider,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature
        )
        
        # Retourner format attendu par le code appelant
        return {
            'content': result.get('content', ''),
            'tokens_used': result.get('tokens_used', 0)
        }
    
    def _post_process_response(self, response_text: str, context: Dict) -> str:
        """
        Post-processing de la réponse LLM
        - Nettoyage
        - Insertion variables dynamiques
        - Validation longueur
        """
        # Nettoyer les espaces
        response_text = response_text.strip()
        
        # Remplacer les variables dynamiques
        site_name = context.get('site', {}).get('site_name', 'ePerformance')
        response_text = response_text.replace('{{site_name}}', site_name)
        
        # Limiter la longueur (500 mots max ≈ 2500 chars)
        if len(response_text) > 2500:
            # Couper au dernier point complet
            response_text = response_text[:2500]
            last_period = response_text.rfind('.')
            if last_period > 2000:
                response_text = response_text[:last_period + 1]
        
        return response_text

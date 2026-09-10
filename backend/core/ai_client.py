"""
Client IA unifié avec gestion cascade et fallback automatique.
Support : Claude Gateway (aiapiflow.com) → DeepSeek → GLM-4 → Template

ePerformance API Flow - Unified IA System
"""

import httpx
import json
import logging
from typing import Optional, Dict, Any, Tuple
from datetime import datetime
from backend.core.ai_providers import AIProvidersConfig, AIProvider, ProviderConfig

logger = logging.getLogger(__name__)


class AIClient:
    """
    Client unifié pour appels IA avec fallback cascade automatique.
    
    Usage:
        client = AIClient()
        content, provider = await client.generate(
            prompt="Analyse ce diagnostic...",
            system_prompt="Tu es K. STEPHANE...",
            response_format="json"  # optionnel
        )
    """
    
    def __init__(self):
        self.providers = AIProvidersConfig.get_cascade()
        self.success_counts = {p.name: 0 for p in self.providers}
        self.error_counts = {p.name: 0 for p in self.providers}
        self.last_used = None
        self.last_error = None
        
        logger.info(f"[AIClient] Initialisé avec {len(self.providers)} providers: "
                   f"{[p.name for p in self.providers]}")
    
    async def generate(
        self,
        prompt: str,
        system_prompt: str,
        response_format: Optional[str] = None,  # "json" ou None
        diagnostic_data: Optional[Dict[str, Any]] = None  # Pour template fallback
    ) -> Tuple[str, AIProvider]:
        """
        Génère une réponse IA avec cascade automatique.
        
        Args:
            prompt: Prompt utilisateur
            system_prompt: System prompt (rôle IA)
            response_format: "json" pour forcer JSON output, None sinon
            diagnostic_data: Données diagnostic pour template fallback
        
        Returns:
            (content, provider_used)
        
        Raises:
            Exception: Si même le template fallback échoue (très rare)
        """
        
        for provider in self.providers:
            # Skip template sauf si dernier recours
            if provider.name == AIProvider.TEMPLATE and len(self.providers) > 1:
                if provider != self.providers[-1]:
                    continue
            
            try:
                logger.info(f"[AIClient] Tentative {provider.name}...")
                
                if provider.name == AIProvider.TEMPLATE:
                    content = self._generate_template(diagnostic_data or {})
                else:
                    content = await self._call_provider(
                        provider=provider,
                        prompt=prompt,
                        system_prompt=system_prompt,
                        response_format=response_format
                    )
                
                self.success_counts[provider.name] += 1
                self.last_used = provider.name
                self.last_error = None
                
                logger.info(f"[AIClient] ✅ {provider.name} success ({len(content)} chars)")
                
                return content, provider.name
                
            except Exception as e:
                self.error_counts[provider.name] += 1
                self.last_error = str(e)
                logger.error(f"[AIClient] ❌ {provider.name} failed: {str(e)}")
                continue  # Passe au fallback suivant
        
        # Aucun provider n'a fonctionné (ne devrait jamais arriver car template toujours dispo)
        logger.critical("[AIClient] ⚠️ TOUS PROVIDERS ÉCHOUÉS (impossible normalement)")
        raise Exception("Tous les providers IA ont échoué, y compris template fallback")
    
    async def _call_provider(
        self,
        provider: ProviderConfig,
        prompt: str,
        system_prompt: str,
        response_format: Optional[str] = None
    ) -> str:
        """Appel à un provider IA spécifique via HTTP"""
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {provider.api_key}"
        }
        
        # Ajout header spécifique pour Claude Gateway si besoin
        if provider.name == AIProvider.CLAUDE_GATEWAY:
            headers["anthropic-version"] = "2023-06-01"
        
        payload = {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": provider.max_tokens,
            "temperature": provider.temperature
        }
        
        # Force JSON output si demandé (Claude, DeepSeek supportent)
        if response_format == "json":
            if provider.name in [AIProvider.CLAUDE_GATEWAY, AIProvider.DEEPSEEK]:
                payload["response_format"] = {"type": "json_object"}
        
        async with httpx.AsyncClient(timeout=provider.timeout / 1000) as client:
            response = await client.post(
                provider.endpoint,
                headers=headers,
                json=payload
            )
            
            if response.status_code != 200:
                error_text = response.text[:200]  # Limite pour logs
                raise Exception(f"HTTP {response.status_code}: {error_text}")
            
            data = response.json()
            
            # Extraction contenu selon format provider
            return self._extract_content(data, provider.name)
    
    def _extract_content(self, data: Dict[str, Any], provider_name: AIProvider) -> str:
        """Extrait le contenu de la réponse selon le provider"""
        
        try:
            if provider_name in [AIProvider.CLAUDE_GATEWAY, AIProvider.DEEPSEEK, AIProvider.GLM4]:
                # Format OpenAI-compatible
                return data["choices"][0]["message"]["content"]
            else:
                raise ValueError(f"Unknown provider format: {provider_name}")
        except (KeyError, IndexError) as e:
            logger.error(f"[AIClient] Format response invalide: {data}")
            raise Exception(f"Format response invalide pour {provider_name}: {str(e)}")
    
    def _generate_template(self, diagnostic_data: Dict[str, Any]) -> str:
        """
        Template fallback basique (sans IA).
        Utilisé uniquement si tous les providers IA échouent.
        """
        
        nom = diagnostic_data.get("nom", "Prospect")
        score = diagnostic_data.get("score", 0)
        secteur = diagnostic_data.get("secteur", "votre secteur")
        faille_principale = diagnostic_data.get("faille_principale", "des opportunités d'amélioration")
        
        return f"""Bonjour {nom},

Votre diagnostic révèle un score de {score}/100 dans {secteur}.

L'analyse identifie {faille_principale} comme point d'attention prioritaire.

Pour optimiser votre acquisition client et rentabiliser vos investissements marketing, un accompagnement structuré sur 90 jours permettrait de corriger ces failles et d'accélérer significativement vos résultats.

Je vous recontacte dans les 24-48h sur WhatsApp pour discuter d'un plan d'action personnalisé adapté à votre situation.

K. STÉPHANE
Consultant Stratégique — ePerformance
+225 01 51 17 06 66
https://eperformance.pro"""
    
    def get_stats(self) -> Dict[str, Any]:
        """Statistiques d'utilisation des providers"""
        
        total_calls = sum(self.success_counts.values())
        
        return {
            "total_calls": total_calls,
            "success_by_provider": self.success_counts,
            "errors_by_provider": self.error_counts,
            "last_used": self.last_used,
            "last_error": self.last_error,
            "success_rate": {
                provider: (
                    round(self.success_counts[provider] / total_calls * 100, 2)
                    if total_calls > 0 else 0
                )
                for provider in self.success_counts.keys()
            }
        }
    
    def reset_stats(self):
        """Reset les statistiques (utile pour tests)"""
        self.success_counts = {p.name: 0 for p in self.providers}
        self.error_counts = {p.name: 0 for p in self.providers}
        self.last_used = None
        self.last_error = None
        logger.info("[AIClient] Stats reset")


# Instance singleton globale (optionnel, pour réutilisation)
_ai_client_instance = None

def get_ai_client() -> AIClient:
    """Retourne l'instance singleton du client IA"""
    global _ai_client_instance
    if _ai_client_instance is None:
        _ai_client_instance = AIClient()
    return _ai_client_instance

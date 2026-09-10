"""
Multi-provider AI configuration avec cascade fallback.
Providers : Claude Gateway (aiapiflow.com) → DeepSeek → GLM-4 → Template

ePerformance API Flow - Unified IA System
"""

import os
from typing import Optional, List
from dataclasses import dataclass
from enum import Enum


class AIProvider(str, Enum):
    """Providers IA disponibles"""
    CLAUDE_GATEWAY = "claude_gateway"
    DEEPSEEK = "deepseek"
    GLM4 = "glm4"
    TEMPLATE = "template"


@dataclass
class ProviderConfig:
    """Configuration d'un provider IA"""
    name: AIProvider
    endpoint: str
    api_key: str
    model: str
    timeout: int  # milliseconds
    max_tokens: int
    temperature: float
    enabled: bool = True
    
    def is_configured(self) -> bool:
        """Vérifie si le provider est correctement configuré"""
        if not self.enabled:
            return False
        if self.name == AIProvider.TEMPLATE:
            return True  # Template toujours disponible
        return bool(self.api_key and self.endpoint)


class AIProvidersConfig:
    """Configuration centralisée des providers IA"""
    
    # PRIMARY: Claude via aiapiflow.com Gateway
    PRIMARY = ProviderConfig(
        name=AIProvider.CLAUDE_GATEWAY,
        endpoint=os.getenv("CLAUDE_GATEWAY_URL", "https://api.aiapiflow.com/v1/chat/completions"),
        api_key=os.getenv("CLAUDE_GATEWAY_KEY", ""),
        model=os.getenv("CLAUDE_MODEL", "claude-opus-4"),
        timeout=30000,  # 30s
        max_tokens=2000,
        temperature=0.7
    )
    
    # FALLBACK 1: DeepSeek
    FALLBACK_1 = ProviderConfig(
        name=AIProvider.DEEPSEEK,
        endpoint=os.getenv("DEEPSEEK_ENDPOINT", "https://api.deepseek.com/v1/chat/completions"),
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        timeout=25000,  # 25s
        max_tokens=2000,
        temperature=0.7
    )
    
    # FALLBACK 2: GLM-4
    FALLBACK_2 = ProviderConfig(
        name=AIProvider.GLM4,
        endpoint=os.getenv("GLM4_ENDPOINT", "https://open.bigmodel.cn/api/paas/v4/chat/completions"),
        api_key=os.getenv("GLM4_API_KEY", ""),
        model=os.getenv("GLM4_MODEL", "glm-4-plus"),
        timeout=45000,  # 45s (GLM4 plus lent)
        max_tokens=2000,
        temperature=0.7
    )
    
    # FALLBACK ULTIME: Template (sans IA)
    TEMPLATE_FALLBACK = ProviderConfig(
        name=AIProvider.TEMPLATE,
        endpoint="",
        api_key="",
        model="template",
        timeout=0,
        max_tokens=0,
        temperature=0.0,
        enabled=True
    )
    
    @classmethod
    def get_cascade(cls) -> List[ProviderConfig]:
        """
        Retourne la cascade de providers dans l'ordre.
        Filtre automatiquement les providers non configurés.
        """
        providers = [cls.PRIMARY, cls.FALLBACK_1, cls.FALLBACK_2]
        configured = [p for p in providers if p.is_configured()]
        
        # Toujours ajouter template fallback à la fin
        configured.append(cls.TEMPLATE_FALLBACK)
        
        return configured
    
    @classmethod
    def get_provider(cls, name: AIProvider) -> Optional[ProviderConfig]:
        """Récupère un provider par nom"""
        providers = {
            AIProvider.CLAUDE_GATEWAY: cls.PRIMARY,
            AIProvider.DEEPSEEK: cls.FALLBACK_1,
            AIProvider.GLM4: cls.FALLBACK_2,
            AIProvider.TEMPLATE: cls.TEMPLATE_FALLBACK
        }
        return providers.get(name)
    
    @classmethod
    def get_primary(cls) -> ProviderConfig:
        """Retourne le provider primaire configuré"""
        cascade = cls.get_cascade()
        return cascade[0] if cascade else cls.TEMPLATE_FALLBACK

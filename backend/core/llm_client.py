"""
LLM Client unifié pour DeepSeek, Claude, OpenAI
Utilisé par : chatbot, design_pipeline, agents IA

Réutilise le code testé de design_pipeline.py avec adaptations async
"""
import json
import urllib.request
import urllib.error
import asyncio
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import time
import sys
import os


class LLMClient:
    """
    Client unifié pour appeler DeepSeek, Claude, OpenAI avec fallback automatique
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Charger config depuis config_ia.json
        
        Args:
            config_path: Chemin vers config_ia.json (optionnel)
        """
        self.config = self._load_config(config_path)
        
        # Clés API
        self.deepseek_key = self.config.get('api_keys', {}).get('deepseek', '')
        self.claude_gateway_url = self.config.get('claude_gateway', {}).get('url', '')
        self.claude_gateway_key = self.config.get('claude_gateway', {}).get('api_key', '')
        self.claude_model = self.config.get('claude_gateway', {}).get('model', 'claude-sonnet-5')
        self.openai_key = self.config.get('api_keys', {}).get('openai', '')
        
        # Provider par défaut
        provider_raw = self.config.get('provider', 'deepseek')
        self.preferred_provider = 'claude' if provider_raw == 'anthropic' else provider_raw
        
        # Ordre de fallback
        self.fallback_order = ['deepseek', 'claude', 'openai']
    
    def _load_config(self, config_path: Optional[str]) -> Dict:
        """
        Charger la configuration depuis config_ia.json ou variables d'environnement
        
        Priorité:
        1. Fichier config_ia.json (dev local)
        2. Variables d'environnement (Railway, production)
        """
        if config_path:
            config_file = Path(config_path)
        else:
            # Chercher dans plusieurs emplacements
            possible_paths = [
                Path(__file__).parent.parent.parent.parent / "toolkit_eperformance" / "config_ia.json",
                Path("/home/ballo/OX6A/toolkit_eperformance/config_ia.json"),
                Path(__file__).parent / "config_ia.json",
            ]
            config_file = None
            for path in possible_paths:
                if path.exists():
                    config_file = path
                    break
        
        # Tenter de charger depuis fichier
        if config_file and config_file.exists():
            try:
                return json.loads(config_file.read_text())
            except Exception as e:
                print(f"⚠️  Erreur lecture config_ia.json: {e}", file=sys.stderr)
        
        # Fallback sur variables d'environnement (Railway)
        env_config = {
            'api_keys': {
                'deepseek': os.getenv('DEEPSEEK_API_KEY', ''),
                'openai': os.getenv('OPENAI_API_KEY', ''),
            },
            'claude_gateway': {
                'url': os.getenv('CLAUDE_GATEWAY_URL', ''),
                'api_key': os.getenv('CLAUDE_GATEWAY_KEY', ''),
                'model': os.getenv('CLAUDE_MODEL', 'claude-sonnet-5')
            },
            'provider': os.getenv('DEFAULT_LLM_PROVIDER', 'deepseek')
        }
        
        # Vérifier si au moins une clé API est présente
        has_keys = any([
            env_config['api_keys']['deepseek'],
            env_config['api_keys']['openai'],
            env_config['claude_gateway']['api_key']
        ])
        
        if has_keys:
            print(f"✅ Configuration LLM chargée depuis variables d'environnement", file=sys.stderr)
            return env_config
        
        print(f"⚠️  config_ia.json non trouvé et aucune variable d'environnement", file=sys.stderr)
        return {}
    
    async def chat_completion(
        self,
        provider: Optional[str],
        messages: List[Dict[str, str]],
        max_tokens: int = 2000,
        temperature: float = 0.7,
        retry_count: int = 2
    ) -> Dict:
        """
        Appel unifié pour tous les providers avec fallback automatique
        
        Args:
            provider: 'deepseek' | 'claude' | 'openai' | None (utilise preferred_provider)
            messages: [{"role": "system|user|assistant", "content": "..."}]
            max_tokens: Limite de tokens
            temperature: Créativité (0.0-2.0)
            retry_count: Nombre de tentatives par provider
        
        Returns:
            {
                'content': str,  # Réponse générée
                'tokens_used': int,
                'model': str,
                'provider': str
            }
        """
        # Déterminer le provider principal
        if provider is None:
            provider = self.preferred_provider
        
        provider = provider.lower()
        
        # Ordre de tentative avec fallback
        if provider == 'claude':
            primary = 'claude'
            fallbacks = ['deepseek', 'openai']
        elif provider == 'openai':
            primary = 'openai'
            fallbacks = ['deepseek', 'claude']
        else:  # deepseek par défaut
            primary = 'deepseek'
            fallbacks = ['claude', 'openai']
        
        # Tenter le provider principal
        result = await self._try_provider_with_retry(
            provider=primary,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            retry_count=retry_count
        )
        
        if result:
            print(f"🤖 LLM utilisé : {result['provider']} (provider principal)", file=sys.stderr)
            return result
        
        # Fallback sur les autres providers
        for fallback_provider in fallbacks:
            print(f"⚠️  {primary} indisponible, fallback sur {fallback_provider}...", file=sys.stderr)
            
            result = await self._try_provider_with_retry(
                provider=fallback_provider,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                retry_count=retry_count
            )
            
            if result:
                print(f"🤖 LLM utilisé : {result['provider']} (fallback)", file=sys.stderr)
                return result
        
        # Tous les providers ont échoué
        print(f"❌ Aucun LLM disponible (tous les providers ont échoué)", file=sys.stderr)
        return {
            'content': '',
            'tokens_used': 0,
            'model': 'none',
            'provider': 'none'
        }
    
    async def _try_provider_with_retry(
        self,
        provider: str,
        messages: List[Dict[str, str]],
        max_tokens: int,
        temperature: float,
        retry_count: int
    ) -> Optional[Dict]:
        """
        Tenter un provider avec retry et backoff exponentiel
        """
        for attempt in range(retry_count):
            try:
                result = None
                
                if provider == 'deepseek' and self.deepseek_key:
                    result = await self._call_deepseek(messages, temperature, max_tokens)
                
                elif provider == 'claude' and self.claude_gateway_url and self.claude_gateway_key:
                    result = await self._call_claude(messages, temperature, max_tokens)
                
                elif provider == 'openai' and self.openai_key:
                    result = await self._call_openai(messages, temperature, max_tokens)
                
                # Si résultat valide, retourner immédiatement
                if result and result.get('content'):
                    return result
                
                # Sinon, retry si tentatives restantes
                if attempt < retry_count - 1:
                    wait_time = 2 ** attempt  # Backoff exponentiel: 1s, 2s, 4s
                    print(f"⚠️  {provider} tentative {attempt+1}/{retry_count} retourné vide, retry dans {wait_time}s...", file=sys.stderr)
                    await asyncio.sleep(wait_time)
            
            except Exception as e:
                if attempt < retry_count - 1:
                    wait_time = 2 ** attempt
                    print(f"⚠️  {provider} erreur ({type(e).__name__}: {str(e)[:100]}), retry dans {wait_time}s...", file=sys.stderr)
                    await asyncio.sleep(wait_time)
                else:
                    print(f"⚠️  {provider} échec définitif: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        
        return None
    
    async def _call_deepseek(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int
    ) -> Optional[Dict]:
        """
        Appeler DeepSeek API (réutilise logique de design_pipeline.py)
        Adapté pour async avec asyncio
        """
        if not self.deepseek_key:
            return None
        
        body = json.dumps({
            "model": "deepseek-chat",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode("utf-8")
        
        try:
            # Utiliser run_in_executor pour l'appel synchrone urllib
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._sync_deepseek_call,
                body
            )
            return result
        
        except Exception as e:
            print(f"⚠️  DeepSeek API échec: {e}", file=sys.stderr)
            return None
    
    def _sync_deepseek_call(self, body: bytes) -> Optional[Dict]:
        """
        Appel synchrone DeepSeek (pour run_in_executor)
        """
        req = urllib.request.Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.deepseek_key}",
                "Content-Type": "application/json"
            },
        )
        
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
        
        if "choices" in data and len(data["choices"]) > 0:
            content = data["choices"][0]["message"]["content"]
            if content:  # Pas de limite 50 chars, même réponse courte valide
                return {
                    'content': content,
                    'tokens_used': data.get('usage', {}).get('total_tokens', 0),
                    'model': 'deepseek-chat',
                    'provider': 'DeepSeek'
                }
        
        return None
    
    async def _call_claude(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int
    ) -> Optional[Dict]:
        """
        Appeler Claude via Gateway (réutilise logique de design_pipeline.py)
        Adapté pour async avec asyncio
        """
        if not self.claude_gateway_url or not self.claude_gateway_key:
            return None
        
        # Format compatible OpenAI pour le Gateway
        body = json.dumps({
            "model": self.claude_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode("utf-8")
        
        try:
            # Utiliser run_in_executor pour l'appel synchrone urllib
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._sync_claude_call,
                body
            )
            return result
        
        except Exception as e:
            print(f"⚠️  Claude API échec: {e}", file=sys.stderr)
            return None
    
    def _sync_claude_call(self, body: bytes) -> Optional[Dict]:
        """
        Appel synchrone Claude (pour run_in_executor)
        """
        # Normaliser l'URL
        gateway_url = self.claude_gateway_url.rstrip('/')
        if not gateway_url.endswith('/completions'):
            gateway_url = f"{gateway_url}/v1/chat/completions"
        
        req = urllib.request.Request(
            gateway_url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.claude_gateway_key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
        )
        
        with urllib.request.urlopen(req, timeout=240) as resp:
            data = json.loads(resp.read())
        
        # Format de réponse compatible OpenAI
        if "choices" in data and len(data["choices"]) > 0:
            content = data["choices"][0]["message"]["content"]
            if content:
                return {
                    'content': content,
                    'tokens_used': data.get('usage', {}).get('total_tokens', 0),
                    'model': self.claude_model,
                    'provider': 'Claude Sonnet 5'
                }
        
        # Format Anthropic natif
        elif "content" in data:
            if isinstance(data["content"], list):
                content = data["content"][0].get("text", "")
            else:
                content = data["content"]
            
            if content:
                return {
                    'content': content,
                    'tokens_used': data.get('usage', {}).get('input_tokens', 0) + data.get('usage', {}).get('output_tokens', 0),
                    'model': self.claude_model,
                    'provider': 'Claude Sonnet 5'
                }
        
        return None
    
    async def _call_openai(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int
    ) -> Optional[Dict]:
        """
        Appeler OpenAI API (fallback final)
        """
        if not self.openai_key:
            return None
        
        body = json.dumps({
            "model": self.config.get('models', {}).get('openai', 'gpt-4o-mini'),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode("utf-8")
        
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._sync_openai_call,
                body
            )
            return result
        
        except Exception as e:
            print(f"⚠️  OpenAI API échec: {e}", file=sys.stderr)
            return None
    
    def _sync_openai_call(self, body: bytes) -> Optional[Dict]:
        """
        Appel synchrone OpenAI (pour run_in_executor)
        """
        try:
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=body,
                headers={
                    "Authorization": f"Bearer {self.openai_key}",
                    "Content-Type": "application/json"
                },
            )
            
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            
            if "choices" in data and len(data["choices"]) > 0:
                content = data["choices"][0]["message"]["content"]
                if content and len(content) > 50:
                    return {
                        'content': content,
                        'tokens_used': data.get('usage', {}).get('total_tokens', 0),
                        'model': data.get('model', 'gpt-4o-mini'),
                        'provider': 'OpenAI'
                    }
            
            return None
        
        except Exception as e:
            print(f"⚠️  OpenAI sync call error: {e}", file=sys.stderr)
            return None


# Test rapide
if __name__ == "__main__":
    async def test():
        client = LLMClient()
        
        messages = [
            {"role": "system", "content": "Tu es un assistant utile."},
            {"role": "user", "content": "Dis bonjour en une phrase."}
        ]
        
        result = await client.chat_completion(
            provider=None,  # Utilise preferred_provider
            messages=messages,
            max_tokens=100,
            temperature=0.7
        )
        
        print(f"\n✅ Test réussi !")
        print(f"Provider: {result['provider']}")
        print(f"Tokens: {result['tokens_used']}")
        print(f"Réponse: {result['content'][:200]}...")
    
    asyncio.run(test())

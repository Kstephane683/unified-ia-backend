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


# ============================================================================
# DEEPSEEK — RÉGLAGES DU MODÈLE (tâche 6.3-BIS A.1)
#
# AUDIT AVANT : la valeur était écrite en dur, deux fois, à l'intérieur de
# `_call_deepseek` / `_sync_deepseek_call` :
#     "model": "deepseek-chat"
# et l'URL l'était aussi : "https://api.deepseek.com/v1/chat/completions".
# Aucune variable d'environnement DEEPSEEK_MODEL n'existait sur Railway
# (`railway variables` ne la listait pas) : le modèle était donc NON
# surchargeable et il fallait redéployer pour le changer.
#
# APRÈS : `deepseek-flash` est l'ID unique et natif — c'est aussi lui qui
# porte la vision. Les alias `deepseek-chat`, `deepseek-v4-flash` et
# `deepseek-v4-flash-vision-exp` sont routés par le fournisseur vers ce même
# modèle ; on n'écrit plus que l'ID canonique, surchargeable par
# DEEPSEEK_MODEL sans redéploiement de code.
#
# `deepseek-flash` est un modèle de RAISONNEMENT : il émet d'abord un
# `reasoning_content` (brouillon interne), puis le `content` utile, et
# `max_tokens` couvre LES DEUX. Sans `reasoning_effort`, une réponse peut
# revenir VIDE avec `finish_reason=length` — le code la prendrait pour une
# panne du provider et basculerait silencieusement sur Claude. D'où :
#   · `reasoning_effort=none` par défaut (surchargeable) ;
#   · un rejeu automatique avec budget doublé si la réponse revient vide
#     alors qu'un raisonnement a bien été émis.
# Mesuré sur ce dépôt (agent-ia-web/RAPPORT_FINAL_EPERF_CORE.md) :
# max_tokens=150 → 612 car. de raisonnement, 0 de contenu ; max_tokens=400
# → 968 car. de raisonnement, 167 car. de contenu.
# ============================================================================

DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
DEEPSEEK_API_URL = os.getenv(
    "DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"
)
DEEPSEEK_REASONING_EFFORT = os.getenv("DEEPSEEK_REASONING_EFFORT", "none")
# Budget minimal quand le raisonnement est actif (il mange le budget)
DEEPSEEK_MIN_TOKENS_RAISONNEMENT = int(os.getenv("DEEPSEEK_MIN_TOKENS", "2048"))


def _deepseek_body(
    messages: List[Dict],
    temperature: float,
    max_tokens: int,
) -> Dict:
    """Construire le corps DeepSeek (OpenAI-compatible).

    `messages` peut porter du contenu multi-parties
    (`[{type:text}, {type:image_url}]`) : c'est le format natif de la vision,
    on le laisse passer tel quel — `json.dumps` le sérialise sans adaptation.
    """
    body: Dict = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # `reasoning_effort` n'est posé que s'il porte une valeur utile : la valeur
    # sentinelle `default` laisse le fournisseur décider (raisonnement actif).
    if DEEPSEEK_REASONING_EFFORT and DEEPSEEK_REASONING_EFFORT.lower() not in (
        "default",
        "defaut",
        "",
    ):
        body["reasoning_effort"] = DEEPSEEK_REASONING_EFFORT
    return body


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
        Charger la configuration depuis les variables d'environnement ou config_ia.json

        Priorité:
        1. Variables d'environnement (Railway, Docker, production)
        2. Fichier config_ia.json (repli, développement local)

        POURQUOI CET ORDRE — ne pas l'inverser sans lire ceci.
        L'ordre inverse (fichier d'abord) rendait la configuration DESTRUCTIBLE
        EN SILENCE : `json.loads()` était retourné sans condition dès que le
        fichier existait et se parsait, si bien qu'un config_ia.json présent
        mais vide (`{}`) ou dépourvu de clés court-circuitait l'environnement —
        le backend démarrait alors sans aucune clé, sans erreur et sans trace.
        C'est le défaut qui rendait dangereuse la purge de config_ia.json
        prévue par la refonte du toolkit (condition bloquante D8).
        Un fichier sans clé exploitable ne court-circuite plus rien : il est
        traité comme absent.
        """
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

        if self._a_des_cles(env_config):
            print("✅ Configuration LLM chargée depuis variables d'environnement", file=sys.stderr)
            return env_config

        config_file = self._trouver_config(config_path)
        if config_file:
            try:
                depuis_fichier = json.loads(config_file.read_text())
            except Exception as e:
                print(f"⚠️  Erreur lecture config_ia.json: {e}", file=sys.stderr)
            else:
                if self._a_des_cles(depuis_fichier):
                    print(f"✅ Configuration LLM chargée depuis {config_file}", file=sys.stderr)
                    return depuis_fichier
                print(f"⚠️  {config_file} ne porte aucune clé exploitable — ignoré, "
                      "l'environnement n'a pas été court-circuité", file=sys.stderr)

        print("⚠️  Aucune clé LLM : ni variable d'environnement, ni config_ia.json exploitable",
              file=sys.stderr)
        return {}

    @staticmethod
    def _a_des_cles(config: Dict) -> bool:
        """Vrai si la configuration porte au moins une clé utilisable.

        Sert de garde : une configuration vide ne doit jamais être retournée
        comme si elle était valide, sinon l'absence de clé devient silencieuse.
        """
        if not isinstance(config, dict):
            return False
        cles = config.get('api_keys') or {}
        passerelle = config.get('claude_gateway') or {}
        return bool(
            (isinstance(cles, dict) and (cles.get('deepseek') or cles.get('openai')))
            or (isinstance(passerelle, dict) and passerelle.get('api_key'))
        )

    @staticmethod
    def _trouver_config(config_path: Optional[str]) -> Optional[Path]:
        """Localiser config_ia.json : chemin explicite, sinon emplacements connus."""
        if config_path:
            chemin = Path(config_path)
            return chemin if chemin.exists() else None
        for path in (
            Path(__file__).parent.parent.parent.parent / "toolkit_eperformance" / "config_ia.json",
            Path("/home/ballo/OX6A/toolkit_eperformance/config_ia.json"),
            Path(__file__).parent / "config_ia.json",
        ):
            if path.exists():
                return path
        return None
    
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
        messages: List[Dict],
        temperature: float,
        max_tokens: int
    ) -> Optional[Dict]:
        """
        Appeler DeepSeek API (réutilise logique de design_pipeline.py)
        Adapté pour async avec asyncio

        `messages` accepte le contenu multi-parties (vision) : la seule
        contrainte est que `messages` reste une liste de dicts sérialisables.
        """
        if not self.deepseek_key:
            return None

        loop = asyncio.get_event_loop()
        # Budget « raisonnement » : le brouillon interne se paie sur le même
        # budget que la réponse, donc on plancher à une valeur utilisable.
        budget = max_tokens
        if DEEPSEEK_REASONING_EFFORT and DEEPSEEK_REASONING_EFFORT.lower() not in (
            "default",
            "defaut",
            "",
            "none",
        ):
            budget = max(max_tokens, DEEPSEEK_MIN_TOKENS_RAISONNEMENT)

        try:
            body = json.dumps(
                _deepseek_body(messages, temperature, budget)
            ).encode("utf-8")
            result = await loop.run_in_executor(None, self._sync_deepseek_call, body)

            # Rejeu : réponse VIDE alors qu'un raisonnement a été émis =
            # budget mangé par le brouillon, ce n'est PAS une panne du
            # provider. On rejoue une fois avec le budget doublé.
            if result and result.get("reasoning_truncated"):
                print(
                    f"⚠️  DeepSeek {DEEPSEEK_MODEL}: réponse vide (raisonnement "
                    f"tronqué), rejeu avec max_tokens={budget * 2}",
                    file=sys.stderr,
                )
                body = json.dumps(
                    _deepseek_body(messages, temperature, budget * 2)
                ).encode("utf-8")
                result = await loop.run_in_executor(None, self._sync_deepseek_call, body)

            return result

        except Exception as e:
            print(f"⚠️  DeepSeek API échec: {e}", file=sys.stderr)
            return None

    def _sync_deepseek_call(self, body: bytes) -> Optional[Dict]:
        """
        Appel synchrone DeepSeek (pour run_in_executor)

        Ne remonte JAMAIS `reasoning_content` : c'est le brouillon interne du
        modèle, il ne doit pas devenir une réponse affichée au visiteur.
        """
        req = urllib.request.Request(
            DEEPSEEK_API_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {self.deepseek_key}",
                "Content-Type": "application/json"
            },
        )

        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())

        if "choices" in data and len(data["choices"]) > 0:
            choice = data["choices"][0]
            message = choice.get("message") or {}
            content = message.get("content")
            if content:  # Pas de limite 50 chars, même réponse courte valide
                return {
                    'content': content,
                    'tokens_used': data.get('usage', {}).get('total_tokens', 0),
                    'model': DEEPSEEK_MODEL,
                    'provider': 'DeepSeek'
                }
            # Contenu vide + raisonnement émis → troncature, pas une panne.
            if (message.get("reasoning_content") or "").strip():
                return {
                    'content': '',
                    'tokens_used': data.get('usage', {}).get('total_tokens', 0),
                    'model': DEEPSEEK_MODEL,
                    'provider': 'DeepSeek',
                    'reasoning_truncated': True,
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

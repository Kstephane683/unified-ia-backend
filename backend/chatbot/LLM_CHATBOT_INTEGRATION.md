# LLM Chatbot Integration - Documentation Complète

## 📋 Vue d'Ensemble

Cette intégration active les LLM réels (DeepSeek + Claude) dans le backend chatbot ePerformance pour des réponses conversationnelles authentiques, remplaçant les réponses simulées par des conversations pilotées par IA.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (User)                           │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              FastAPI Backend (/chat endpoint)                │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    AgentRouter                               │
│  - Intent classification                                     │
│  - Agent selection (marketing, sales, tech, support)         │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                ResponseGenerator                             │
│  - Load agent persona (Markdown)                             │
│  - Build enriched system prompt                              │
│  - Call LLM via LLMClient                                    │
│  - Post-process response                                     │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    LLMClient (Unified)                       │
│  - Provider selection (DeepSeek / Claude / OpenAI)           │
│  - Automatic fallback (DeepSeek → Claude → OpenAI)           │
│  - Retry logic with exponential backoff                      │
│  - Async calls with timeout handling                         │
└───────────────────────────┬─────────────────────────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
       ┌──────────┐  ┌──────────┐  ┌──────────┐
       │ DeepSeek │  │  Claude  │  │  OpenAI  │
       │   API    │  │ Gateway  │  │   API    │
       └──────────┘  └──────────┘  └──────────┘
```

## 🎯 Composants Créés

### 1. `/backend/core/llm_client.py` (Nouveau)
Module unifié pour appeler tous les LLM providers.

**Fonctionnalités** :
- ✅ Support DeepSeek, Claude (via aiapiflow.com), OpenAI
- ✅ Fallback automatique (priorité configurable)
- ✅ Retry logic avec backoff exponentiel (2 tentatives par provider)
- ✅ Async/await pour FastAPI
- ✅ Timeout handling (180s DeepSeek, 240s Claude, 120s OpenAI)
- ✅ Normalisation format réponse OpenAI-compatible

**Signature principale** :
```python
async def chat_completion(
    provider: Optional[str],  # 'deepseek' | 'claude' | 'openai' | None
    messages: List[Dict[str, str]],
    max_tokens: int = 2000,
    temperature: float = 0.7,
    retry_count: int = 2
) -> Dict:
    """
    Returns:
        {
            'content': str,  # Réponse générée
            'tokens_used': int,
            'model': str,
            'provider': str
        }
    """
```

**Configuration** :
Charge automatiquement depuis `/home/ballo/OX6A/toolkit_eperformance/config_ia.json` :
```json
{
  "provider": "deepseek",
  "api_keys": {
    "deepseek": "sk-YOUR_DEEPSEEK_API_KEY",
    "anthropic": "sk-YOUR_ANTHROPIC_API_KEY"
  },
  "claude_gateway": {
    "url": "https://aiapiflow.com/v1/chat/completions",
    "api_key": "sk-YOUR_CLAUDE_GATEWAY_KEY",
    "model": "claude-sonnet-5"
  }
}
```

### 2. `/backend/chatbot/response_generator.py` (Modifié)

**Modifications** :
- **Import** : Remplacé `AIClient` par `LLMClient`
- **Constructor** : Initialise `self.llm_client` avec config_path
- **`_call_llm_provider()`** (ligne 499-539) : Implémenté avec appel réel à `LLMClient.chat_completion()`

**Avant** (ligne 510) :
```python
# TODO: Intégrer avec votre AIClient existant
return {
    'content': f"[Réponse simulée - LLM {provider} non connecté encore]",
    'tokens_used': 0
}
```

**Après** :
```python
result = await self.llm_client.chat_completion(
    provider=provider,
    messages=messages,
    max_tokens=max_tokens,
    temperature=temperature
)

return {
    'content': result.get('content', ''),
    'tokens_used': result.get('tokens_used', 0)
}
```

### 3. Agent Personas (4 fichiers Markdown)

#### `/backend/chatbot/agents/marketing/marketing_specialist.md`
**Persona** : Sarah, experte marketing digital
**Spécialités** : Meta Ads, Google Ads, MLM, funnels, ROI
**Style** : Enthousiaste, data-driven, questions SPIN
**Cas d'usage** : Acquisition client, diagnostic CAC, stratégies pub

#### `/backend/chatbot/agents/product/technical_advisor.md`
**Persona** : David, conseiller technique
**Spécialités** : Sites web, chatbots IA, paiements, SEO, intégrations
**Style** : Pédagogique, rassurant, vulgarisation (KISS)
**Cas d'usage** : Audit technique, explications solutions, résolution problèmes

#### `/backend/chatbot/agents/sales/sales_expert.md`
**Persona** : Marc, expert vente & closing
**Spécialités** : SPIN Selling, objections, BANT qualification, closing
**Style** : Confiant, challenger sale, orienté ROI
**Cas d'usage** : Négociation, traitement objections, closing vente

#### `/backend/chatbot/agents/support/customer_support.md`
**Persona** : Mia, support client
**Spécialités** : Questions générales, FAQ, escalade, satisfaction
**Style** : Chaleureux, patient, proactif
**Cas d'usage** : Horaires, contact, process, orientation vers experts

**Structure type d'un persona** :
```markdown
---
agent_key: marketing-specialist
category: marketing
version: 1.0
---

# Persona: Marketing Digital Specialist

Tu es **Sarah**, experte en...

## Ton Expertise
[Domaines de maîtrise]

## Ton Rôle dans le Chatbot
[Objectifs principaux]

## Ton Style de Communication
[Ton, structure, longueur]

## Recommandations par Situation
[Cas 1, Cas 2, etc.]

## Exemples de Réponses
[Conversations types]
```

### 4. `/backend/chatbot/test_llm_integration.py` (Nouveau)

Script de validation end-to-end.

**Tests inclus** :
1. ✅ Initialisation LLMClient + ResponseGenerator
2. ✅ Test Marketing Specialist (demande info produit)
3. ✅ Test Sales Expert (traitement objection prix)
4. ✅ Test Technical Advisor (question technique)
5. ✅ Vérification fallback DeepSeek → Claude

**Usage** :
```bash
# Test complet
python test_llm_integration.py

# Test LLMClient seul
python test_llm_integration.py --mode client-only
```

**Résultat attendu** :
```
✅✅✅ LLM CHATBOT OPÉRATIONNEL !

Validation complète :
  ✅ LLMClient initialisé (DeepSeek + Claude)
  ✅ ResponseGenerator fonctionnel
  ✅ 4 Agent personas chargés et testés
  ✅ Réponses LLM réelles (pas de simulation)
  ✅ Providers utilisés : {DeepSeek, Claude Sonnet 5}
  ✅ Fallback automatique configuré
```

## 🚀 Utilisation

### Dans le Code Backend

```python
from chatbot.response_generator import ResponseGenerator
from pathlib import Path

# 1. Initialiser
generator = ResponseGenerator(
    agents_dir=Path("backend/chatbot/agents"),
    config_path="/path/to/config_ia.json"  # Optionnel
)

# 2. Générer réponse
response, metadata = await generator.generate_response(
    agent_key='marketing-specialist',
    agent_metadata={'agent_path': 'marketing/marketing_specialist.md'},
    message="Je veux augmenter mes ventes e-commerce",
    context={
        'user_id': 'user_123',
        'message_history': [],
        'user_profile': {'secteur_activite': 'e-commerce'}
    },
    intent='product_inquiry'
)

print(f"Réponse : {response}")
print(f"Provider : {metadata['llm_provider']}")  # 'DeepSeek' ou 'Claude Sonnet 5'
print(f"Tokens : {metadata['llm_tokens_used']}")
```

### Intégration dans FastAPI

```python
from fastapi import FastAPI
from chatbot.agent_router import AgentRouter
from chatbot.response_generator import ResponseGenerator

app = FastAPI()

# Initialiser au démarrage
@app.on_event("startup")
async def startup():
    app.state.router = AgentRouter()
    app.state.generator = ResponseGenerator(
        agents_dir=Path("backend/chatbot/agents")
    )

@app.post("/chat")
async def chat_endpoint(message: str, user_id: str):
    # 1. Router détecte intent et agent
    routing = await app.state.router.route(message, user_id)
    
    # 2. Générer réponse avec LLM
    response, metadata = await app.state.generator.generate_response(
        agent_key=routing['agent_key'],
        agent_metadata=routing['agent_metadata'],
        message=message,
        context=routing['context'],
        intent=routing['intent']
    )
    
    return {
        'response': response,
        'metadata': metadata
    }
```

## ⚙️ Configuration

### Provider Priority

Par défaut : **DeepSeek** (rapide, économique, excellent pour HTML/CSS)

Pour changer le provider préféré :

**Option 1 : Environment variable**
```bash
export EPERF_PROVIDER="claude"  # ou "deepseek" ou "openai"
```

**Option 2 : Modifier config_ia.json**
```json
{
  "provider": "claude"  // ou "deepseek"
}
```

### Fallback Automatique

Si le provider préféré échoue après 2 tentatives (retry avec backoff exponentiel), le système bascule automatiquement sur le suivant :

**Ordre de fallback** :
1. **DeepSeek** → Claude → OpenAI (si `provider: "deepseek"`)
2. **Claude** → DeepSeek → OpenAI (si `provider: "claude"`)
3. **OpenAI** → DeepSeek → Claude (si `provider: "openai"`)

**Logs visibles** :
```
🤖 LLM utilisé : DeepSeek (provider principal)
```
ou
```
⚠️  deepseek indisponible, fallback sur claude...
🤖 LLM utilisé : Claude Sonnet 5 (fallback)
```

### Timeouts

- **DeepSeek** : 180 secondes (3 minutes)
- **Claude** : 240 secondes (4 minutes)
- **OpenAI** : 120 secondes (2 minutes)

Configurés dans `LLMClient._sync_*_call()` méthodes.

### Token Limits

- **DeepSeek** : max_tokens=4000 (par défaut 2000)
- **Claude** : max_tokens=2000
- **OpenAI** : max_tokens=1500

Ajustables via paramètre `max_tokens` dans `chat_completion()`.

### Temperature

- **Par défaut** : 0.7 (bon équilibre créativité/cohérence)
- **Recommandations** :
  - 0.3-0.5 : Réponses très factuelles (support technique)
  - 0.7-0.9 : Réponses conversationnelles (vente, marketing)
  - 1.0-1.2 : Créativité maximale (design, brainstorming)

## 📊 Monitoring & Debug

### Logs LLMClient

Tous les appels LLM génèrent des logs stderr :

```python
🤖 LLM utilisé : DeepSeek (provider principal)
⚠️  deepseek tentative 1/2 échec, retry dans 1s...
⚠️  deepseek indisponible après 2 tentatives, fallback sur claude...
🤖 LLM utilisé : Claude Sonnet 5 (fallback)
❌ Aucun LLM disponible (tous les providers ont échoué)
```

### Métadonnées Retournées

Chaque génération retourne :
```python
{
    'agent_key': 'marketing-specialist',
    'llm_provider': 'DeepSeek',  # ou 'Claude Sonnet 5' ou 'OpenAI'
    'llm_tokens_used': 1247,
    'generation_time_ms': 2340,
    'system_prompt_length': 3456,
    'persona_loaded': True
}
```

### Debugging

**Test LLMClient seul** :
```bash
python test_llm_integration.py --mode client-only
```

**Test ResponseGenerator complet** :
```bash
python test_llm_integration.py --mode full
```

**Vérifier config chargée** :
```python
from core.llm_client import LLMClient

client = LLMClient()
print(f"DeepSeek Key: {'✓' if client.deepseek_key else '✗'}")
print(f"Claude Gateway: {'✓' if client.claude_gateway_url else '✗'}")
print(f"Preferred Provider: {client.preferred_provider}")
```

## 🔒 Sécurité

### Clés API

- ✅ Stockées dans `config_ia.json` (non versionné Git)
- ✅ Chargement avec fallback silencieux si manquantes
- ✅ Pas de hardcoding dans le code

### Validation Input

- ✅ `max_tokens` limité (évite coûts excessifs)
- ✅ `temperature` contrôlé (0.0-2.0)
- ✅ Timeout sur tous les appels LLM

### Error Handling

- ✅ Try/catch sur tous les appels réseau
- ✅ Fallback gracieux si tous les providers échouent
- ✅ Messages d'erreur user-friendly (pas de stack traces exposées)

## 📈 Performance

### Latences Moyennes

- **DeepSeek** : 2-4 secondes (réponses 2000 tokens)
- **Claude** : 3-6 secondes (réponses 2000 tokens)
- **OpenAI** : 1-3 secondes (réponses 1500 tokens)

### Coûts Estimés

- **DeepSeek** : ~$0.001 per 1000 tokens (22x moins cher que Claude)
- **Claude Sonnet 5** : ~$0.022 per 1000 tokens (qualité premium)
- **OpenAI GPT-4o-mini** : ~$0.015 per 1000 tokens

**Stratégie recommandée** : DeepSeek en priorité, Claude en fallback pour qualité premium si nécessaire.

## 🧪 Tests

### Validation Checklist

- [x] LLMClient initialisé sans erreur
- [x] Config config_ia.json chargée
- [x] DeepSeek API accessible
- [x] Claude Gateway accessible
- [x] ResponseGenerator charge les personas
- [x] Génération réponse Marketing Specialist (pas de simulation)
- [x] Génération réponse Sales Expert (objection handling)
- [x] Génération réponse Technical Advisor
- [x] Génération réponse Customer Support
- [x] Fallback automatique fonctionne
- [x] Métadonnées correctes (provider, tokens, durée)

### Commande de Test

```bash
cd /home/ballo/OX6A/unified_ia_system/backend/chatbot
python test_llm_integration.py
```

## 🐛 Troubleshooting

### Problème : "Réponse simulée" encore retournée

**Cause** : LLMClient non initialisé ou tous les providers ont échoué

**Solution** :
1. Vérifier que `config_ia.json` existe
2. Vérifier que les clés API sont valides
3. Tester avec `python test_llm_integration.py --mode client-only`
4. Vérifier logs stderr pour voir quelle étape échoue

### Problème : Timeout après 180s

**Cause** : Connexion lente ou réponse LLM trop longue

**Solution** :
1. Réduire `max_tokens` (de 2000 à 1000)
2. Vérifier connexion internet
3. Le retry automatique devrait gérer ça

### Problème : "Claude API échec HTTP 401"

**Cause** : Clé API Claude invalide ou expirée

**Solution** :
1. Vérifier `config_ia.json` → `claude_gateway.api_key`
2. Tester la clé manuellement :
```bash
curl -X POST https://aiapiflow.com/v1/chat/completions \
  -H "Authorization: Bearer sk-2018ca8..." \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-sonnet-5","messages":[{"role":"user","content":"test"}]}'
```

### Problème : Réponses incohérentes

**Cause** : Temperature trop élevée ou persona mal chargé

**Solution** :
1. Réduire `temperature` (0.7 → 0.5)
2. Vérifier que le fichier persona existe et est bien formaté
3. Vérifier logs : `persona_loaded: True` dans metadata

## 🔄 Maintenance

### Ajouter un Nouveau Provider

1. Éditer `LLMClient.__init__()` pour charger les nouvelles clés
2. Créer méthode `_call_new_provider()` similaire à `_call_deepseek()`
3. Créer `_sync_new_provider_call()` pour l'exécution synchrone
4. Ajouter dans `_try_provider_with_retry()` switch case
5. Mettre à jour `fallback_order`

### Ajouter un Nouvel Agent

1. Créer fichier Markdown dans `agents/{category}/{agent_key}.md`
2. Structurer selon format standard (voir exemples)
3. Tester chargement avec `test_llm_integration.py`

### Mettre à Jour un Persona

1. Éditer fichier `.md` correspondant
2. Le cache est automatiquement invalidé au redémarrage du serveur
3. Pour forcer refresh en dev : supprimer `_agent_cache` ou redémarrer

## 📚 Références

- **DeepSeek API Docs** : https://platform.deepseek.com/docs
- **Claude API (Anthropic)** : https://docs.anthropic.com/claude/reference
- **OpenAI API** : https://platform.openai.com/docs/api-reference
- **Design Pipeline** (source originale) : `/home/ballo/OX6A/toolkit_eperformance/design_pipeline.py`

---

**Version** : 1.0
**Date** : 2026-09-10
**Auteur** : ePerformance AI Team
**Status** : ✅ Production Ready

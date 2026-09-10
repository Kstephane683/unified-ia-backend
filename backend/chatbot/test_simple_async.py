#!/usr/bin/env python3
"""
Test simplifié : ResponseGenerator + LLMClient
Sans passer par les imports complexes
"""
import asyncio
import sys
from pathlib import Path

# Setup paths
backend_root = Path("/home/ballo/OX6A/unified_ia_system/backend")
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "core"))
sys.path.insert(0, str(backend_root / "chatbot"))

# Import direct
from llm_client import LLMClient

print("=" * 70)
print("TEST SIMPLIFIÉ - LLMClient avec Async")
print("=" * 70)
print()

async def test_llm_async():
    """Test LLMClient avec asyncio"""
    
    # 1. Init client
    print("1. Initialisation LLMClient...")
    client = LLMClient("/home/ballo/OX6A/toolkit_eperformance/config_ia.json")
    
    print(f"   - DeepSeek Key: {'✓' if client.deepseek_key else '✗'}")
    print(f"   - Claude Gateway: {'✓' if client.claude_gateway_url else '✗'}")
    print(f"   - Provider préféré: {client.preferred_provider}")
    print()
    
    # 2. Test appel simple
    print("2. Test appel LLM...")
    messages = [
        {"role": "system", "content": "Tu es un assistant utile."},
        {"role": "user", "content": "Dis bonjour en une phrase courte."}
    ]
    
    result = await client.chat_completion(
        provider=None,  # Utilise preferred_provider
        messages=messages,
        max_tokens=100,
        temperature=0.7
    )
    
    print(f"   ✅ Résultat:")
    print(f"      Provider: {result['provider']}")
    print(f"      Model: {result['model']}")
    print(f"      Tokens: {result['tokens_used']}")
    print(f"      Réponse: {result['content']}")
    print()
    
    if result['content'] and result['provider'] != 'none':
        print("✅✅✅ LLMClient fonctionne avec asyncio !")
        return True
    else:
        print("❌ LLMClient a échoué")
        return False

if __name__ == "__main__":
    try:
        success = asyncio.run(test_llm_async())
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ ERREUR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

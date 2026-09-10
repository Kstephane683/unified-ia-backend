"""
Test rapide des composants chatbot Phase 1-J2
IntentDetector, ContextBuilder, ChatbotService
"""
import sys
sys.path.insert(0, '/home/ballo/OX6A/unified_ia_system')

from backend.core.database import SessionLocal
from backend.chatbot.intent_detector import IntentDetector
from backend.chatbot.context_builder import ContextBuilder
from backend.chatbot.service import ChatbotService
import asyncio


def test_intent_detector():
    """Test du détecteur d'intent"""
    print("=" * 60)
    print("TEST 1: IntentDetector")
    print("=" * 60)
    
    detector = IntentDetector()
    
    test_messages = [
        "Je voudrais faire un diagnostic de mon business",
        "Combien coûte la formation Meta Ads ?",
        "Je veux commander la formation",
        "J'ai un problème avec mon compte",
        "Comment créer du contenu viral sur Instagram ?",
        "Quelles sont les dernières tendances en IA ?",
    ]
    
    for msg in test_messages:
        intent, confidence, metadata = detector.detect(msg)
        print(f"\n📨 Message: {msg}")
        print(f"   ✅ Intent: {intent} (confiance: {confidence:.2%})")
        print(f"   📝 Description: {detector.get_intent_description(intent)}")
    
    # Stats
    print(f"\n📊 Statistiques:")
    stats = detector.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")


def test_context_builder():
    """Test du constructeur de contexte"""
    print("\n" + "=" * 60)
    print("TEST 2: ContextBuilder")
    print("=" * 60)
    
    db = SessionLocal()
    builder = ContextBuilder(db)
    
    # Test 1: Site vitrine
    context = builder.build_context(
        conversation_id="test_conv_001",
        site_id="eperformance_vitrine",
        user_id=None,
        message_history=[
            {"role": "user", "content": "Bonjour"},
            {"role": "assistant", "content": "Bonjour ! Comment puis-je vous aider ?"}
        ]
    )
    
    print(f"\n📊 Contexte chargé:")
    print(f"   Site: {context.get('site', {}).get('site_name', 'N/A')}")
    print(f"   Historique: {len(context.get('history', []))} messages")
    print(f"   Sources: {', '.join(context.get('sources', []))}")
    print(f"   Stats: {context.get('stats')}")
    
    # Format pour LLM
    llm_context = builder.format_context_for_llm(context)
    print(f"\n📝 Contexte formaté pour LLM:\n{llm_context}")
    
    db.close()


async def test_chatbot_service():
    """Test du service chatbot complet"""
    print("\n" + "=" * 60)
    print("TEST 3: ChatbotService (Pipeline complet)")
    print("=" * 60)
    
    db = SessionLocal()
    service = ChatbotService(db)
    
    # Test 1: Nouveau message
    print("\n🔄 Test message 1: Diagnostic request")
    result = await service.process_message(
        site_id="eperformance_vitrine",
        message="Bonjour, j'aimerais faire un diagnostic de mon business",
        visitor_info={
            'ip': '127.0.0.1',
            'user_agent': 'Test Bot',
            'referrer': 'https://google.com'
        }
    )
    
    print(f"   ✅ Conversation ID: {result['conversation_id']}")
    print(f"   🎯 Intent: {result['intent']} (confiance: {result['intent_confidence']:.2%})")
    print(f"   🤖 Agent: {result['agent_used']}")
    print(f"   💬 Réponse: {result['response'][:100]}...")
    print(f"   💡 Suggestions: {result['suggestions']}")
    print(f"   ⏱️  Temps: {result['processing_time_ms']}ms")
    print(f"   📚 Sources contexte: {result['context_sources']}")
    
    # Test 2: Message dans conversation existante
    print("\n🔄 Test message 2: Order intent (même conversation)")
    conv_id = result['conversation_id']
    result2 = await service.process_message(
        site_id="eperformance_vitrine",
        message="Ok je veux commander la formation Meta Ads",
        conversation_id=conv_id,
        message_history=[
            {"role": "user", "content": "Bonjour, j'aimerais faire un diagnostic"},
            {"role": "assistant", "content": result['response']}
        ]
    )
    
    print(f"   ✅ Conversation ID: {result2['conversation_id']}")
    print(f"   🎯 Intent: {result2['intent']} (confiance: {result2['intent_confidence']:.2%})")
    print(f"   💬 Réponse: {result2['response'][:100]}...")
    
    # Test 3: Récupérer l'historique
    print("\n📜 Récupération historique conversation:")
    history = service.get_conversation_history(conv_id)
    print(f"   Messages: {len(history['messages'])}")
    print(f"   Statut: {history['status']}")
    print(f"   Lead capturé: {history['lead_captured']}")
    
    db.close()


if __name__ == "__main__":
    print("\n🚀 TESTS CHATBOT PHASE 1-J2")
    print("=" * 60)
    
    # Test 1: IntentDetector
    test_intent_detector()
    
    # Test 2: ContextBuilder
    test_context_builder()
    
    # Test 3: ChatbotService
    asyncio.run(test_chatbot_service())
    
    print("\n" + "=" * 60)
    print("✅ TOUS LES TESTS TERMINÉS")
    print("=" * 60)

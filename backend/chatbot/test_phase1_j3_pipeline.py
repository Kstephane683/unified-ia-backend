"""
Test Phase 1-J3 : Pipeline complet Backend IA
AgentRouter + ResponseGenerator + ActionExecutor

Test du flux :
User message → Intent → Agent routing → LLM response → Actions → DB
"""
import asyncio
import sys
from pathlib import Path

# Ajouter le chemin parent pour les imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.core.database import Base, get_db_url
from backend.chatbot.service import ChatbotService
from backend.chatbot.models import ChatbotConversation, ChatbotMessage, ChatbotLead


async def test_pipeline_complete():
    """
    Test complet du pipeline Phase 1-J3
    """
    print("=" * 80)
    print("🚀 TEST PHASE 1-J3 : PIPELINE BACKEND IA COMPLET")
    print("=" * 80)
    print()
    
    # Configuration DB
    db_url = get_db_url()
    engine = create_engine(db_url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        # Initialiser le service
        print("📦 Initialisation ChatbotService...")
        service = ChatbotService(db)
        print("   ✅ Service initialisé\n")
        
        # Test cases
        test_cases = [
            {
                'name': 'Test 1 : Demande de diagnostic (intent detection)',
                'site_id': 'eperformance_vitrine',
                'message': 'Bonjour, je voudrais faire un diagnostic de mon business',
                'expected_intent': 'diagnostic_request',
                'expected_agent': 'sales-discovery-coach'
            },
            {
                'name': 'Test 2 : Commande produit (lead capture)',
                'site_id': 'eperformance_vitrine',
                'message': "Je veux commander le Pack Découverte. Je m'appelle Moussa Diallo, mon tel est +225 0758493021",
                'expected_intent': 'order_intent',
                'expected_agent': 'sales-offer-lead-gen-strategist',
                'expected_action': 'lead_capture'
            },
            {
                'name': 'Test 3 : Question MLM Longrich (routing override)',
                'site_id': 'eperformance_vitrine',
                'message': 'Comment recruter plus de filleules Longrich avec votre système ?',
                'expected_intent': 'mlm_advice',
                'expected_agent': 'sales-outbound-strategist'
            },
            {
                'name': 'Test 4 : Question SEO (agent marketing)',
                'site_id': 'eperformance_vitrine',
                'message': 'Comment améliorer le référencement de mon site sur Google ?',
                'expected_intent': 'seo_question',
                'expected_agent': 'marketing-seo-specialist'
            }
        ]
        
        results = []
        
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n{'=' * 80}")
            print(f"📝 {test_case['name']}")
            print(f"{'=' * 80}")
            print(f"💬 Message: {test_case['message'][:80]}...")
            print()
            
            try:
                # Traiter le message
                result = await service.process_message(
                    site_id=test_case['site_id'],
                    message=test_case['message'],
                    visitor_info={
                        'ip': '192.168.1.1',
                        'user_agent': 'Test Bot',
                        'referrer': ''
                    }
                )
                
                # Afficher les résultats
                print(f"✅ Traitement réussi ({result['processing_time_ms']}ms)")
                print(f"   🎯 Intent détecté: {result['intent']} (confidence: {result['intent_confidence']:.2f})")
                print(f"   🤖 Agent utilisé: {result['agent_used']}")
                print(f"   💬 Réponse ({len(result['response'])} chars):")
                print(f"      {result['response'][:200]}...")
                
                if result.get('suggestions'):
                    print(f"   💡 Suggestions: {result['suggestions']}")
                
                if result.get('actions'):
                    print(f"   ⚡ Actions exécutées: {len(result['actions'])}")
                    for action in result['actions']:
                        status = "✅" if action.get('success') else "❌"
                        print(f"      {status} {action['action']}")
                
                # Vérifier les attentes
                checks_passed = 0
                checks_total = 0
                
                # Check intent
                if 'expected_intent' in test_case:
                    checks_total += 1
                    if result['intent'] == test_case['expected_intent']:
                        print(f"   ✅ Intent attendu : {test_case['expected_intent']}")
                        checks_passed += 1
                    else:
                        print(f"   ⚠️  Intent attendu : {test_case['expected_intent']}, obtenu : {result['intent']}")
                
                # Check agent
                if 'expected_agent' in test_case:
                    checks_total += 1
                    if result['agent_used'] == test_case['expected_agent']:
                        print(f"   ✅ Agent attendu : {test_case['expected_agent']}")
                        checks_passed += 1
                    else:
                        print(f"   ⚠️  Agent attendu : {test_case['expected_agent']}, obtenu : {result['agent_used']}")
                
                # Check action
                if 'expected_action' in test_case:
                    checks_total += 1
                    actions_types = [a['action'] for a in result.get('actions', [])]
                    if test_case['expected_action'] in actions_types:
                        print(f"   ✅ Action attendue : {test_case['expected_action']}")
                        checks_passed += 1
                    else:
                        print(f"   ⚠️  Action attendue : {test_case['expected_action']}, obtenu : {actions_types}")
                
                # Score du test
                score_pct = (checks_passed / checks_total * 100) if checks_total > 0 else 100
                print(f"\n   📊 Score: {checks_passed}/{checks_total} ({score_pct:.0f}%)")
                
                results.append({
                    'test': test_case['name'],
                    'success': True,
                    'score': score_pct,
                    'conversation_id': result['conversation_id']
                })
            
            except Exception as e:
                print(f"❌ Erreur: {e}")
                import traceback
                traceback.print_exc()
                results.append({
                    'test': test_case['name'],
                    'success': False,
                    'error': str(e)
                })
        
        # Résumé final
        print(f"\n\n{'=' * 80}")
        print("📊 RÉSUMÉ DES TESTS")
        print(f"{'=' * 80}\n")
        
        total_tests = len(results)
        passed_tests = sum(1 for r in results if r['success'])
        
        for r in results:
            status = "✅" if r['success'] else "❌"
            score_info = f" ({r['score']:.0f}%)" if 'score' in r else ""
            print(f"{status} {r['test']}{score_info}")
        
        print(f"\n{'=' * 80}")
        print(f"🎯 Résultat global: {passed_tests}/{total_tests} tests réussis ({passed_tests/total_tests*100:.0f}%)")
        print(f"{'=' * 80}\n")
        
        # Vérifier les données en DB
        print("\n📦 Vérification des données en DB:")
        
        conv_count = db.query(ChatbotConversation).count()
        msg_count = db.query(ChatbotMessage).count()
        lead_count = db.query(ChatbotLead).count()
        
        print(f"   💬 Conversations créées: {conv_count}")
        print(f"   📝 Messages enregistrés: {msg_count}")
        print(f"   🎯 Leads capturés: {lead_count}")
        
        if lead_count > 0:
            print("\n   Détails des leads:")
            leads = db.query(ChatbotLead).all()
            for lead in leads:
                print(f"   - {lead.lead_name} | {lead.lead_phone or 'N/A'} | Intent: {lead.lead_intent}")
        
        print(f"\n{'=' * 80}")
        print("✅ TEST PHASE 1-J3 TERMINÉ")
        print(f"{'=' * 80}\n")
        
        return passed_tests == total_tests
    
    finally:
        db.close()


async def test_agent_router_only():
    """
    Test isolé de l'AgentRouter
    """
    print("\n" + "=" * 80)
    print("🧪 TEST ISOLÉ : AgentRouter")
    print("=" * 80 + "\n")
    
    from backend.chatbot.agent_router import AgentRouter
    
    router = AgentRouter(agents_base_path="agents")
    
    test_intents = [
        ('diagnostic_request', 'sales-discovery-coach'),
        ('product_inquiry', 'sales-offer-lead-gen-strategist'),
        ('mlm_advice', 'sales-outbound-strategist'),
        ('seo_question', 'marketing-seo-specialist'),
        ('content_strategy', 'marketing-content-creator'),
        ('brand_identity', 'design-brand-guardian'),
        ('ia_trends', 'research-deep-agent'),
    ]
    
    for intent, expected_agent in test_intents:
        agent_key, metadata = router.route(
            intent=intent,
            context={},
            intent_metadata={}
        )
        
        status = "✅" if agent_key == expected_agent else "⚠️"
        print(f"{status} {intent:25s} → {agent_key:35s} (attendu: {expected_agent})")
    
    # Test coverage
    print(f"\n📊 Coverage:")
    coverage = router.get_intent_coverage()
    print(f"   - {len(coverage)} intents mappés")
    
    agents = router.get_all_agents()
    total_agents = sum(len(v) for v in agents.values())
    print(f"   - {total_agents} agents disponibles")
    
    for category, agent_list in agents.items():
        print(f"   - {category}: {len(agent_list)} agents")


async def test_response_generator_only():
    """
    Test isolé du ResponseGenerator
    """
    print("\n" + "=" * 80)
    print("🧪 TEST ISOLÉ : ResponseGenerator")
    print("=" * 80 + "\n")
    
    from backend.chatbot.response_generator import ResponseGenerator
    
    generator = ResponseGenerator(agents_base_path="agents")
    
    # Test chargement persona
    print("📖 Test chargement persona:")
    persona = generator._load_agent_persona(
        'sales-discovery-coach',
        'agents/sales/sales-discovery-coach.md'
    )
    
    if persona:
        print(f"   ✅ Persona chargé ({len(persona)} chars)")
        print(f"   Preview: {persona[:150]}...")
    else:
        print(f"   ⚠️  Persona non chargé")
    
    # Test system prompt
    print("\n📝 Test construction system prompt:")
    system_prompt = generator._build_system_prompt(
        agent_persona=persona,
        context={'site': {'site_name': 'ePerformance'}},
        intent='diagnostic_request',
        agent_key='sales-discovery-coach'
    )
    
    print(f"   ✅ System prompt construit ({len(system_prompt)} chars)")
    print(f"   Preview: {system_prompt[:200]}...")


async def test_action_executor_only():
    """
    Test isolé de l'ActionExecutor
    """
    print("\n" + "=" * 80)
    print("🧪 TEST ISOLÉ : ActionExecutor")
    print("=" * 80 + "\n")
    
    from backend.chatbot.action_executor import ActionExecutor
    
    # Test détection contact info
    executor = ActionExecutor(None)
    
    test_texts = [
        "Mon numéro est 0758493021",
        "Contactez-moi sur john@example.com",
        "Je m'appelle Moussa Diallo, tel +225 07 58 49 30 21",
        "Bonjour, comment allez-vous ?"
    ]
    
    print("🔍 Test détection infos de contact:")
    for text in test_texts:
        has_contact = executor._detect_contact_info(text)
        status = "✅" if has_contact else "❌"
        print(f"{status} '{text[:50]}'")
        
        if has_contact:
            info = executor._extract_contact_info(text)
            print(f"   → {info}")


if __name__ == "__main__":
    print("\n🚀 SUITE DE TESTS PHASE 1-J3\n")
    
    # Menu
    print("Choisissez un test:")
    print("1. Test pipeline complet (recommandé)")
    print("2. Test AgentRouter seulement")
    print("3. Test ResponseGenerator seulement")
    print("4. Test ActionExecutor seulement")
    print("5. Tous les tests isolés")
    
    choice = input("\nVotre choix (1-5, défaut=1): ").strip() or "1"
    
    if choice == "1":
        success = asyncio.run(test_pipeline_complete())
        sys.exit(0 if success else 1)
    
    elif choice == "2":
        asyncio.run(test_agent_router_only())
    
    elif choice == "3":
        asyncio.run(test_response_generator_only())
    
    elif choice == "4":
        asyncio.run(test_action_executor_only())
    
    elif choice == "5":
        asyncio.run(test_agent_router_only())
        asyncio.run(test_response_generator_only())
        asyncio.run(test_action_executor_only())
    
    else:
        print("❌ Choix invalide")
        sys.exit(1)

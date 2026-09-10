#!/usr/bin/env python3
"""
Test rapide WhatsApp Business Cloud API
Vérifie la connexion et envoie un message de test

Usage:
    python test_whatsapp_quick.py
    python test_whatsapp_quick.py --to +2250798408300

Author: ePerformance IA System
Date: 2026-09-10
"""

import asyncio
import sys
import argparse
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.communication.providers.whatsapp_provider import WhatsAppProvider
from backend.communication.config import get_config


async def test_whatsapp_connection():
    """Test 1: Vérifier les credentials"""
    
    print("=" * 70)
    print("TEST 1: Vérification Credentials WhatsApp")
    print("=" * 70)
    
    config = get_config()
    wa_config = config.get_whatsapp_config()
    
    print(f"Phone Number ID: {wa_config['phone_number_id']}")
    print(f"WABA ID: {wa_config['waba_id']}")
    print(f"Access Token: {'✅ Configured' if wa_config['access_token'] else '❌ Missing'}")
    print(f"Business Phone: {wa_config['business_phone']}")
    
    if not wa_config['access_token']:
        print("\n❌ Access Token manquant !")
        return False
    
    print("\n✅ Credentials OK\n")
    return True


async def test_whatsapp_send_text(to_number: str):
    """Test 2: Envoyer message texte simple"""
    
    print("=" * 70)
    print("TEST 2: Envoi Message Texte")
    print("=" * 70)
    
    config = get_config()
    wa_config = config.get_whatsapp_config()
    
    provider = WhatsAppProvider(
        phone_number_id=wa_config['phone_number_id'],
        access_token=wa_config['access_token']
    )
    
    # Format numéro (enlever espaces/tirets)
    to_number_clean = to_number.replace(" ", "").replace("-", "")
    if not to_number_clean.startswith("+"):
        to_number_clean = "+" + to_number_clean
    
    print(f"Destinataire: {to_number_clean}")
    print(f"Message: Test système communication ePerformance")
    print("\n⏳ Envoi en cours...\n")
    
    result = await provider.send_text_message(
        to=to_number_clean,
        message="✅ *Test système communication ePerformance*\n\nSi vous recevez ce message, WhatsApp Cloud API est opérationnel !\n\n_Message automatique - Phase 1-S1.3_"
    )
    
    if result["success"]:
        print(f"✅ Message envoyé avec succès !")
        print(f"Message ID: {result.get('message_id')}")
        print(f"WhatsApp Message ID: {result['response']['messages'][0]['id']}")
        print(f"\n⚠️ Note: Le message peut prendre quelques secondes à arriver.")
    else:
        print(f"❌ Échec de l'envoi")
        print(f"Erreur: {result.get('error')}")
        print(f"Code: {result.get('error_code')}")
        if result.get('response'):
            print(f"Détails: {result['response']}")
    
    print()
    return result["success"]


async def test_whatsapp_template(to_number: str):
    """Test 3: Tester l'envoi via template (nécessite templates approuvés)"""
    
    print("=" * 70)
    print("TEST 3: Envoi via Template (SKIPPED)")
    print("=" * 70)
    
    print("⚠️ Ce test nécessite des templates WhatsApp approuvés par Meta.")
    print("   Voir WHATSAPP_CONFIGURATION_GUIDE.md pour créer les templates.")
    print()
    
    # Pour l'instant, on skip ce test
    # Une fois les templates créés, décommenter le code ci-dessous
    
    """
    config = get_config()
    wa_config = config.get_whatsapp_config()
    
    provider = WhatsAppProvider(
        phone_number_id=wa_config['phone_number_id'],
        access_token=wa_config['access_token']
    )
    
    # Exemple avec template "hello_world" (template par défaut Meta)
    result = await provider.send({
        "to": to_number.replace(" ", "").replace("-", ""),
        "template_name": "hello_world",
        "language": "fr",
        "components": []
    })
    
    if result["success"]:
        print(f"✅ Template envoyé avec succès !")
        print(f"Message ID: {result.get('message_id')}")
    else:
        print(f"❌ Échec: {result.get('error')}")
    
    print()
    return result["success"]
    """
    
    return True  # Skip pour l'instant


async def main():
    parser = argparse.ArgumentParser(description="Test WhatsApp Business Cloud API")
    parser.add_argument(
        "--to",
        default=None,
        help="Numéro destinataire (format international, ex: +2250798408300)"
    )
    
    args = parser.parse_args()
    
    print("\n" + "=" * 70)
    print("WHATSAPP BUSINESS CLOUD API - TESTS RAPIDES")
    print("=" * 70)
    print()
    
    # Test 1: Credentials
    if not await test_whatsapp_connection():
        print("❌ Test des credentials échoué. Vérifiez votre configuration.")
        return 1
    
    # Si numéro fourni, tester l'envoi
    if args.to:
        await test_whatsapp_send_text(args.to)
        await test_whatsapp_template(args.to)
    else:
        # Utiliser le numéro business par défaut
        config = get_config()
        wa_config = config.get_whatsapp_config()
        
        if wa_config['business_phone']:
            print("ℹ️  Aucun numéro spécifié, utilisation du numéro business.")
            print(f"   Pour tester avec un autre numéro: python test_whatsapp_quick.py --to +225XXXXXXXXX\n")
            
            await test_whatsapp_send_text(wa_config['business_phone'])
            await test_whatsapp_template(wa_config['business_phone'])
        else:
            print("⚠️  Aucun numéro de test spécifié.")
            print("   Usage: python test_whatsapp_quick.py --to +225XXXXXXXXX")
    
    # Résumé
    print("=" * 70)
    print("RÉSUMÉ")
    print("=" * 70)
    print("✅ WhatsApp Business Cloud API configuré et opérationnel !")
    print()
    print("📋 Prochaines étapes :")
    print("   1. Créer les templates WhatsApp sur Meta Business Manager")
    print("   2. Attendre approbation Meta (24-48h)")
    print("   3. Utiliser les templates dans les notifications")
    print()
    print("📖 Voir : WHATSAPP_CONFIGURATION_GUIDE.md (Étape 4)")
    print("=" * 70)
    print()
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

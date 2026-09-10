#!/usr/bin/env python3
"""
Test simple envoi WhatsApp - sans le long guide
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.communication.providers.whatsapp_provider import WhatsAppProvider
from backend.communication.config import get_config


async def main():
    print("=" * 70)
    print("TEST WHATSAPP - Envoi message texte")
    print("=" * 70)
    
    config = get_config()
    wa_config = config.get_whatsapp_config()
    
    print(f"\nPhone Number ID: {wa_config['phone_number_id']}")
    print(f"WABA ID: {wa_config['waba_id']}")
    print(f"To: {wa_config['business_phone']}")
    print(f"Access Token: {'✅ Configured' if wa_config['access_token'] else '❌ Missing'}\n")
    
    if not wa_config['access_token']:
        print("❌ Access Token manquant")
        return 1
    
    provider = WhatsAppProvider(
        phone_number_id=wa_config['phone_number_id'],
        access_token=wa_config['access_token']
    )
    
    print("⏳ Envoi en cours...\n")
    
    result = await provider.send_text_message(
        to=wa_config['business_phone'],
        message="✅ *Test système ePerformance*\n\nSi vous recevez ce message, WhatsApp Cloud API est opérationnel ! 🎉"
    )
    
    print("=" * 70)
    if result["success"]:
        print("✅ MESSAGE ENVOYÉ AVEC SUCCÈS !")
        print(f"\nMessage ID: {result.get('message_id')}")
        print(f"WhatsApp ID: {result['response']['messages'][0]['id']}")
        print(f"\n⚠️ Le message peut prendre quelques secondes à arriver.")
    else:
        print("❌ ÉCHEC DE L'ENVOI")
        print(f"\nErreur: {result.get('error')}")
        print(f"Code: {result.get('error_code')}")
        if result.get('response'):
            import json
            print(f"Détails:\n{json.dumps(result['response'], indent=2)}")
    
    print("=" * 70)
    
    return 0 if result["success"] else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

#!/usr/bin/env python3
"""
Quick Test Suite for Communication System
Tests all providers and core functionality

Usage:
    python test_communication_quick.py
    python test_communication_quick.py --provider email
    python test_communication_quick.py --provider whatsapp
    python test_communication_quick.py --provider telegram

Author: ePerformance IA System
Date: 2026-09-10
"""

import asyncio
import argparse
from datetime import datetime
from typing import Dict, Any


# ═══════════════════════════════════════════════════════════════════════
#  TEST HELPERS
# ═══════════════════════════════════════════════════════════════════════

class TestResult:
    """Test result container"""
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.error = None
        self.duration = 0.0
    
    def __str__(self):
        status = "✅ PASS" if self.passed else "❌ FAIL"
        duration = f"{self.duration:.2f}s"
        if self.error:
            return f"{status} {self.name} ({duration}) - {self.error}"
        return f"{status} {self.name} ({duration})"


class TestSuite:
    """Test suite runner"""
    def __init__(self):
        self.results = []
    
    async def run_test(self, name: str, test_func):
        """Run a single test"""
        result = TestResult(name)
        start = datetime.now()
        
        try:
            await test_func()
            result.passed = True
        except AssertionError as e:
            result.error = str(e)
        except Exception as e:
            result.error = f"{type(e).__name__}: {str(e)}"
        
        result.duration = (datetime.now() - start).total_seconds()
        self.results.append(result)
        
        print(result)
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)
        
        passed = sum(1 for r in self.results if r.passed)
        failed = len(self.results) - passed
        total_time = sum(r.duration for r in self.results)
        
        print(f"Total: {len(self.results)} tests")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Duration: {total_time:.2f}s")
        
        if failed > 0:
            print("\n❌ FAILED TESTS:")
            for r in self.results:
                if not r.passed:
                    print(f"  - {r.name}: {r.error}")
        
        print("=" * 70)
        
        return failed == 0


# ═══════════════════════════════════════════════════════════════════════
#  CONFIGURATION TESTS
# ═══════════════════════════════════════════════════════════════════════

async def test_config_loads():
    """Test: Configuration loads successfully"""
    from backend.communication.config import get_config
    
    config = get_config()
    assert config is not None, "Config should not be None"


async def test_config_has_providers():
    """Test: Configuration has provider configs"""
    from backend.communication.config import get_config
    
    config = get_config()
    
    email_config = config.get_email_config()
    assert "sender_email" in email_config, "Email config should have sender_email"
    
    whatsapp_config = config.get_whatsapp_config()
    assert "phone_number_id" in whatsapp_config, "WhatsApp config should have phone_number_id"
    
    telegram_config = config.get_telegram_config()
    assert "default_bot_token" in telegram_config, "Telegram config should have bot token"


# ═══════════════════════════════════════════════════════════════════════
#  EMAIL PROVIDER TESTS
# ═══════════════════════════════════════════════════════════════════════

async def test_email_provider_init():
    """Test: EmailProvider initializes"""
    from backend.communication.providers.email_provider import EmailProvider
    
    provider = EmailProvider(
        api_key="test_key",
        sender_email="test@eperformance.pro",
        sender_name="Test",
        admin_bcc_email="admin@eperformance.pro"
    )
    
    assert provider.api_key == "test_key"
    assert provider.sender_email == "test@eperformance.pro"


async def test_email_provider_build_payload():
    """Test: EmailProvider builds correct payload with BCC"""
    from backend.communication.providers.email_provider import EmailProvider
    
    provider = EmailProvider(
        api_key="test_key",
        sender_email="notifications@eperformance.pro",
        sender_name="ePerformance",
        admin_bcc_email="admin@eperformance.pro"
    )
    
    notification = {
        "recipient_email": "user@example.com",
        "recipient_name": "Test User",
        "subject": "Test Subject",
        "html_content": "<h1>Test</h1>"
    }
    
    payload = provider._build_payload(notification)
    
    # Check BCC is always present
    assert "bcc" in payload, "Payload must have BCC"
    assert len(payload["bcc"]) == 1, "BCC must have exactly 1 entry"
    assert payload["bcc"][0]["email"] == "admin@eperformance.pro", "BCC must be admin email"


# ═══════════════════════════════════════════════════════════════════════
#  WHATSAPP PROVIDER TESTS
# ═══════════════════════════════════════════════════════════════════════

async def test_whatsapp_provider_init():
    """Test: WhatsAppProvider initializes"""
    from backend.communication.providers.whatsapp_provider import WhatsAppProvider
    
    provider = WhatsAppProvider(
        phone_number_id="123456789",
        access_token="test_token"
    )
    
    assert provider.phone_number_id == "123456789"
    assert provider.access_token == "test_token"


async def test_whatsapp_provider_build_template_payload():
    """Test: WhatsAppProvider builds template payload correctly"""
    from backend.communication.providers.whatsapp_provider import WhatsAppProvider
    
    provider = WhatsAppProvider(
        phone_number_id="123456789",
        access_token="test_token"
    )
    
    notification = {
        "to": "+2250123456789",
        "template_name": "order_confirmation",
        "language": "fr",
        "components": [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": "CMD-001"},
                    {"type": "text", "text": "Fatou"},
                    {"type": "text", "text": "45000 FCFA"}
                ]
            }
        ]
    }
    
    payload = provider._build_template_payload(notification)
    
    assert payload["messaging_product"] == "whatsapp"
    assert payload["to"] == "+2250123456789"
    assert payload["type"] == "template"
    assert "template" in payload


# ═══════════════════════════════════════════════════════════════════════
#  TELEGRAM PROVIDER TESTS
# ═══════════════════════════════════════════════════════════════════════

async def test_telegram_provider_init():
    """Test: TelegramProvider initializes"""
    from backend.communication.providers.telegram_provider import TelegramProvider
    
    provider = TelegramProvider(default_bot_token="123:ABC")
    
    assert provider.default_bot_token == "123:ABC"


async def test_telegram_provider_build_keyboard():
    """Test: TelegramProvider builds inline keyboard"""
    from backend.communication.providers.telegram_provider import TelegramProvider
    
    buttons = [
        [{"text": "Button 1", "url": "https://example.com"}],
        [
            {"text": "Button 2", "callback_data": "action_2"},
            {"text": "Button 3", "callback_data": "action_3"}
        ]
    ]
    
    keyboard = TelegramProvider.build_inline_keyboard(buttons)
    
    assert "inline_keyboard" in keyboard
    assert len(keyboard["inline_keyboard"]) == 2
    assert len(keyboard["inline_keyboard"][0]) == 1
    assert len(keyboard["inline_keyboard"][1]) == 2


# ═══════════════════════════════════════════════════════════════════════
#  NOTIFICATION SERVICE TESTS
# ═══════════════════════════════════════════════════════════════════════

async def test_notification_service_idempotency_key():
    """Test: NotificationService generates consistent idempotency keys"""
    from backend.communication.notification_service import NotificationService
    
    # Mock DB session
    class MockDB:
        def query(self, *args):
            return self
        def filter_by(self, **kwargs):
            return self
        def first(self):
            return None
        def add(self, obj):
            pass
        def commit(self):
            pass
        def refresh(self, obj):
            pass
    
    service = NotificationService(
        db=MockDB(),
        email_config={"api_key": "test"},
        whatsapp_config={},
        telegram_config={}
    )
    
    key1 = service._generate_idempotency_key(
        user_id=1,
        template_code="test",
        variables={"a": "1", "b": "2"}
    )
    
    key2 = service._generate_idempotency_key(
        user_id=1,
        template_code="test",
        variables={"b": "2", "a": "1"}  # Different order
    )
    
    # Same input should produce same key regardless of dict order
    assert key1 == key2, "Idempotency keys should be consistent"


async def test_notification_service_template_rendering():
    """Test: NotificationService renders templates correctly"""
    from backend.communication.notification_service import NotificationService
    
    class MockDB:
        pass
    
    service = NotificationService(
        db=MockDB(),
        email_config={},
        whatsapp_config={},
        telegram_config={}
    )
    
    template = "Hello {{name}}, your order {{order_id}} is ready!"
    variables = {"name": "Fatou", "order_id": "CMD-001"}
    
    result = service._render_template(template, variables)
    
    assert result == "Hello Fatou, your order CMD-001 is ready!"


# ═══════════════════════════════════════════════════════════════════════
#  INTEGRATION TESTS (requires real API keys)
# ═══════════════════════════════════════════════════════════════════════

async def test_telegram_send_real():
    """Test: Send real Telegram message (REQUIRES VALID TOKEN)"""
    from backend.communication.providers.telegram_provider import TelegramProvider
    from backend.communication.config import get_config
    
    config = get_config()
    telegram_config = config.get_telegram_config()
    
    if not telegram_config.get("default_bot_token"):
        raise AssertionError("⚠️ SKIP: Telegram token not configured")
    
    if not telegram_config.get("admin_chat_id"):
        raise AssertionError("⚠️ SKIP: Telegram admin chat_id not configured")
    
    provider = TelegramProvider(
        default_bot_token=telegram_config["default_bot_token"]
    )
    
    result = await provider.send({
        "chat_id": telegram_config["admin_chat_id"],
        "message": f"<b>✅ Test système communication</b>\n\nTimestamp: {datetime.now().isoformat()}",
        "parse_mode": "HTML"
    })
    
    assert result["success"] == True, f"Telegram send failed: {result.get('error')}"


# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

async def run_all_tests(provider_filter: str = None):
    """Run all tests"""
    
    suite = TestSuite()
    
    print("=" * 70)
    print("COMMUNICATION SYSTEM - QUICK TESTS")
    print("=" * 70)
    print()
    
    # Configuration tests
    if not provider_filter or provider_filter == "config":
        print("📋 CONFIGURATION TESTS")
        print("-" * 70)
        await suite.run_test("Config loads", test_config_loads)
        await suite.run_test("Config has providers", test_config_has_providers)
        print()
    
    # Email tests
    if not provider_filter or provider_filter == "email":
        print("📧 EMAIL PROVIDER TESTS")
        print("-" * 70)
        await suite.run_test("Email provider init", test_email_provider_init)
        await suite.run_test("Email provider BCC", test_email_provider_build_payload)
        print()
    
    # WhatsApp tests
    if not provider_filter or provider_filter == "whatsapp":
        print("📱 WHATSAPP PROVIDER TESTS")
        print("-" * 70)
        await suite.run_test("WhatsApp provider init", test_whatsapp_provider_init)
        await suite.run_test("WhatsApp template payload", test_whatsapp_provider_build_template_payload)
        print()
    
    # Telegram tests
    if not provider_filter or provider_filter == "telegram":
        print("✈️ TELEGRAM PROVIDER TESTS")
        print("-" * 70)
        await suite.run_test("Telegram provider init", test_telegram_provider_init)
        await suite.run_test("Telegram inline keyboard", test_telegram_provider_build_keyboard)
        print()
    
    # Service tests
    if not provider_filter or provider_filter == "service":
        print("🔧 NOTIFICATION SERVICE TESTS")
        print("-" * 70)
        await suite.run_test("Service idempotency key", test_notification_service_idempotency_key)
        await suite.run_test("Service template rendering", test_notification_service_template_rendering)
        print()
    
    # Integration tests
    if not provider_filter or provider_filter == "integration":
        print("🚀 INTEGRATION TESTS (Real API calls)")
        print("-" * 70)
        await suite.run_test("Telegram send (real)", test_telegram_send_real)
        print()
    
    # Summary
    success = suite.print_summary()
    
    return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(description="Communication System Quick Tests")
    parser.add_argument(
        "--provider",
        choices=["config", "email", "whatsapp", "telegram", "service", "integration"],
        help="Run tests for specific provider only"
    )
    
    args = parser.parse_args()
    
    exit_code = asyncio.run(run_all_tests(provider_filter=args.provider))
    exit(exit_code)


if __name__ == "__main__":
    main()

"""
Communication System Configuration Loader
Centralized configuration for notification system with environment variables support

Author: ePerformance IA System
Date: 2026-09-10
"""

import os
from typing import Dict, Any, Optional
from pathlib import Path
import json


class CommunicationConfig:
    """
    Configuration loader for communication system
    
    Priority (highest to lowest):
    1. Environment variables
    2. .env file
    3. config_reseaux.json (legacy toolkit)
    4. Default values
    """
    
    def __init__(self, env_file: Optional[str] = None):
        """
        Initialize configuration
        
        Args:
            env_file: Path to .env file (optional, auto-detected if None)
        """
        self._config = {}
        self._load_env_file(env_file)
        self._load_legacy_config()
        self._load_environment()
    
    def _load_env_file(self, env_file: Optional[str] = None):
        """Load .env file if exists"""
        
        if env_file:
            env_path = Path(env_file)
        else:
            # Auto-detect .env file
            candidates = [
                Path.cwd() / ".env",
                Path(__file__).parent.parent.parent / ".env",
                Path("/home/ballo/OX6A/.env"),
                Path("/home/ballo/OX6A/unified_ia_system/.env")
            ]
            env_path = next((p for p in candidates if p.exists()), None)
        
        if env_path and env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        # Remove quotes
                        value = value.strip('"').strip("'")
                        self._config[key] = value
    
    def _load_legacy_config(self):
        """Load legacy config_reseaux.json from toolkit"""
        
        legacy_path = Path("/home/ballo/OX6A/toolkit_eperformance/api/config_reseaux.json")
        
        if not legacy_path.exists():
            # Try example file
            legacy_path = Path("/home/ballo/OX6A/toolkit_eperformance/api/config_reseaux.example.json")
        
        if legacy_path.exists():
            try:
                with open(legacy_path) as f:
                    data = json.load(f)
                
                # Extract WhatsApp
                if "platforms" in data and "whatsapp" in data["platforms"]:
                    wa = data["platforms"]["whatsapp"]
                    if not self._config.get("WHATSAPP_PHONE_NUMBER_ID"):
                        self._config["WHATSAPP_PHONE_NUMBER_ID"] = wa.get("phone_id", "")
                    if not self._config.get("WHATSAPP_ACCESS_TOKEN"):
                        self._config["WHATSAPP_ACCESS_TOKEN"] = wa.get("access_token", "")
                
                # Extract Telegram
                if "telegram" in data:
                    tg = data["telegram"]
                    if not self._config.get("TELEGRAM_BOT_TOKEN"):
                        self._config["TELEGRAM_BOT_TOKEN"] = tg.get("bot_token", "")
                    if not self._config.get("TELEGRAM_ADMIN_CHAT_ID"):
                        self._config["TELEGRAM_ADMIN_CHAT_ID"] = tg.get("chat_id", "")
            
            except Exception:
                pass  # Ignore errors in legacy config
    
    def _load_environment(self):
        """Load from environment variables (highest priority)"""
        
        env_vars = [
            # Database
            "DATABASE_URL",
            "REDIS_URL",
            
            # Brevo (Email)
            "BREVO_API_KEY",
            "BREVO_SENDER_EMAIL",
            "BREVO_SENDER_NAME",
            "BREVO_ADMIN_BCC",
            
            # WhatsApp
            "WHATSAPP_PHONE_NUMBER_ID",
            "WHATSAPP_ACCESS_TOKEN",
            "WHATSAPP_WABA_ID",
            "WHATSAPP_BUSINESS_PHONE",
            "WHATSAPP_WEBHOOK_VERIFY_TOKEN",
            
            # Telegram
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_ADMIN_CHAT_ID"
        ]
        
        for var in env_vars:
            value = os.getenv(var)
            if value:
                self._config[var] = value
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        return self._config.get(key, default)
    
    def get_email_config(self) -> Dict[str, Any]:
        """Get Email provider configuration"""
        
        return {
            "api_key": self.get("BREVO_API_KEY", ""),
            "sender_email": self.get("BREVO_SENDER_EMAIL", "notifications@eperformance.pro"),
            "sender_name": self.get("BREVO_SENDER_NAME", "ePerformance"),
            "admin_bcc_email": self.get("BREVO_ADMIN_BCC", "admin@eperformance.pro")
        }
    
    def get_whatsapp_config(self) -> Dict[str, Any]:
        """Get WhatsApp provider configuration"""
        
        return {
            "phone_number_id": self.get("WHATSAPP_PHONE_NUMBER_ID", "1079505398586828"),
            "access_token": self.get("WHATSAPP_ACCESS_TOKEN", ""),
            "waba_id": self.get("WHATSAPP_WABA_ID", ""),
            "business_phone": self.get("WHATSAPP_BUSINESS_PHONE", "")
        }
    
    def get_telegram_config(self) -> Dict[str, Any]:
        """Get Telegram provider configuration"""
        
        return {
            "default_bot_token": self.get("TELEGRAM_BOT_TOKEN", ""),
            "admin_chat_id": self.get("TELEGRAM_ADMIN_CHAT_ID", "")
        }
    
    def get_database_url(self) -> str:
        """Get database connection URL"""
        
        return self.get("DATABASE_URL", "mysql+pymysql://root@localhost/unified_ia_dev")
    
    def get_redis_url(self) -> str:
        """Get Redis connection URL"""
        
        return self.get("REDIS_URL", "redis://localhost:6379/0")
    
    def validate(self) -> Dict[str, Any]:
        """
        Validate configuration
        
        Returns:
            Dict with validation results
        """
        
        results = {
            "valid": True,
            "warnings": [],
            "errors": []
        }
        
        # Check critical configurations
        
        # Email
        if not self.get("BREVO_API_KEY"):
            results["warnings"].append("BREVO_API_KEY not configured (email disabled)")
        
        # WhatsApp
        if not self.get("WHATSAPP_ACCESS_TOKEN"):
            results["warnings"].append("WHATSAPP_ACCESS_TOKEN not configured (WhatsApp disabled)")
        
        if self.get("WHATSAPP_PHONE_NUMBER_ID") and not self.get("WHATSAPP_ACCESS_TOKEN"):
            results["warnings"].append("WhatsApp Phone ID set but no Access Token")
        
        # Telegram (always valid with default token)
        if not self.get("TELEGRAM_BOT_TOKEN"):
            results["warnings"].append("TELEGRAM_BOT_TOKEN not configured (using default)")
        
        # Database
        if not self.get("DATABASE_URL"):
            results["errors"].append("DATABASE_URL not configured (CRITICAL)")
            results["valid"] = False
        
        return results
    
    def print_status(self):
        """Print configuration status"""
        
        print("=" * 70)
        print("COMMUNICATION SYSTEM CONFIGURATION")
        print("=" * 70)
        
        # Email
        print("\n📧 EMAIL (Brevo)")
        print(f"  API Key: {'✅ Configured' if self.get('BREVO_API_KEY') else '❌ Missing'}")
        print(f"  Sender: {self.get('BREVO_SENDER_EMAIL', 'NOT SET')}")
        print(f"  Admin BCC: {self.get('BREVO_ADMIN_BCC', 'NOT SET')}")
        
        # WhatsApp
        print("\n📱 WHATSAPP (Cloud API)")
        print(f"  Phone ID: {'✅ ' + self.get('WHATSAPP_PHONE_NUMBER_ID', 'NOT SET')}")
        print(f"  Access Token: {'✅ Configured' if self.get('WHATSAPP_ACCESS_TOKEN') else '❌ Missing'}")
        print(f"  WABA ID: {self.get('WHATSAPP_WABA_ID') or '❌ Missing'}")
        
        # Telegram
        print("\n✈️ TELEGRAM (Bot API)")
        print(f"  Bot Token: {'✅ Configured' if self.get('TELEGRAM_BOT_TOKEN') else '❌ Missing'}")
        print(f"  Admin Chat: {self.get('TELEGRAM_ADMIN_CHAT_ID', 'NOT SET')}")
        
        # Database
        print("\n🗄️  DATABASE")
        db_url = self.get("DATABASE_URL", "NOT SET")
        # Mask password
        if "@" in db_url:
            parts = db_url.split("@")
            user_pass = parts[0].split("://")[1]
            if ":" in user_pass:
                user = user_pass.split(":")[0]
                db_url = db_url.replace(user_pass, f"{user}:***")
        print(f"  URL: {db_url}")
        
        # Redis
        print("\n🔴 REDIS")
        print(f"  URL: {self.get('REDIS_URL', 'NOT SET')}")
        
        # Validation
        print("\n" + "=" * 70)
        validation = self.validate()
        
        if validation["valid"]:
            print("✅ Configuration valid")
        else:
            print("❌ Configuration invalid")
        
        if validation["warnings"]:
            print("\n⚠️  WARNINGS:")
            for warning in validation["warnings"]:
                print(f"  - {warning}")
        
        if validation["errors"]:
            print("\n❌ ERRORS:")
            for error in validation["errors"]:
                print(f"  - {error}")
        
        print("=" * 70)


# Global instance
_config_instance: Optional[CommunicationConfig] = None


def get_config(reload: bool = False) -> CommunicationConfig:
    """
    Get global configuration instance (singleton)
    
    Args:
        reload: Force reload configuration
    
    Returns:
        CommunicationConfig instance
    """
    global _config_instance
    
    if _config_instance is None or reload:
        _config_instance = CommunicationConfig()
    
    return _config_instance


if __name__ == "__main__":
    # CLI tool to check configuration
    import argparse
    
    parser = argparse.ArgumentParser(description="Communication System Configuration Tool")
    parser.add_argument("--validate", action="store_true", help="Validate configuration")
    parser.add_argument("--status", action="store_true", help="Print configuration status")
    parser.add_argument("--env-file", help="Path to .env file")
    
    args = parser.parse_args()
    
    config = CommunicationConfig(env_file=args.env_file)
    
    if args.status or not (args.validate):
        config.print_status()
    
    if args.validate:
        validation = config.validate()
        
        if validation["valid"]:
            print("\n✅ Configuration is valid")
            exit(0)
        else:
            print("\n❌ Configuration is invalid")
            for error in validation["errors"]:
                print(f"  ERROR: {error}")
            exit(1)

# Backend Chatbot IA - ePerformance

Backend FastAPI avec chatbot IA alimenté par DeepSeek et Claude.

## 🚀 Déploiement Railway

### Variables d'environnement requises

```bash
DATABASE_URL=postgresql://... (Railway génère automatiquement)
DEEPSEEK_API_KEY=sk-xxxxx
CLAUDE_GATEWAY_URL=https://aiapiflow.com/v1/chat/completions
CLAUDE_GATEWAY_KEY=sk-xxxxx
ENVIRONMENT=production
DEBUG=false
CORS_ORIGINS=https://eperformance.pro,https://www.eperformance.pro
PORT=8000
```

### Endpoints

- `GET /health` - Santé de l'API
- `GET /docs` - Documentation Swagger
- `POST /api/chatbot/message` - Envoyer message au chatbot
- `GET /api/chatbot/conversation/{id}` - Historique conversation

## 📦 Architecture

- **FastAPI** - Framework web
- **SQLAlchemy** - ORM base de données
- **PostgreSQL** - Base de données
- **DeepSeek/Claude** - Modèles LLM
- **4 agents IA** - Marketing, Vente, Technique, Support

## 🗄️ Migrations

Après déploiement, importer les migrations SQL dans PostgreSQL :

1. `migrations/001_create_saas_tables.sql`
2. `migrations/002_add_subscriptions_products.sql`
3. `migrations/003_add_communication_system.sql`
4. `migrations/004_add_chatbot_system.sql`

## 🔧 Développement local

```bash
# Créer environnement virtuel
python -m venv venv
source venv/bin/activate

# Installer dépendances
pip install -r requirements.txt

# Lancer serveur
uvicorn backend.api.app:app --reload
```

## 📝 License

Propriétaire - ePerformance

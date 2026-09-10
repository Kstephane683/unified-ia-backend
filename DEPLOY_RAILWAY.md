═══════════════════════════════════════════════════════════════
  🚂 DÉPLOIEMENT RAILWAY - ÉTAPES SUIVANTES
═══════════════════════════════════════════════════════════════

✅ PRÉPARATION TERMINÉE !

Le backend est prêt dans : /home/ballo/OX6A/unified-ia-backend/

📦 Fichiers créés :
   ✅ Procfile (commande démarrage)
   ✅ runtime.txt (Python 3.11)
   ✅ railway.json (config Railway)
   ✅ README.md (documentation)
   ✅ .gitignore
   ✅ Git initialisé (commit initial fait)
   ✅ 82 fichiers backend copiés
   ✅ 5 migrations SQL

═══════════════════════════════════════════════════════════════

🚀 DÉPLOIEMENT RAILWAY (5 ÉTAPES - 10 MINUTES)

┌─────────────────────────────────────────────────────────────┐
│ ÉTAPE 1 : CRÉER REPO GITHUB (2 min)                        │
└─────────────────────────────────────────────────────────────┘

1. Aller sur : https://github.com/new

2. Créer nouveau repo :
   - Repository name : unified-ia-backend
   - Description : Backend FastAPI Chatbot IA - ePerformance
   - ⚠️ Laisser VIDE (pas de README, pas de .gitignore)
   - Private ou Public : votre choix
   - Cliquer "Create repository"

3. Copier l'URL du repo (exemple) :
   https://github.com/Kstephane683/unified-ia-backend.git

4. Dans votre terminal local :

cd /home/ballo/OX6A/unified-ia-backend
git remote add origin https://github.com/Kstephane683/unified-ia-backend.git
git push -u origin main

(Entrer username/password GitHub si demandé)

┌─────────────────────────────────────────────────────────────┐
│ ÉTAPE 2 : CRÉER COMPTE RAILWAY (1 min)                     │
└─────────────────────────────────────────────────────────────┘

1. Aller sur : https://railway.app

2. Cliquer "Start a New Project" ou "Sign Up"

3. Choisir "Sign up with GitHub"

4. Autoriser Railway à accéder à vos repos GitHub

5. Vous êtes sur le Dashboard Railway ✅

┌─────────────────────────────────────────────────────────────┐
│ ÉTAPE 3 : DÉPLOYER DEPUIS GITHUB (2 min)                   │
└─────────────────────────────────────────────────────────────┘

1. Dashboard Railway → "New Project"

2. Sélectionner "Deploy from GitHub repo"

3. Choisir le repo : unified-ia-backend

4. Railway détecte automatiquement :
   ✅ Python (runtime.txt)
   ✅ Procfile
   ✅ requirements.txt

5. Cliquer "Deploy"

6. Railway commence le build (2-3 minutes)
   - Installing dependencies...
   - Building...
   - Deploying...

7. Une fois terminé, vous voyez "Active" en vert ✅

┌─────────────────────────────────────────────────────────────┐
│ ÉTAPE 4 : AJOUTER POSTGRESQL (1 min)                       │
└─────────────────────────────────────────────────────────────┘

1. Dans le même projet Railway

2. Cliquer "+ New" → "Database" → "Add PostgreSQL"

3. Railway crée la base automatiquement (30s)

4. PostgreSQL apparaît dans le projet

5. DATABASE_URL est automatiquement lié au service backend ✅

┌─────────────────────────────────────────────────────────────┐
│ ÉTAPE 5 : CONFIGURER VARIABLES (2 min)                     │
└─────────────────────────────────────────────────────────────┘

1. Cliquer sur votre service backend (unified-ia-backend)

2. Onglet "Variables"

3. Ajouter les variables suivantes :

   Nom : DEEPSEEK_API_KEY
   Valeur : sk-xxxxx (votre clé DeepSeek)

   Nom : CLAUDE_GATEWAY_URL
   Valeur : https://aiapiflow.com/v1/chat/completions

   Nom : CLAUDE_GATEWAY_KEY
   Valeur : sk-xxxxx (votre clé Claude gateway)

   Nom : ENVIRONMENT
   Valeur : production

   Nom : DEBUG
   Valeur : false

   Nom : CORS_ORIGINS
   Valeur : https://eperformance.pro,https://www.eperformance.pro

   Nom : PORT
   Valeur : 8000

4. Railway redémarre automatiquement (30s)

┌─────────────────────────────────────────────────────────────┐
│ ÉTAPE 6 : OBTENIR L'URL PUBLIQUE (30s)                     │
└─────────────────────────────────────────────────────────────┘

1. Dans votre service backend

2. Onglet "Settings"

3. Section "Networking" → "Generate Domain"

4. Railway génère une URL type :
   https://unified-ia-backend-production.up.railway.app

5. Copier cette URL ✅

┌─────────────────────────────────────────────────────────────┐
│ ÉTAPE 7 : IMPORTER MIGRATIONS SQL (3 min)                  │
└─────────────────────────────────────────────────────────────┘

1. Cliquer sur PostgreSQL dans le projet

2. Onglet "Data" → "Connect"

3. Copier "Postgres Connection URL" (commence par postgresql://)

4. Option A : Utiliser TablePlus / pgAdmin
   - Installer TablePlus : https://tableplus.com
   - New Connection → PostgreSQL
   - Coller la connection URL
   - Importer les fichiers SQL dans l'ordre :
     1. migrations/001_create_saas_tables.sql
     2. migrations/002_add_subscriptions_products.sql
     3. migrations/003_add_communication_system.sql
     4. migrations/004_add_chatbot_system.sql

5. Option B : Via terminal (psql)

   cd /home/ballo/OX6A/unified-ia-backend
   
   export DATABASE_URL="postgresql://..." (coller URL Railway)
   
   psql $DATABASE_URL -f migrations/001_create_saas_tables.sql
   psql $DATABASE_URL -f migrations/002_add_subscriptions_products.sql
   psql $DATABASE_URL -f migrations/003_add_communication_system.sql
   psql $DATABASE_URL -f migrations/004_add_chatbot_system.sql

┌─────────────────────────────────────────────────────────────┐
│ ÉTAPE 8 : TESTER L'API (1 min)                             │
└─────────────────────────────────────────────────────────────┘

1. Ouvrir dans navigateur :
   https://votre-url.up.railway.app/health

   Réponse attendue :
   {
     "status": "healthy",
     "database": "ok",
     "environment": "production"
   }

2. Tester documentation :
   https://votre-url.up.railway.app/docs

3. Tester chatbot :
   
   curl -X POST https://votre-url.up.railway.app/api/chatbot/message \
     -H "Content-Type: application/json" \
     -d '{
       "messages": [{"role": "user", "text": "Bonjour"}],
       "site_id": "eperformance_vitrine"
     }'

┌─────────────────────────────────────────────────────────────┐
│ ÉTAPE 9 : METTRE À JOUR LE WIDGET (2 min)                  │
└─────────────────────────────────────────────────────────────┘

1. Modifier le widget frontend :

   cd /home/ballo/OX6A/site-eperformance/chatbot-widget
   nano src/main.jsx

2. Remplacer l'URL Railway :

   const defaultApiUrl = isLocalhost 
     ? 'http://localhost:8000'
     : 'https://unified-ia-backend-production.up.railway.app';

   (Remplacer par VOTRE URL Railway générée)

3. Rebuild le widget :

   npm run build
   cp dist/chatbot-widget.iife.js ../
   cp dist/chatbot-widget.css ../

4. Commit et push :

   cd /home/ballo/OX6A/site-eperformance
   git add chatbot-widget.iife.js chatbot-widget.css chatbot-widget/src/main.jsx
   git commit -m "fix: Pointer widget vers Railway backend API"
   git push origin main

5. Attendre rebuild GitHub Pages (2-5 min)

6. Tester sur : https://eperformance.pro

═══════════════════════════════════════════════════════════════

✅ RÉSULTAT FINAL

Frontend : https://eperformance.pro
Backend  : https://votre-url.up.railway.app
Chatbot  : Opérationnel avec LLM réels (DeepSeek + Claude)

═══════════════════════════════════════════════════════════════

📊 MONITORING RAILWAY

• Dashboard → Logs (temps réel)
• Metrics (CPU, RAM, requêtes)
• 500h/mois gratuit (renouvelé chaque mois)
• Auto-deploy depuis GitHub (push = redéploiement auto)

═══════════════════════════════════════════════════════════════

🆘 TROUBLESHOOTING

❌ Build failed
   → Vérifier logs Railway
   → requirements.txt correct ?
   → Python 3.11 spécifié dans runtime.txt ?

❌ Database connection failed
   → PostgreSQL bien ajouté au projet ?
   → DATABASE_URL automatiquement lié ?

❌ CORS errors
   → Vérifier CORS_ORIGINS dans variables
   → Inclure https://eperformance.pro

❌ LLM timeout
   → Vérifier DEEPSEEK_API_KEY
   → Tester clés API manuellement

═══════════════════════════════════════════════════════════════

⏱️ TEMPS TOTAL : 10-15 MINUTES

✅ Repo GitHub : 2 min
✅ Compte Railway : 1 min
✅ Deploy : 2 min
✅ PostgreSQL : 1 min
✅ Variables : 2 min
✅ URL : 30s
✅ Migrations : 3 min
✅ Tests : 1 min
✅ Widget : 2 min

═══════════════════════════════════════════════════════════════

🎉 BONNE CHANCE !

Tout est prêt. Suivez les 9 étapes ci-dessus et votre chatbot
sera opérationnel en production ! 🚀

═══════════════════════════════════════════════════════════════

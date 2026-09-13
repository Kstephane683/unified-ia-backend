#!/bin/bash
# Script pour importer les migrations PostgreSQL sur Railway
# Usage: ./IMPORT_MIGRATIONS_RAILWAY.sh

cd /home/ballo/OX6A/unified-ia-backend

echo "🚂 Import des migrations PostgreSQL sur Railway..."
echo ""

# Vérifier que Railway CLI est connecté
if ! railway status &>/dev/null; then
    echo "❌ Railway CLI non connecté. Exécutez d'abord:"
    echo "   cd /home/ballo/OX6A/unified-ia-backend"
    echo "   railway link"
    exit 1
fi

echo "✅ Railway CLI connecté"
echo ""
echo "📦 Migrations à importer:"
echo "   1️⃣  001_create_saas_tables.sql"
echo "   2️⃣  002_add_subscriptions_products.sql"
echo "   3️⃣  003_add_communication_system.sql"
echo "   4️⃣  004_add_chatbot_system.sql"
echo ""
echo "⏳ Démarrage de l'import..."
echo ""

# Lancer railway connect postgres avec les migrations
railway connect postgres << 'EOF'
\i /home/ballo/OX6A/unified-ia-backend/migrations/postgresql/001_create_saas_tables.sql
\i /home/ballo/OX6A/unified-ia-backend/migrations/postgresql/002_add_subscriptions_products.sql
\i /home/ballo/OX6A/unified-ia-backend/migrations/postgresql/003_add_communication_system.sql
\i /home/ballo/OX6A/unified-ia-backend/migrations/postgresql/004_add_chatbot_system.sql
\dt
\q
EOF

echo ""
echo "✅ Migrations importées avec succès !"
echo ""
echo "🔍 Vérification des tables créées:"
railway connect postgres -c "\dt"
echo ""
echo "✅ Import terminé !"

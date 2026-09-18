# Configuration Variables Railway

## Via Dashboard (Recommandé - 2 minutes)

1. **Aller sur Railway Dashboard:**
   https://railway.app/project/e4f6d758-4402-49ac-ad4b-dce1b0abb0c0

2. **Cliquer sur service `web`**

3. **Onglet `Variables`**

4. **Lier DATABASE_URL depuis Postgres:**
   - Cliquer `+ New Variable`
   - Sélectionner `Add Reference`
   - Service: `Postgres`
   - Variable: `DATABASE_URL`
   - Confirmer

5. **Ajouter variables API (cliquer `+ New Variable` pour chaque):**

```
DEEPSEEK_API_KEY
Valeur: <a renseigner dans Railway, jamais dans ce fichier>

CLAUDE_GATEWAY_URL
Valeur: https://aiapiflow.com/v1/chat/completions

CLAUDE_GATEWAY_KEY
Valeur: <a renseigner dans Railway, jamais dans ce fichier>

CORS_ORIGINS
Valeur: https://eperformance.pro,https://www.eperformance.pro

ENVIRONMENT
Valeur: production

DEBUG
Valeur: false
```

6. **Railway redémarre automatiquement** (30-60 secondes)

7. **Tester l'API:**
```bash
curl https://web-production-4ab53.up.railway.app/health
```

Réponse attendue:
```json
{"status":"healthy","database":"ok"}
```

---

## Vérification

Après configuration, le service `web` devrait passer de ● Crashed à ● Online.

```bash
railway status
```

---

## Troubleshooting

**Service toujours Crashed ?**
```bash
railway logs --service web
```

**DATABASE_URL non disponible ?**
Vérifier que Postgres et web sont dans le même environnement (production).

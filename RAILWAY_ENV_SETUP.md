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

---

## Fondations d'extensibilité (19/09) — variables à poser SEULEMENT à l'activation

Toutes les variables ci-dessous sont **vides/absentes par défaut** : le comportement sans elles est un état explicite (`non configuré` / `désactivé`), jamais une erreur, jamais un appel réseau. Ne rien poser tant que le canal/fonction n'est pas activé — et ne JAMAIS écrire une valeur réelle dans un fichier versionné (dépôt public, `scripts/verifier-secrets.py` au pre-push). Détail : `docs/refonte-app-mia/EXTENSIBILITE.md §6`.

| Fonction | Variables (poser dans Railway → service `web` → Variables) |
|---|---|
| **WhatsApp (Meta Cloud API)** | `WHATSAPP_ENABLED=true` · `WHATSAPP_ACCESS_TOKEN` · `WHATSAPP_PHONE_NUMBER_ID` · `WHATSAPP_WABA_ID` · `WHATSAPP_NOTIF_DESTINATAIRE` (destinataire par défaut des notifications) |
| **Webhooks WhatsApp** | `WHATSAPP_WEBHOOK_VERIFY_TOKEN` (vérification GET `hub.challenge`) · `WHATSAPP_APP_SECRET` (validation `X-Hub-Signature-256`) |
| **RCS** | `RCS_ENABLED=true` · `RCS_AGENT_ID` · `RCS_API_URL` · `RCS_API_KEY` · `RCS_FALLBACK_SMS=true` (fallback SMS DÉCLARATIF — la bascule d'envoi reste à implémenter avec le fournisseur final) |
| **Abonnement Jeko** | `JEKO_API_URL` (sandbox puis production) · `JEKO_API_KEY` · `JEKO_WEBHOOK_SECRET` (HMAC — sans lui, `POST /api/webhooks/jeko` refuse tout : 400) |

À l'ajout d'une variable, Railway redémarre le service (30-60 s). Vérification après activation :

```bash
curl https://web-production-4ab53.up.railway.app/health
curl -H "Authorization: Bearer <jeton>" https://web-production-4ab53.up.railway.app/api/client/v1/me
```

`/me` reflète le `plan` et les fonctionnalités `actives`/`verrouillees` de l'activation.

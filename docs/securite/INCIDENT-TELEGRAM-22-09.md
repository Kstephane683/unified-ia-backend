# 🔴 INCIDENT TELEGRAM — 22/09/2026 · compromission du bot + rotation

> Document de référence de l'incident. Toute valeur de secret est désignée par
> son nom de variable et son emplacement, jamais reproduite (règle du 18/09 22:15).
> Les nouvelles valeurs vivent dans des fichiers locaux 0600 hors dépôt :
> `/home/ballo/EP-PROD-TELEGRAM-NOUVEAU.txt` et `/home/ballo/EP-PROD-DEEPSEEK-NOUVEAU.txt`.

## 1. Ce qui s'est passé

Le **22/09**, le propriétaire constate une compromission du bot Telegram et
décide : nouveau bot, rotation du token, rotation de la clé DeepSeek dans la
foulée. Le **24/09**, il transmet hors journal le token du nouveau bot et la
nouvelle clé DeepSeek à l'agent CHATBOT, qui exécute la rotation (ce document).

**Identité du nouveau bot** : `@ePerformance_bot` (id `8873088998`) — c'est un
bot NOUVEAU, pas un nouveau token du même bot. L'ancien bot est mort : son
token ne répond plus (`getUpdates` → `ok:false`, Unauthorized).

## 2. Cause de la fuite initiale — IDENTIFIÉE

La cause n'est pas une supposition, elle est documentée depuis l'incident du
18/09 (entrée du journal de coordination, 22:15) :

- **`TELEGRAM_BOT_TOKEN` était en clair dans un dépôt PUBLIC** (`unified-ia-backend`,
  5 fichiers, dont une valeur par défaut codée en dur dans `config.py`).
- Les dépôts publics sont moissonnés en continu par des robots ; un token de bot
  exposé donne à n'importe qui le contrôle total du bot (lecture des messages
  via `getUpdates`, envoi de messages à tous les chats ayant déjà parlé au bot).
- La valeur a été retirée des fichiers le 18/09, mais **l'historique git public
  la conserve** — et une réécriture d'historique du dépôt public n'a pas été
  faite à ce jour. Tant que le token n'était pas révoqué chez BotFather, la
  fuite restait active. C'est ce qui a mené à la compromission constatée le 22/09.

**Leçon** : la rotation finit quand les clients suivent, mais elle COMMENCE par
la révocation chez le fournisseur. Ici, la révocation a tardé de 4 jours.

## 3. Ce qui a été fait (24/09)

### 3.1 Vérifications préalables (mesurées, pas supposées)

| Vérification | Résultat |
|---|---|
| Ancien token (getMe / getUpdates) | **mort** — révoqué ou bot supprimé |
| Nouveau token (getMe) | **actif** — `@ePerformance_bot`, id 8873088998 |
| Nouvelle clé DeepSeek (`/v1/models`) | **HTTP 200** — valide |
| Webhook du nouveau bot (`getWebhookInfo`) | **aucun** — propre, rien à supprimer |
| Message réel au chat admin | **délivré** (message_id 4) — bout en bout prouvé |

### 3.2 Emplacements des nouvelles valeurs

| Emplacement | Variables | État |
|---|---|---|
| **Railway** (backend de production) | `TELEGRAM_BOT_TOKEN`, `DEEPSEEK_API_KEY` | posées le 24/09, **service à redéployer** |
| `docker-unified/unified-ia-backend/.env` | `TELEGRAM_BOT_TOKEN`, `DEEPSEEK_API_KEY`, `DEEPSEEK_KEY` | posées |
| `unified_ia_system/.env` | idem | posées |
| `agent-ia-web/.env` | `TG_TOKEN` | posée |
| `toolkit_eperformance/.env` | `DEEPSEEK_API_KEY` (l'ancienne répondait **401** : le toolkit était en panne d'authentification silencieuse depuis la rotation précédente) | posée |
| `Eperformance/.env` (copie locale LWS) | `DEEPSEEK_API_KEY` (l'ancienne répondait **401**) | posée |
| `Eperformance/secrets.php` (copie locale LWS) | fallbacks `TG_TOKEN` (l.67) et `DEEPSEEK_KEY` (l.50) | posées |

### 3.3 Anciennes valeurs retirées des fichiers du toolkit

14 fichiers / 18 emplacements portaient l'ancien token Telegram (ou l'ancienne
clé DeepSeek pour 1) en clair. Le toolkit **n'a aucun remote** — rien n'était
publié, c'était du nettoyage préventif :

- `webhook_reponse.php`, `webhook_wa.php` (racine) · `api/{webhook_reponse,cron_publications,cron_sequences,stop_prospect}.php`, `api/README-API.md`, `api/config_reseaux.example.json`
- 4 exports `n8n/*.json` (reliques d'export — la base n8n live de référence n'a
  plus d'emplacement Telegram à corriger : les workflows qui appelaient notre
  API portaient le jeton Bearer, corrigé le 19/09 ; aucun nœud Telegram n'y vit)
- `PLAN_UNIFICATION_EPERFORMANCE.md` (ancienne clé DeepSeek → référence)
- `Eperformance/secrets.php` (copie locale ; remis à la valeur NOUVELLE, voir 3.2)

Remplacement : placeholder explicite + renvoi vers `.env`/secrets, sauf la
copie locale `secrets.php` qui doit rester synchronisable (valeur réelle).

### 3.4 Renforcement — whitelist chat_id (code, testé)

`backend/chatbot/notifications.py` — `_envoyer_telegram()` :

- **Le bot n'écrit plus qu'aux chat_id listés dans `TELEGRAM_ADMIN_CHAT_ID`**
  (plusieurs valeurs séparées par des virgules acceptées).
- Tout autre destinataire est **refusé avant l'appel réseau** : statut
  `refuse_whitelist`, code `whitelist`, motif explicite, trace en base comme
  les autres statuts. Un token compromis ou une route admin trompée ne peut
  plus transformer le bot en relais vers des chats inconnus.
- Outrepasser exige `TELEGRAM_ALLOW_ANY_CHAT_ID=true` — variable explicite,
  prévue pour le multi-tenant à venir, jamais un défaut.
- 4 tests ajoutés (`test_tache_6_5_notifications.py` → 40 passés). Suite
  backend complète : **410 passés** (+4), 2 erreurs préexistantes inchangées.
  Parité Docker répliquée (contrat C12) : **157 fichiers identiques**.

## 4. 🔴 LISTE LWS — à poser par Ballo via cPanel (actionnable, dans l'ordre)

Le serveur LWS a **deux fichiers à modifier** — les 10 autres fichiers listés
lisent les constantes, ils ne portent aucune valeur :

| # | Fichier serveur (cPanel) | Nature | Action précise |
|---|---|---|---|
| 1 | `Eperformance/.env` | clé DeepSeek `DEEPSEEK_API_KEY` (valeur actuelle **401 — invalidée** : le chatbot PHP de LWS est en panne d'authentification) | remplacer la ligne `DEEPSEEK_API_KEY=…` par la nouvelle valeur (fichier local `EP-PROD-DEEPSEEK-NOUVEAU.txt`) |
| 2 | `Eperformance/.env` | clé DeepSeek fallback `DEEPSEEK_KEY` : **absente du .env** — le fallback en dur de `secrets.php` l.50 est **mort (401)** → les appels DeepSeek de `db.php` (l.60) et `health.php` (l.36) sont **en panne silencieuse** | ajouter une ligne `DEEPSEEK_KEY=<nouvelle valeur>` — le mécanisme `getenv()` prioritaire de `secrets.php` la prendra sans éditer le code |
| 3 | `Eperformance/.env` | token Telegram `TG_TOKEN` : **absent du .env** — le fallback en dur de `secrets.php` l.67 est le token mort | ajouter une ligne `TG_TOKEN=<nouveau token>` (fichier local `EP-PROD-TELEGRAM-NOUVEAU.txt`) |
| 4 | (aucun fichier) | vérification | relancer un cron ou `health.php` : plus aucun 401 en log |

**Rappel du mécanisme** (`secrets.php` tête de fichier) : le `.env` est chargé
et prioritaire via `getenv()` ; les valeurs en dur ne sont que des fallbacks.
**Ajouter dans le `.env` est donc la voie documentée** — éditer `secrets.php`
n'est pas nécessaire (mais la copie locale est déjà à jour si tu préfères
synchroniser).

Fichiers qui liront ces constantes sans modification (pour information) :
`chatbot.php` (l.70), `config.php`, `db.php`, `health.php`, `alertes.php`,
`analyse_csv.php`, `worker_livrables.php`, `cron_{publications,relances,clients_web,taches_web,rapport}.php`,
`webhook_reponse.php`, `stop_prospect.php` (Telegram).

**Non concerné par cette rotation** : `CRON_KEY` / `API_BEARER_TOKEN`
(déjà tournées le 19/09, URLs des tâches planifiées cPanel vérifiées 200).

## 5. Actions restantes pour le propriétaire (BotFather / compte Telegram)

1. **Supprimer définitivement l'ancien bot** (BotFather → `/deletebot` ou au
   minimum `/revoke`) — tant qu'il existe, il est une porte enregistrée à son nom.
2. **Activer la double authentification** du compte Telegram qui possède les bots.
3. Rien à faire côté Meta/webhook : le nouveau bot n'a **aucun webhook** (bot
   de notification sortant) et la chaîne WhatsApp/Meta n'utilise pas ce bot.

## 6. Déploiement backend

Les nouvelles variables Railway sont posées mais le service **doit être
redéployé** pour les lire ; le redéploiement embarque aussi le garde-fou
whitelist. À la livraison du lot : `railway up` + vérification production
(`/health` 200, `notify` canal telegram → envoyé).

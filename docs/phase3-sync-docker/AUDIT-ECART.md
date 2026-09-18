# AUDIT D'ÉCART — `docker-unified/unified-ia-backend/` ↔ backend Railway

**Date** : 2026-09-18 23 h · **Auteur** : agent CHATBOT · **État** : mesuré **avant** toute correction.

## Pourquoi ce document

`docker-unified/unified-ia-backend/` n'est pas un environnement de test : c'est le **backend qui remplacera Railway** sur un serveur dédié. Il doit rester à 100 % synchrone pour qu'un basculement soit possible à tout moment sans perte. Au 18/09 il était resté à un **instantané du 13/09** — six jours de retard.

## Nature de la cible

| Fait | Valeur | Conséquence |
|---|---|---|
| Dépôt git dans le dossier Docker | **non** | copie simple : aucune traçabilité, la parité doit être vérifiée par script |
| `requirements.txt` | **identique** à la source | aucune dépendance manquante — `pywebpush` manque des deux côtés (attente propriétaire) |
| `migrations/` | **identiques**, 6 fichiers | rien à faire |
| Fichiers propres à Docker | `docker-compose.yml`, `Dockerfile` | **à ne jamais écraser** : une copie naïve de la source les supprimerait |
| `scripts/` | **absent de Docker** | 4 scripts à copier (dont `verifier-secrets.py` et le smoke test) |
| `.env` | présent, 5 793 o, **13/09** | **contient les secrets exposés** retirés du dépôt public le 18/09 ; non versionné, donc non publié, mais à reposer après rotation |

## 1. Fichiers Python manquants (7)

| Fichier | Ce qui est perdu au basculement |
|---|---|
| `backend/chatbot/vision.py` | **la vision** — Mia ne décrit plus les images |
| `backend/chatbot/retention.py` | **la purge de conformité à 12 mois** — la page cookies devient fausse |
| `backend/chatbot/blog_search.py` | **la recherche sur le blog** (6.8) |
| `backend/chatbot/notifications.py` | **les notifications multi-canal** (6.5) |
| `backend/chatbot/test_tache_6_3_bis.py` | couverture de test Bloc A |
| `backend/chatbot/test_tache_6_5_notifications.py` | couverture de test 6.5 |
| `backend/chatbot/test_tache_6_8_recherche_blog.py` | couverture de test 6.8 |

## 2. Fichiers divergents (13)

`backend/api/app.py` · `backend/api/routes/admin_chatbot.py` · `backend/api/routes/chatbot.py` · `backend/api/routes/notifications.py` · `backend/chatbot/agent_router.py` · `backend/chatbot/models.py` · `backend/chatbot/response_generator.py` · `backend/chatbot/service.py` · `backend/chatbot/test_phase1_j3_pipeline.py` · `backend/communication/config.py` · `backend/communication/providers/telegram_provider.py` · `backend/communication/workers/notification_worker.py` · `backend/core/llm_client.py`

Les porteurs de corrections structurantes : `llm_client.py` (**vision DeepSeek**), `service.py` (**mémoire de conversation** — le bug d'amnésie), `agent_router.py` (**9 intents**), `chatbot.py` (**retrait de `metadata.agent_used`**, décision du propriétaire), les 3 fichiers de `communication/` (**retrait du jeton Telegram codé en dur**).

## 3. Variables d'environnement

Le code lit **50 variables**. Le `.env` de Docker en déclare 70, dont **21 attendues par le code sont absentes** :

- `BLOG_*` (14) — la recherche 6.8 : `BLOG_INDEX_PATH`, `BLOG_INDEX_URL`, `BLOG_SEARCH_ENABLED`, `BLOG_SEARCH_LIMIT`, `BLOG_SEARCH_LIMIT_MAX`, `BLOG_SEARCH_SEUIL_SCORE`, `BLOG_SEARCH_SEUIL_COUVERTURE`, `BLOG_INDEX_TTL_SECONDES`, `BLOG_INDEX_CACHE`, `BLOG_FETCH_*`, `BLOG_CONTEXT_*`
- `DEEPSEEK_*` (3) — `DEEPSEEK_API_URL`, `DEEPSEEK_MIN_TOKENS`, `DEEPSEEK_REASONING_EFFORT`
- `NOTIF_*` (2) — `NOTIF_TIMEOUT`, `NOTIF_TRACE_CORPS`
- `RAILWAY_GIT_COMMIT_SHA`, `RUN_TESTS_INTEGRATION`

Toutes ont une valeur par défaut dans le code : le service démarre sans elles. Mais un `.env` qui ne les déclare pas rend la parité **invisible** — on croit avoir tout, et l'écart ne se voit qu'au premier comportement différent.

## 4. n8n — écart entre la consigne et le dépôt

La consigne décrit « FastAPI + PostgreSQL + n8n » et demande de vérifier **3 services** healthy. Le `docker-compose.yml` en déclare **deux** (`postgres`, `backend`), et **aucun fichier du dépôt ne mentionne n8n** — ni le code, ni les migrations, ni la documentation.

**Je ne crée pas un service que rien n'utilise.** Signaler vaut mieux qu'inventer de l'infrastructure : soit n8n est un projet à venir qu'il faut provisionner, soit la description était approximative. Décision au propriétaire.

## 5. Ce que la parité doit garantir après correction

1. `docker compose up` démarre `postgres` puis `backend` en **healthy**
2. `/health` → 200
3. `POST /api/chatbot/message` → 200, **avec vision** (image → description)
4. `GET /api/chatbot/search` → 200, résultats sur requête de contrôle
5. `POST /api/chatbot/admin/notify` → **401 sans jeton**, et fonctionnel avec
6. `metadata.agent_used` **absent** de la réponse publique
7. Purge de rétention : `dry_run` puis exécution réelle sur conversation artificielle
8. 171 tests widget · 170 backend · 36 notifications
9. `verifier-secrets.py` → PASS
10. `agent_used` absent, aucun nom d'agent exposé

## 6. Contrôle permanent

Un script `verifier-parite-docker.py` compare les arborescences et **échoue sur divergence**, intégré au smoke test pre-push : sans lui, l'écart se recrée en silence dès la première modification qui n'est pas répliquée. C'est l'objet du contrat **C12**.

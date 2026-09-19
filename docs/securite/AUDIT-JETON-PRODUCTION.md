# AUDIT — JETON API DE PRODUCTION (secret n°4)

**Date** : 2026-09-19 · **Agent** : CHATBOT · **Objet** : préparation de la rotation du quatrième secret exposé le 18/09.
**Aucune valeur de jeton n'est reproduite dans ce document** — tout est signalé par `fichier:ligne` et par nature.

---

## 1. Ce que la consigne annonçait, et ce que la mesure montre

La consigne décrit un jeton « partagé entre le backend FastAPI (Railway + Docker) et le PHP sur LWS », authentifiant le backend auprès du PHP, avec une étape « poser côté Railway » et une étape « supprimer l'ancienne variable côté Railway ».

**Ce n'est pas ce que le code dit.** Vérifié trois fois :

| Vérification | Méthode | Résultat |
|---|---|---|
| Le backend contient-il le jeton ? | recherche sur `unified-ia-backend/backend/**` et `docker-unified/unified-ia-backend/backend/**` | **0 occurrence** |
| Le backend appelle-t-il le PHP ? | recherche de `proxy.php`, `api_mobile.php`, `cron_blog.php`, `api.eperformance.pro` dans le backend | **aucun appel** ; `/sites/{id}/configure` y est une **route FastAPI**, pas un appel sortant |
| Existe-t-il une variable d'environnement de jeton côté backend ? | inventaire des variables lues | seules les clés LLM, le `SECRET_KEY` JWT, Brevo, Telegram, VAPID, WhatsApp — **aucun jeton de production** |

**Conséquence : l'étape « Railway » de la consigne reposerait sur une prémisse fausse.** Toucher Railway donnerait l'impression d'avancer sans rien changer au problème, et laisserait intacts les vrais clients du jeton.

## 2. Qui utilise réellement ce jeton

La direction est l'inverse de celle décrite : **le PHP de cPanel est le validateur, tout le reste est client.**

```
                    ┌──────────────────────────────┐
                    │  secrets.php (cPanel / LWS)  │
                    │  CRON_KEY          = <jeton> │  ← LE VALIDATEUR
                    │  API_BEARER_TOKEN  = <jeton> │
                    └───────────────┬──────────────┘
                                    │ compare ($auth !== 'Bearer '.$TOKEN)
        ┌───────────────┬───────────┴────────┬──────────────────┐
        │               │                    │                  │
   crons LWS        n8n (localhost:5678)  outillage toolkit   agent-ia-web
 cron_publications  webhooks, lecture_csv prospect_app.py     chatbot_register.php
 cron_sequences     stop_prospect, ...   content_engine.py    reinstaller_config.sh
                                         prospect_scraper.py
```

**Le backend FastAPI n'apparaît nulle part dans cette carte**, et c'est cohérent : il ne parle pas au PHP.

## 3. Inventaire complet — 48 fichiers

| Dépôt | Publié ? | Fichiers | Dont suivis par git |
|---|---|---|---|
| `site-eperformance` | **PUBLIC** | 1 | **0** |
| `toolkit_eperformance` | non publié (aucun remote) | 40 | 31 |
| `agent-ia-web` | non publié (aucun remote) | 7 | 3 |
| `unified-ia-backend` | public | **0** | 0 |
| `docker-unified` | non publié | **0** | 0 |

### 3.1 Le seul fichier d'un dépôt public

`site-eperformance/docs/refonte-dashboard/AUDIT-M1-ACQUISITION.md:952` — un exemple `curl` avec `Authorization: Bearer <jeton>`.
**Non suivi par git** (le dossier `docs/refonte-dashboard/` est entier non suivi), donc **non publié** — mais il vit dans l'arborescence d'un dépôt à remote **public** : un seul `git add` l'exposerait. Le garde-fou `verifier-secrets.py` installé en pre-push sur ce dépôt bloquerait ce push, donc le risque est couvert — mais le fichier n'aurait pas dû contenir la valeur.
→ **Hors de mon périmètre** (refonte SITE/SOCIAL) : signalé, non corrigé.

### 3.2 Répartition par nature, dans le toolkit (40 fichiers)

| Nature | Nombre | Exemple |
|---|---|---|
| PHP (endpoints et copies cPanel) | 20 | `Eperformance/secrets.php:76`, `webhook_reponse.php:23` |
| Configuration JSON | 5 | `template_whatsapp_j0.json` |
| Documentation | 8 | `PATCH_NOTES.md` |
| Python (outillage) | 4 | `prospect_app.py:771`, `content_engine.py:1986` |
| Page HTML, texte, tâche cron | 3 | `dashboard.html` |

### 3.3 Le cas le plus dangereux du lot

Quatre fichiers Python lisent le jeton depuis une variable d'environnement **avec l'ancienne valeur en repli codé en dur** :

```
prospect_app.py:771, 800, 830, 862, 1871, 1914, 1998   os.environ.get("EPERF_API_TOKEN", "<ancien jeton>")
content_engine.py:1986                                  os.environ.get("EPERF_API_TOKEN", "<ancien jeton>")
prospect_scraper.py:37                                  API_TOKEN = "<ancien jeton>"
```

**C'est le piège de cette rotation** : après bascule, si la variable `EPERF_API_TOKEN` n'est pas posée dans l'environnement d'exécution de ces outils, ils enverront **l'ancien jeton en silence** — et recevront 401 sans que rien n'indique pourquoi. Le repli doit être **retiré**, pas seulement contourné.

## 4. Découverte annexe — trois autres jetons sont devinables

Dans le même fichier `secrets.php`, trois autres secrets sont des chaînes **prévisibles**, contrairement au jeton tourné qui, lui, est aléatoire :

| Constante | Nature de la valeur | Risque |
|---|---|---|
| `ADMIN_TOKEN` | chaîne lisible de type `<mot>_token_<année>_<mot>` | devinable par dictionnaire |
| `MOBILE_API_TOKEN` | même schéma | devinable |
| `CHATBOT_API_TOKEN` | même schéma | devinable |

Ces trois-là ne sont **pas** dans la fuite du 18/09, mais un jeton qui se devine par dictionnaire n'a pas besoin de fuiter. **Recommandation : les tourner aussi, avec `openssl rand -hex 32` comme le quatrième.** Ils ne sont pas dans le périmètre de cette mission ; je les signale.

**Point de durcissement, non bloquant** : la comparaison est un `!==` de chaînes (`webhook_reponse.php:27`, `stop_prospect.php:67`), donc non à temps constant. `hash_equals()` supprimerait la surface de mesure temporelle. À faire lors d'une prochaine intervention sur ces fichiers, pas dans cette rotation.

## 5. Séquence de rotation corrigée

Le PHP valide **une seule valeur** et ne peut pas accepter l'ancienne et la nouvelle en même temps sans modification. Il y a donc une fenêtre pendant laquelle quelque chose envoie le mauvais jeton.

**Ce que la fenêtre coûte réellement** — et c'est ce qui rend l'opération peu risquée : les clients du jeton sont des **crons et des outils internes**, pas la surface publique. Le site, le blog et le chatbot n'utilisent pas ce jeton. Un cron qui échoue se rattrape au tic suivant ; un webhook n8n peut être rejoué. Au pire, une publication de blog est retardée d'une heure.

| # | Qui | Action |
|---|---|---|
| 1 | **Ballo** | Poser le nouveau jeton dans `secrets.php` (cPanel) — remplacer la valeur de **`CRON_KEY`** et d'**`API_BEARER_TOKEN`** (les deux portent le même secret) |
| 2 | **Ballo** | Confirmer ici, **sans la valeur** (par exemple : « posé ») |
| 3 | **Moi** | Vérifier immédiatement la sonde de production, puis basculer les clients de mon ressort |
| 4 | **SOCIAL / NOYAU** | Poser `EPERF_API_TOKEN` dans l'environnement des outils du toolkit et d'agent-ia-web, **et retirer les replis codés en dur** (§3.3) |
| 5 | **Ballo** | Mettre à jour les workflows n8n (le jeton y circule en en-tête `Authorization`) |
| 6 | **Ballo** | Retirer l'ancienne valeur de `secrets.php` une fois tous les clients basculés |

**Ce que je ne peux pas faire :** accéder à cPanel (étapes 1, 2, 6) et modifier les workflows n8n (étape 5). Je ne tente ni l'un ni l'autre.

## 6. Ce que cette rotation ferme, et ce qu'elle ne ferme pas

**Elle ferme** l'usage du jeton fuité : après l'étape 6, la valeur présente dans les 48 fichiers ne vaudra plus rien.

**Elle ne ferme pas** la fuite elle-même : la valeur reste dans l'historique git de `site-eperformance` (dépôt public) où elle a été publiée. C'est la raison pour laquelle la rotation est la seule réparation possible — réécrire les fichiers ne répare rien, et réécrire l'historique d'un dépôt public ne le « dé-publie » pas.

**Elle ne touche pas** Railway ni le backend FastAPI, pour la raison mesurée au §1.

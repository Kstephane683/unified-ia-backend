# ROTATION DU JETON API DE PRODUCTION — rapport

**Date** : 2026-09-19 · **Agent** : CHATBOT · **Statut** : rotation **faite et vérifiée** ; remise en marche des clients **en cours**.
**Aucune valeur de jeton dans ce document.**

---

## 1. Ce qui a été fait

| # | Étape | État |
|---|---|---|
| 1 | Nouveau jeton généré (`openssl rand -hex 32`), hors dépôt, `0600` | ✅ |
| 2 | Audit exhaustif des 48 emplacements (`AUDIT-JETON-PRODUCTION.md`) | ✅ |
| 3 | Pose par Ballo dans `secrets.php` — constantes `CRON_KEY` **et** `API_BEARER_TOKEN` | ✅ confirmée |
| 4 | Vérification par sonde de production | ✅ **l'ancienne valeur rend 403, la nouvelle 200** |
| 5 | Scission de `CRON_KEY` / `API_BEARER_TOKEN` (réponse Q1) | 🔄 lot 2 prêt |
| 6 | Rotation des 3 constantes devinables (décision Ballo) | 🔄 lot 2 prêt |
| 7 | Remise en marche des clients | 🔴 **en cours — voir §4** |

## 2. Réponses aux deux questions

### Q1 — `CRON_KEY` et `API_BEARER_TOKEN` doivent-ils être identiques ? **NON.**

Mesuré, pas supposé : `CRON_KEY` est lu par `cron_publications.php:36` et `cron_sequences.php:41` ; `API_BEARER_TOKEN` est défini dans `secrets.php` pour les endpoints CRM. **Aucun fichier ne lit les deux.** Leur égalité vient du choix initial, pas d'une contrainte technique.

Le raisonnement de Ballo est retenu : `CRON_KEY` transite par URL (`?key=`) donc finit dans des journaux de serveurs et de proxies ; s'ils partagent la valeur, un journal compromis compromet aussi le Bearer. **Décision : on les scinde.** `CRON_KEY` **garde** la valeur posée — l'URL de la tâche planifiée cPanel la porte déjà, la changer imposerait une manipulation supplémentaire — et `API_BEARER_TOKEN` reçoit une valeur neuve.

### Q2 — Les trois constantes devinables : tournées, clients identifiés

| Constante | Clients (mesurés) | Repli codé en dur ? |
|---|---|---|
| `ADMIN_TOKEN` | agent-ia-web : `deliver.py`, `notifications.py` (variables d'environnement) ; côté serveur `proxy.php` (`maj_livraison_site`). Également présent dans `Eperformance/.env`, `notifications/config-notifications.php`, `gen-admin-token.php`, `agent-ia-web/.env` | non |
| `MOBILE_API_TOKEN` | **aucun client trouvé dans les dépôts** — endpoint `api_mobile.php` (en-tête `X-API-Key`), appelant **externe** | non |
| `CHATBOT_API_TOKEN` | agent-ia-web : `artisan.py`, `api/chatbot_register.php` | non |

**Recommandation sur `MOBILE_API_TOKEN`** : c'est le seul dont le consommateur n'est pas identifiable ici. Le tourner sans avoir identifié qui appelle l'API mobile **couperait ce service**. À faire en dernier.

Aucune des trois n'a de repli codé en dur dans le code Python — le piège des quatre replis du toolkit ne s'y répète pas. En revanche elles sont écrites **en clair dans cinq fichiers de configuration non publiés** : à mettre à jour, faute de quoi les outils enverront l'ancienne valeur en silence.

## 3. Preuves — sondes de production (19/09, 14h00)

| Endpoint | Résultat |
|---|---|
| `cron_publications.php?key=<nouvelle>` | **200** |
| `cron_sequences.php?key=<nouvelle>` | **200** |
| `lire_publications.php?key=<nouvelle>` | **200** |
| `stop_prospect.php?key=<nouvelle>` | **400** — l'authentification passe, c'est la requête qui est incomplète |
| `cron_sequences.php?key=<ancienne>` | **403** |
| `stop_prospect.php?key=<ancienne>` | **403** |
| `api_mobile.php` (sans en-tête) | 403 — attend son propre jeton |
| `chatbot_register.php` (sans en-tête) | 401 — attend `CHATBOT_API_TOKEN` |

**Conclusion : la rotation fonctionne.** Le secret fuité est mort ; le nouveau est accepté par la famille d'endpoints qui le concerne.

## 4. 🔴 Ce qui est cassé en ce moment, et pourquoi c'est attendu

Le PHP n'accepte plus que la nouvelle valeur. **Tout client qui envoie encore l'ancienne est arrêté depuis la pose** :

1. **Les tâches planifiées cPanel** — leur URL contient `?key=<ancienne>`. **La publication automatique du blog est arrêtée.** C'est la conséquence la plus visible et la plus urgente. Action : mettre à jour l'URL des tâches `cron_publications.php` et `cron_sequences.php` avec la valeur actuelle de `CRON_KEY`.
2. **n8n** (`localhost:5678`) — les workflows qui envoient `Authorization: Bearer <ancienne>` échouent.
3. **Toolkit** — `EPERF_API_TOKEN`, et surtout **quatre fichiers portent l'ancienne valeur en repli codé en dur** : ils l'enverront même sans variable d'environnement. Le repli doit être **retiré**, pas contourné.
4. **agent-ia-web** — `.env` (ADMIN_TOKEN) et `artisan.py` (CHATBOT_API_TOKEN).

**Ordre conseillé** : tâches planifiées d'abord (le blog repart), puis n8n, puis toolkit et agent-ia-web.

## 5. Ce que cette rotation ne ferme pas

La valeur reste dans l'**historique git** du dépôt public du site, où elle a été publiée le 18/09 **et de nouveau le 19/09 à 11h54** (commit `0325d96`). Réécrire les fichiers ne répare rien : la rotation est la seule réparation, et elle est faite. Reste à retirer l'occurrence vivante de `docs/refonte-dashboard/AUDIT-M1-ACQUISITION.md:952` — désormais sans danger puisqu'elle est morte, mais elle bloque les push du dépôt tant qu'elle est là.

## 6. Le lot 2, prêt

`/home/ballo/EP-PROD-JETONS-LOT2.txt` — permissions `0600`, hors de tout dépôt. Contient les 4 jetons (1 scission + 3 constantes devinables), leurs empreintes, les clients de chacun et l'ordre des poses. Vérifié : aucun des quatre n'apparaît dans une arborescence de dépôt ni dans un script.

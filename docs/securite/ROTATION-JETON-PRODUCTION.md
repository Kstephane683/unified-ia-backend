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

---

## 7. Scission `CRON_KEY` / `API_BEARER_TOKEN`

**Fait** : nouveau `API_BEARER_TOKEN` généré, consigné **hors dépôt** dans `/home/ballo/EP-PROD-JETON-BEARER.txt` (`0600`) avec la valeur, l'empreinte, la raison, les clients et l'ordre. **`CRON_KEY` ne change pas** — l'URL de la tâche planifiée cPanel la porte déjà.

Deux fichiers portaient la même valeur (lot 2 et le fichier dédié) : la valeur a été **retirée du lot 2**, qui y renvoie désormais. **Un secret, un fichier** — deux sources pour un même secret reproduiraient exactement le défaut que nous venons de supprimer avec les copies du journal de coordination.

### Clients de `API_BEARER_TOKEN` — identifiés nommément

**1. n8n — cinq workflows portent le jeton en clair dans leurs nœuds** (lus dans `n8n-compose/n8n_data/database.sqlite`) :

| Workflow | État | Nœud concerné |
|---|---|---|
| `Meta Webhook — Réponses & Statuts (ePerformance)` | **ACTIF** | « Réponse prospect ? » — en-tête `Authorization` |
| `prospect-manuel` | inactif | `HTTP Request` / `Authorization` |
| `WhatsApp Sequences J0-J3-J7 (ePerformance)` | inactif (2 versions) | nœud `api_token` |
| `WhatsApp Séquence J+3 (ePerformance)` | inactif | nœud `api_token` |
| `WhatsApp Séquence J+7 (ePerformance)` | inactif | nœud `api_token` |

Le workflow **actif envoie l'ancienne valeur** : les réponses aux webhooks Meta sont cassées depuis la bascule. Les quatre inactifs sont des **pièges à retardement** — à corriger en même temps, sinon ils échoueront silencieusement le jour où on les réactive.

Une credential `[httpHeaderAuth] « Header Auth account »` existe également ; sa valeur est **chiffrée** et illisible hors de l'interface n8n — à vérifier là-bas.

**2. L'outillage du toolkit** — `prospect_scraper.py`, `prospect_app.py`, `content_engine.py` : replis codés en dur de l'ancienne valeur, à **retirer**. **8 occurrences restantes**, périmètre SOCIAL.

---

## 8. Les trois constantes devinables

Décision du propriétaire : on les tourne. Quatre jetons générés (dont celui de la scission), consignés hors dépôt, avec leurs clients.

| Constante | Clients mesurés | Repli codé en dur |
|---|---|---|
| `ADMIN_TOKEN` | agent-ia-web : `deliver.py`, `notifications.py` ; serveur : `proxy.php` (`maj_livraison_site`) | non |
| `CHATBOT_API_TOKEN` | agent-ia-web : `artisan.py`, `api/chatbot_register.php` | non |
| `MOBILE_API_TOKEN` | **aucun client dans les dépôts** — appelant externe | non |

### `MOBILE_API_TOKEN` — ne pas le tourner avant d'avoir mesuré

C'est le seul dont le consommateur n'est pas identifiable depuis les dépôts. Le tourner sans lui **couperait l'API mobile**.

**Méthode : mesurer le trafic, pas deviner.**
- cPanel → **Metrics → Raw Access Logs**, ou en SSH : `grep api_mobile.php ~/logs/*access*log | awk '{print $1, $12}' | sort | uniq -c | sort -rn | head`
- **Si aucun appel n'apparaît sur 30 jours, l'endpoint n'a pas de client** — le tourner (ou le désactiver) ne coupe rien. C'est la seule façon de trancher sans risque.
- Variante : journaliser temporairement l'IP et le `User-Agent` dans `api_mobile.php`, puis relire après quelques jours.

### Fichiers de configuration à mettre à jour

Cinq fichiers non publiés portent ces constantes **en clair** : `Eperformance/.env`, `notifications/config-notifications.php`, `gen-admin-token.php`, `agent-ia-web/.env`. Périmètres **SOCIAL** et **NOYAU** — consignes déposées, aucun correctif écrit depuis mon périmètre.

---

## 9. Bilan du nettoyage

**42 occurrences** de l'ancienne valeur subsistent dans les dépôts **non publiés** (toolkit, agent-ia-web), et **8 replis codés en dur**. Ce n'est plus une fuite — la valeur est morte et ces dépôts n'ont pas de remote — c'est du nettoyage. Mais tant que les replis sont là, les outils enverront une valeur morte **sans le dire**.

---

## 10. Correction de n8n — faite et prouvée (19/09, fin de journée)

### Pourquoi le premier essai échouait (HTTP 400)

Trois causes distinctes, chacune diagnostiquée par le corps de la réponse — le
log d'erreur ajouté au script a fait la différence :

1. **`request/body/active is read-only`** : l'API n8n refuse le champ `active`
   dans le PUT. Dans cette version, l'état actif se pilote par des **endpoints
   dédiés** (`POST /workflows/{id}/activate` et `/deactivate`). Le payload a
   été réduit aux champs réellement modifiables (`name`, `nodes`,
   `connections`, `settings`).
2. **`Cannot update an archived workflow`** : deux des six workflows sont
   **archivés** dans n8n (`isArchived: true`) et refusent toute écriture. Ce
   sont des reliques volontairement abandonnées : elles portent encore
   l'ancien jeton, mais elles ne tourneront plus sans une décision
   d' désarchivage.
3. Un workflow qui échoue n'arrête plus les autres : le script journalise
   l'erreur complète et continue.

### Résultat

| Workflow | État | Jeton ancien | Jeton nouveau |
|---|---|---|---|
| **Meta Webhook — Réponses & Statuts** | **ACTIF** | 0 | **1** |
| WhatsApp Séquence J+3 | inactif | 0 | 3 |
| WhatsApp Séquence J+7 | inactif | 0 | 3 |
| WhatsApp Sequences J0-J3-J7 | inactif | 0 | 3 |
| WhatsApp Sequences J0-J3-J7 (2ᵉ version) | **archivé** | 5 | 0 |
| prospect-manuel | **archivé** | 2 | 0 |

**16 emplacements corrigés, réellement, par l'API officielle.** Les 2
restants sont dans des workflows archivés — inoffensifs tant qu'ils ne sont
pas désarchivés, et à corriger le jour où on le fait.

### Preuve que le workflow actif fonctionne

Test réel de la vérification Meta (exigence de l'API Meta : le `hub.challenge`
doit être répercuté) :

```
GET /webhook/meta-whatsapp?hub.mode=subscribe&hub.verify_token=<valeur attendue>&hub.challenge=essai-4251
→ HTTP 200, corps : essai-4251
```

**Le workflow actif répond, vérifie son jeton et renvoie le challenge** : la
chaîne Meta → n8n → webhook_reponse.php est de nouveau opérationnelle.

**Découverte au passage** : le jeton de vérification attendu par n8n n'est pas
`ep_perf_verify_2026` (celui du PHP) mais une valeur distincte de 64
caractères hexadécimaux, codée dans la condition du nœud « Token valide ? ».
Il existe donc **deux** jetons de vérification en parallèle (PHP et n8n), et
Meta n'en envoie qu'un : **seule l'URL configurée chez Meta importe**. Le
chemin n8n étant `/webhook/meta-whatsapp` en production, c'est n8n qui reçoit
la vérification — et il la valide avec sa propre valeur.

### Ce qui reste

- **2 nœuds archivés** portent l'ancien jeton — inoffensifs, à corriger si un
  jour on désarchive.
- **L'outillage du toolkit** (8 replis codés en dur) et **agent-ia-web** :
  demandes déposées aux agents concernés.
- **`MOBILE_API_TOKEN`** : mesurer le trafic avant de tourner (méthode au §8).

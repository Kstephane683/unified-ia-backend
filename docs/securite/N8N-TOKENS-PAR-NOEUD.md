# n8n — nature des jetons, nœud par nœud

**Date** : 2026-09-19 · **Agent** : CHATBOT · **Méthode** : lecture seule de `n8n-compose/n8n_data/database.sqlite` (module `sqlite3` de Python — l'outil en ligne de commande n'est pas installé).
**Aucune valeur de jeton d'API dans ce document.** Le jeton de vérification Meta est cité : il n'est pas un secret critique (voir §1).

---

## 1. La prémisse de la consigne ne s'applique pas — et c'est une bonne nouvelle

La consigne supposait qu'un **jeton de vérification Meta** avait pu être changé côté n8n alors que Meta garde l'ancien, et qu'il faudrait donc « remettre l'ancien dans n8n » pour éviter d'aller dans Meta App Dashboard.

**La mesure dit autre chose, et c'est plus simple : ce jeton n'a jamais été touché.**

Le nœud de vérification porte **`ep_perf_verify_2026`** (19 caractères) — un **troisième jeton**, distinct des deux qui ont tourné :

| Jeton | Longueur | Rôle | Touché par la rotation ? |
|---|---|---|---|
| le jeton d'API de production (25 caractères, valeur **non reproduite**) | 25 | API de production (cPanel ↔ clients) | **oui** — mort depuis le 19/09 |
| `ep_perf_verify_2026` | 19 | vérification du webhook Meta, comparaison locale | **non** |
| `EAA…` (204 car.) | 204 | API Meta (page / WhatsApp) | non — et à ne pas toucher |

`ep_perf_verify_2026` se trouve aussi dans `webhook_wa.php`, `Eperformance/webhook_wa.php`, `templates_whatsapp_meta.md` et l'export JSON du workflow — donc c'est bien le jeton de vérification du webhook, inchangé.

**Conséquences, et elles règlent la question posée :**
- **Rien à restaurer** dans n8n : la valeur présente est celle d'origine.
- **Rien à faire dans Meta App Dashboard** — la prudence qui motivait cette piste ne s'applique pas. Ballo a raison de refuser cette manipulation, et elle est inutile.
- **Rien à changer pour les jetons Meta (`EAA…`)** : ils n'ont pas bougé.

## 2. Ce qui est réellement cassé : 17 nœuds portent le jeton mort

Aucun nœud n8n ne porte le nouveau jeton. **17 nœuds portent l'ancien, qui rend 403 depuis la bascule** — comptés, pas estimés.

| Workflow | État | Nœuds à corriger | Appels concernés |
|---|---|---|---|
| **Meta Webhook — Réponses & Statuts** | **ACTIF** | **1** (`Analyse réponse → CSV`) | `webhook_reponse.php` |
| WhatsApp Sequences J0-J3-J7 (2 versions) | inactif | 5 puis 3 | `lecture_csv.php`, `update_status.php` |
| WhatsApp Séquence J+3 | inactif | 3 | `lecture_csv.php`, `update_status.php` |
| WhatsApp Séquence J+7 | inactif | 3 | `lecture_csv.php`, `update_status.php` |
| prospect-manuel | inactif | 2 | `lecture_csv.php`, `update_status.php` |

**Le workflow actif est le seul dont la panne a un effet aujourd'hui** : les réponses aux webhooks Meta ne sont plus enregistrées. Les 16 autres nœuds sont dans des workflows inactifs — ils ne cassent rien maintenant, mais échoueront silencieusement le jour où on les réactivera.

**La nature de chaque jeton, nœud par nœud :**

- **Jeton de vérification Meta** — nœud `Meta Verification (GET)` du workflow actif. **Ne pas modifier.**
- **Jeton de notre API (ancien, mort)** — tous les nœuds `httpRequest` et les nœuds `Config` (`set`) qui alimentent `api.eperformance.pro`. **À remplacer** par le nouveau `API_BEARER_TOKEN`.
- **Jeton de l'API Meta (`EAA…`)** — nœuds `Config` des trois workflows WhatsApp. **Ne pas modifier.**

## 3. Ce que je n'ai pas fait, et pourquoi

**Je n'ai pas écrit dans la base n8n.** Deux raisons :

1. **L'API n8n exige une authentification que je n'ai pas** : les identifiants du `docker-compose.yml` sont des renvois de variables (pas de valeur lisible), et il n'existe **aucune clé d'API** en base (la table `api_keys` n'existe pas dans cette version). Je ne peux donc pas passer par la voie *supportée*, qui gère la versioning et le rechargement des workflows.
2. **Écrire directement dans le SQLite d'une instance n8n en marche est risqué** : n8n garde l'état en mémoire et historise les versions ; une écriture hors de son dos peut être écrasée au prochain enregistrement, ou laisser la base et l'instance incohérentes. Sur de l'automatisation de production, ce n'est pas un pari à prendre pour éviter cinq minutes de saisie.

**Ce que je fournis à la place** (voir §4) : la liste exacte des modifications (**17 nœuds, 17 emplacements** — comptés), et un script qui les applique **par l'API n8n** dès qu'une clé existe — une clé se crée en deux minutes dans l'interface (`Settings → API`). Le script est en simulation par défaut.

## 4. Ce qui attend une action

| # | Qui | Action |
|---|---|---|
| 1 | **Ballo** | Poser le nouveau `API_BEARER_TOKEN` dans `secrets.php` (valeur dans `/home/ballo/EP-PROD-JETON-BEARER.txt`) |
| 2 | **Ballo** | Créer une clé d'API n8n (`Settings → API`) — ou saisir les 18 nœuds à la main depuis la liste du §5 |
| 3 | **Moi** | Appliquer les 17 remplacements (script en simulation d'abord, puis réel), vérifier le workflow actif |
| 4 | **Ballo** | Confirmer qu'une réponse Meta remonte bien jusqu'à `webhook_reponse.php` |

L'ordre compte : l'étape 1 d'abord, sinon les nœuds corrigés enverraient une valeur que le serveur n'accepte pas encore.

## 5. Liste des modifications

Voir `/home/ballo/N8N-WORKFLOWS-CORRIGES.txt` (permissions `0600`, hors de tout dépôt) : un tableau `workflow → nœud → ancienne valeur → nouvelle valeur`, prêt à être suivi à la main ou exécuté par le script.

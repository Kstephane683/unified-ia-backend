# RAPPORT — Tâche 6.8 : recherche sur le contenu du blog

Date : 2026-09-18 · Dépôt : `unified-ia-backend` · Branche : `main`

---

## 1. Ce qui est livré

| Livrable | Fichier |
|---|---|
| Moteur de recherche (index BM25F, extraction du texte, mémoïsation, dégradation) | `backend/chatbot/blog_search.py` |
| Endpoint `GET /api/chatbot/search?q=…&limit=…` | `backend/api/routes/chatbot.py` |
| Enrichissement non intrusif de `POST /api/chatbot/message` | `backend/chatbot/service.py` |
| Bloc de prompt « articles du blog » | `backend/chatbot/response_generator.py` |
| Banc de mesure rejouable | `scripts/benchmark_recherche_blog.py` |
| Tests (32) | `backend/chatbot/test_tache_6_8_recherche_blog.py` |

### L'endpoint

`GET /api/chatbot/search?q=<mots-clés>&limit=<1-20>` — public, sans coût LLM.
Réponse : `requete`, `resultats[]` (slug, titre, description, url, collection,
date, tags, `score`, `couverture`, `termes_trouves`, `pertinent`), `total`,
`message`, et `index` (`disponible`, `articles_indexes`, `articles_avec_corps`,
`genere_le`, `source`, `derniere_erreur`).

Nom retenu : `/api/chatbot/search`, conforme aux routes existantes (toutes sous
`/api/chatbot`). `q` est **facultatif** à dessein : une question vide produit une
réponse lisible en 200, jamais une erreur de validation — le widget enverra aussi
des requêtes partielles pendant la frappe. Aucun paramètre de cette route ne peut
produire un 4xx.

### L'index

- **Mémoïsé** : construit une seule fois, gardé en mémoire, rafraîchi à TTL
  (6 h par défaut). **Jamais reconstruit à chaque requête** — mesuré ci-dessous.
- **Traçable** : `index.genere_le` porte la date de génération de
  `chatbot-index.json` côté blog.
- **Robuste aux pannes du blog** : trois sources essayées dans l'ordre — fichier
  local (`BLOG_INDEX_PATH`), réseau (`BLOG_INDEX_URL`), puis cache disque. Aucune
  ne répond → l'index précédent est conservé ; s'il n'y en a pas, la recherche
  répond un état explicite.
- **Hors du chemin critique** : la construction se fait dans un fil
  d'arrière-plan. La conversation ne l'attend jamais.

---

## 2. Le contenu réel du blog, et ce que ça impose

Inspection **avant** toute décision :

- `blog-eperformance/chatbot-index.json` : 6 471 octets, **8 articles publiés**
  (sur 81 dans `_schedule.json`), avec `genere_le`, `source`, `collections[]`,
  `articles[]`. Chaque article : slug, titre, description, collection, date, url,
  tags, image.
- `blog-eperformance/articles/` : 81 dossiers, **1 fichier `index.html`
  chacun** (~46 Ko).
- Les 73 articles non publiés ne doivent **jamais** fuiter (règle du générateur
  d'index du blog, contrat C7). Ils ne sont ni lus ni indexés.

**Constat décisif** : indexer le seul `chatbot-index.json` aurait donné 30 mots
par article — le résumé d'un résumé. La recherche aurait « eu l'air de
fonctionner » sans rien trouver, ce que la consigne interdit explicitement.

Or la page publique de chaque article **publié** contient tout le texte
(**2 050 à 2 372 mots mesurés**). C'est la même source, publique, que celle du
widget. La solution retenue : fiche depuis l'index + **corps depuis la page
publique**, pour les seuls articles présents dans l'index.

**Résultat mesuré** : 8 articles indexés, **8 avec corps complet**, ~18 000 mots
de français réel. C'est suffisant pour une recherche de qualité — vérifié au
banc (§4).

### Limite réelle, dite explicitement

Le corpus publié ne couvre que 8 sujets. Une question légitime dont l'article
n'est pas encore publié (ex. « mes visiteurs ne me contactent pas », dont
l'article `formulaire-contact-efficace` existe mais n'est pas publié) ne trouve
**rien de pertinent** — et c'est le comportement correct : mieux vaut ne rien
injecter que d'injecter un article hors sujet. Le blog publie 5 articles par
jour ; le corpus atteindra 81 articles le 2026-10-03 et ces questions
trouveront leur réponse sans modification de code.

---

## 3. Décision « embeddings » : indisponibles, prouvé par curl

Aucun fournisseur d'embeddings n'est joignable avec les clés du projet.
Commandes exécutées le 2026-09-18 et sorties brutes :

```
=== TEST 1: OpenAI embeddings SANS cle (controle) ===
{"error":{"message":"You didn't provide an API key. [...]","type":"invalid_request_error"}}
HTTP 401

=== TEST 2: DeepSeek /v1/embeddings ===
HTTP 404

=== TEST 3: aiapiflow /v1/embeddings (passerelle Claude du projet) ===
{"error":{"message":"Embeddings API is not supported for this platform","type":"not_found_error"}}
HTTP 404
```

Contrôles de validité des clés, pour distinguer « pas d'endpoint » de « clé
invalide » — les deux clés fonctionnent :

```
=== CONTROLE: la cle DeepSeek est-elle valide ? (chat/completions) ===
HTTP 200
{"id":"be2385c0-...","model":"deepseek-flash","choices":[...]}

=== CONTROLE: la cle passerelle est-elle valide ? ===
HTTP 200
{"id":"msg_SwcUAZ82RVFHGsH0h5xG98e6","model":"claude-sonnet-5",[...]}
```

Configuration de production, relevée par `railway variables` : **aucune
variable `OPENAI_API_KEY`**. En local, `api_keys.openai` vaut `''` dans
`config_ia.json`.

**Décision : BM25F en Python pur, sans dépendance ajoutée.** Ce n'est pas un
pis-aller — c'est le moteur lexical de référence (Lucene, Elasticsearch, SQLite
FTS5), il ne coûte rien par requête, n'ajoute ni clé ni dépendance, et sa
qualité est mesurée. Ajouter des embeddings imposerait une clé OpenAI payante,
un nouvel appel réseau sur le chemin de la conversation, et une reconstruction
complète de l'index à chaque publication.

---

## 4. Mesures

### 4.1 Banc de recherche — `scripts/benchmark_recherche_blog.py`

10 questions formulées **comme un visiteur les écrit** (jamais avec les mots du
titre), 3 requêtes hors sujet, 2 requêtes sans article publié.

```
TOP-1 CORRECT        : 9/9
FAUX POSITIFS        : 0 (attendu : 0)
```

Détail des scores (extrait) :

```
OK   calculer mon cout d'acquisition client
        1. score=  21.562 couverture=1.00  calculer-cac-cote-ivoire  <-- attendu
OK   comment etre visible sur Google a Abidjan
        1. score=  23.140 couverture=1.00  seo-local-abidjan-guide  <-- attendu
OK   repondre aux clients la nuit sans recruter
        1. score=  31.483 couverture=1.00  ia-service-client-nuit  <-- attendu
OK   prix d'un site internet
        1. score=   8.531 couverture=0.67  site-web-professionnel-abidjan-guide  <-- attendu
OK   hors sujet : réservation d'un billet d'avion pour Tokyo → 1 brut(s), 0 pertinent(s)
OK   sans article publié : mes visiteurs ne me contactent pas → 0 pertinent(s)
```

### 4.2 Deux défauts trouvés par la mesure, puis corrigés

La mesure n'a pas servi à confirmer un choix : elle a servi à en corriger deux.

1. **Le titre était écrasé par le corps.** Un BM25 plat classait l'article
   « Site web professionnel à Abidjan » (le bon) **hors du top 3** sur « prix
   d'un site internet », parce que « site » y apparaît 65 fois dans le corps et
   que cette masse écrasait sa présence dans le titre. Corrigé par un **IDF et
   une normalisation par champ** (BM25F) : un titre de 6 mots et un corps de
   2 300 mots ne peuvent pas partager le même compteur.
2. **Faux positif par métaphore.** « Réservation d'un billet d'avion pour
   Tokyo » obtenait une couverture de 0,50 sur l'article du CAC — qui contient
   la métaphore « le prix d'un billet d'avion ». Corrigé par un plancher de
   score (`BLOG_SEARCH_SEUIL_SCORE`), **mesuré** : vrais positifs de 6,29 à 36,2 ;
   faux positifs à 2,46 et 0,26. Le seuil de 4,0 est au milieu des deux
   populations, avec ≈ 1,6× de marge de chaque côté.
3. **Flexions verbales.** « combien coute un client » ne trouvait pas l'article
   du CAC : « coute » ≠ « coût ». Corrigé par des variantes de flexion
   (`calculer`→`calcul`, `coute`→`cout`), produites des deux côtés — documents
   et requête — donc sans jamais faire perdre une correspondance. Ce défaut
   avait été détecté par un test, puis mesuré sur le corpus réel.

### 4.3 Mémoïsation et non-intrusivité (serveur local, curl réel)

```
=== A. premier appel (index froid) ===
real  0m1,987s
index: {"disponible": true, "articles_indexes": 8, "articles_avec_corps": 8,
        "genere_le": "2026-09-18T10:40:16Z", "ttl_s": 21600,
        "source": "index + corps d'articles (8/8)", "derniere_erreur": null}

=== B. deuxieme appel (memoise) ===
real  0m0,042s
```

**47× plus rapide au second appel** : l'index n'est pas reconstruit.

### 4.4 Cas dégradés (curl réel)

```
=== C. requete vide ===
HTTP 200
{"requete":"","resultats":[],"total":0,
 "message":"Requête vide : indiquez des mots-clés (exemple : « calculer mon CAC »)."}

=== D. requete absurde ===
HTTP 200
total: 0 | message: Aucun article du blog ne correspond à cette recherche. [...]

=== E. requete hors sujet (faux positif connu) ===
bruts: 1 | pertinents: 0

=== F. sans parametre q du tout ===
HTTP 200
total: 0 | message: Requête vide : indiquez des mots-clés [...]
```

Aucun de ces cas ne produit 500 ni exception.

### 4.5 La conversation n'est pas cassée (curl réel, LLM appelé)

Question liée à un article publié :

```
HTTP 200 | 3.396954s
REPONSE DE MIA (extrait) :
Bonne question — et c'est rare qu'on me la pose correctement. La plupart des
entrepreneurs calculent leur CAC avec le coût par clic ou le coût par message,
ce qui donne un chiffre flatteur… et faux.
[...]

metadata.blog_sources : [
  {"slug": "calculer-cac-cote-ivoire", "titre": "Calculer son vrai CAC [...]",
   "url": "https://blog.eperformance.pro/articles/calculer-cac-cote-ivoire/"},
  {"slug": "ia-service-client-nuit", ...},
  {"slug": "seo-local-abidjan-guide", ...}]
metadata.agent_used   : absent (conforme)
```

Question **sans** article pertinent :

```
HTTP 200 | 1.386499s
REPONSE (extrait) : Bonjour ! Je n'ai pas d'horaires fixes : je suis disponible
ici à toute heure [...]
blog_sources : absent (conforme : rien de pertinent)
agent_used   : absent (conforme)
```

Mia répond normalement dans les deux cas. `blog_sources` est **additif** :
absent quand la recherche échoue ou ne trouve rien, donc invisible pour le
widget actuel.

### 4.6 Tests

```
python3 -m pytest backend/chatbot/test_tache_6_8_recherche_blog.py -q
32 passed in 0.42s
```

Cas couverts, sans réseau ni base : classement (dont titre > corps, accents,
ordre stable, mots vides), requête vide / absurde / hors sujet, index absent,
**schéma d'index changé**, index précédent conservé, mémoïsation (1 seule
construction pour 5 appels), non-blocage au démarrage à froid, extraction du
texte (menu, pied de page et bandeau de consentement exclus), bloc de prompt
(présent / vide), absorption des erreurs, désactivation par variable
d'environnement.

---

## 5. Ce qui est bloqué, et ce qui revient au propriétaire

**Rien n'est bloqué pour la 6.8.** Le propriétaire n'a aucune action à faire
pour que la recherche fonctionne.

À savoir néanmoins :

1. **Le corpus grandit tout seul.** `_schedule.json` publie 5 articles par jour
   jusqu'au 2026-10-03. L'index se rafraîchit à TTL (6 h) sans intervention.
2. **Le seuil de pertinence devra être revu.** Il est mesuré pour 8 articles.
   L'IDF croît avec le nombre de documents, donc les scores augmenteront : quand
   le corpus dépassera ~40 articles, relever `BLOG_SEARCH_SEUIL_SCORE` et
   relancer le banc. Une quarantaine de jours après la publication complète est
   un bon moment.
3. **Dépendance au dépôt du blog (risque nommé au contrat).** Voir la
   coordination : la recherche dépend du **schéma de `chatbot-index.json`** et
   de la **structure des pages d'articles**. Le premier est validé à la lecture
   (`_valider_index` renvoie un motif clair) ; le second retombe sur titre +
   description si le corps n'est plus extractible, et `index.articles_avec_corps`
   le rend visible. Une entrée de contrat a été ajoutée à la coordination.
4. **Aucun front n'est livré ici.** Le widget n'affiche pas encore ces résultats :
   `GET /api/chatbot/search` est prêt à être consommé par l'onglet Aide.

---

## 6. Variables d'environnement

Toutes facultatives ; les valeurs par défaut conviennent en production.

| Variable | Défaut | Rôle |
|---|---|---|
| `BLOG_INDEX_URL` | `https://blog.eperformance.pro/chatbot-index.json` | source de l'index |
| `BLOG_INDEX_PATH` | vide | index local (développement) |
| `BLOG_INDEX_CACHE` | `backend/chatbot/data/blog_index_cache.json` | repli hors ligne |
| `BLOG_INDEX_TTL_SECONDES` | `21600` (6 h) | durée de validité |
| `BLOG_FETCH_TIMEOUT` | `8` | délai par page d'article |
| `BLOG_FETCH_MAX_ARTICLES` | `40` | pages lues au maximum |
| `BLOG_FETCH_BUDGET` | `25` | budget total de lecture (s) |
| `BLOG_SEARCH_ENABLED` | `1` | `0` désactive complètement la recherche |
| `BLOG_SEARCH_LIMIT` / `_MAX` | `5` / `20` | résultats par défaut / maximum |
| `BLOG_SEARCH_SEUIL_COUVERTURE` | `0.5` | seuil de couverture |
| `BLOG_SEARCH_SEUIL_SCORE` | `4.0` | seuil de score (mesuré) |
| `BLOG_CONTEXT_MAX_ARTICLES` | `3` | articles injectés dans le prompt |
| `BLOG_CONTEXT_EXTRAIT` | `600` | longueur d'un extrait injecté |

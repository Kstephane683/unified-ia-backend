# P3-PUSH — `GET /api/chatbot/push/config` : la clé publique vers le navigateur

| | |
|---|---|
| **Dépôt** | `unified-ia-backend` (branche `main`) |
| **Périmètre** | backend uniquement — le versant widget est dans `eperformance-widget/docs/phase3-push-subscribe/RAPPORT-WIDGET.md` |
| **Objet** | le dernier point d'interface serveur manquant de la chaîne de notifications : servir la clé PUBLIQUE VAPID que `PushManager.subscribe()` exige |
| **Amont** | `docs/phase3-push-subscribe/RAPPORT.md` (§7.3 et §8.1, où ce besoin a été identifié) |
| **État** | livré et vérifié ; commit local, non poussé (voir §8) |

---

## 1. Ce qui est livré

### 1.1 L'endpoint

| Méthode | Chemin exact | Authentification | Écritures |
|---|---|---|---|
| `GET` | `/api/chatbot/push/config` | **aucune** (public) | aucune — ni base, ni réseau, ni fichier |

Réponse quand le push est configuré :

```json
{
  "canal": { "canal": "webpush", "configure": true,
             "raison": "configuré (clés VAPID et bibliothèque présentes)",
             "detail": { "contact": "notifications@exemple.test" } },
  "configure": true,
  "cle_publique": "BGrBuFB_qN9YMlmiAhhuEbxOtCT2zUZ6H7XS5DRN8JKpWmfpsUxDgDh95txi2gGuv2VzXZGcdX77mWvgdWmh3NI",
  "raison": null,
  "forme_cle": "point public P-256 (base64url X962)",
  "message": "clé publique disponible : le widget peut proposer les notifications, après consentement explicite du visiteur"
}
```

Réponse aujourd'hui, **sans aucune clé VAPID** — l'état par défaut de la
production, et la raison d'être du champ `configure` :

```json
{
  "canal": { "canal": "webpush", "configure": false,
             "raison": "non configuré : VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY manquant(s) — le propriétaire n'a pas encore créé les clés VAPID du push navigateur",
             "detail": {} },
  "configure": false,
  "cle_publique": null,
  "raison": "non configuré : VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY manquant(s) — …",
  "forme_cle": "absente",
  "message": "push non configuré côté serveur : le widget ne propose pas les notifications, aucun réglage n'est nécessaire côté visiteur"
}
```

`cle_publique` est en base64url **sans remplissage** : c'est la forme attendue
par `applicationServerKey`. Le widget la convertit en octets
(`Uint8Array`) avant de la passer au navigateur, ce qui évite toute ambiguïté
d'analyse de la chaîne selon les navigateurs.

### 1.2 Fichiers

| Fichier | Nature |
|---|---|
| `backend/chatbot/push_abonnements.py` | `config_cle_publique()`, `ConfigClePublique`, `_est_point_public_p256()`, `_forme_declaree()` — la lecture et le contrôle de la clé |
| `backend/api/routes/chatbot.py` | la route `GET /push/config`, à côté des deux routes de push déjà livrées |
| `backend/chatbot/test_push_config.py` | **nouveau** — 45 tests, dont ceux de la non-fuite de la clé privée |

Aucune variable d'environnement nouvelle n'est introduite : la route ne lit que
`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` et `VAPID_CONTACT`, déjà déclarées (le
garde-fou de parité C12 le vérifie, §7). Aucune table, aucune colonne, aucune
migration : la route ne touche pas la base.

---

## 2. Où cette route se place dans la chaîne

```
  navigateur du visiteur
        │  ① GET /api/chatbot/push/config          ← LIVRÉ ICI (public, lecture seule)
        │     reçoit cle_publique (base64url X962)
        │
        │  ② consentement EXPLICITE du visiteur     ← rien n'est demandé sans lui
        │     puis PushManager.subscribe(cle_publique)
        ▼
  POST /api/chatbot/push/subscribe                  (livré au cycle précédent)
        ▼
  table push_subscriptions                          (livrée au cycle précédent)
        ▼
  POST /api/chatbot/admin/notify → notifications.envoyer("webpush")   (tâche 6.5)
        ▼
  service de push du navigateur (FCM, Mozilla, Apple, WNS)
```

Le cycle précédent s'arrêtait au premier point : `PushManager.subscribe()` a
besoin de la clé publique en `applicationServerKey`, et rien ne la servait. Le
rapport précédent proposait deux issues (§8.1) ; celle retenue est l'endpoint,
parce qu'une clé écrite en dur dans le widget obligerait à republier le widget
le jour d'une rotation de clés.

---

## 3. La clé privée ne sort jamais — la démonstration

C'est le point de sécurité de cette tâche. Il est traité par **quatre barrières
indépendantes**, et chacune est vérifiée par un test qui échoue si elle tombe.

### 3.1 Barrière 1 — la route ne lit pas la clé privée

`config_cle_publique()` ne lit que `VAPID_PUBLIC_KEY`. Elle ne lit pas la clé
privée, ne la contrôle pas, ne la nomme pas : elle ne peut pas transmettre ce
qu'elle ne touche jamais.

Deux tests le vérifient, et ils portent sur autre chose que le comportement
observé :

* `test_seule_la_variable_publique_est_lue` remplace `os.getenv` par un espion
  et vérifie que `VAPID_PRIVATE_KEY` n'est jamais demandé ;
* `test_le_code_de_la_route_ne_nomme_jamais_la_cle_privee` lit la **source** de
  la route et de la fonction de configuration et vérifie que le nom
  `VAPID_PRIVATE_KEY` n'y figure pas — garantie qui tient même pour un chemin
  d'exécution qu'aucun test n'emprunte.

### 3.2 Barrière 2 — la valeur servie doit être un point public P-256 valide

C'est la barrière qui protège contre l'erreur de manipulation, et c'est la plus
importante en pratique. Le script de génération documenté
(`RAPPORT.md` §7.1) imprime **la clé privée en premier**, puis la publique. Un
copier-coller du mauvais bloc met donc la clé privée dans `VAPID_PUBLIC_KEY` —
et un endpoint qui se contenterait de renvoyer `os.getenv("VAPID_PUBLIC_KEY")`
publierait alors un secret sur une route publique, sans qu'aucune alerte ne se
déclenche.

Ici, la valeur n'est servie que si elle se décode réellement comme un point
public P-256 **sur la courbe** (`ec.EllipticCurvePublicKey.from_encoded_point`).
Sont refusés, et ne sont jamais servis :

| Valeur posée dans `VAPID_PUBLIC_KEY` | Servie ? | `forme_cle` renvoyée |
|---|---|---|
| point public P-256 (87 caractères) | **oui** | `point public P-256 (base64url X962)` |
| la même, avec remplissage `=` | **oui** (remplissage retiré) | `point public P-256 (base64url X962)` |
| **clé privée PKCS8** (184 caractères) | **non** | `clé privée PKCS8 (variable inversée ?)` |
| PEM, multiligne ou sur une ligne | **non** | `PEM` |
| graine brute de 32 octets (43 caractères) | **non** | `base64url de longueur inattendue` |
| 65 octets hors courbe | **non** | `base64url de longueur attendue` |
| texte libre | **non** | `base64url de longueur inattendue` |

`cryptography` est importé **paresseusement**, dans la fonction, comme partout
dans ce projet : son absence fait retomber sur le contrôle de forme (65 octets,
premier octet `0x04`), qui suffit déjà à distinguer une clé publique d'une clé
privée. Elle est de toute façon présente en production (dépendance de
`python-jose[cryptography]` et de `pywebpush`).

### 3.3 Barrière 3 — les messages ne recopient jamais la valeur

Le cas d'échec est précisément celui où la valeur peut être un secret. Les
messages de `raison` ne contiennent donc **jamais** la valeur, ni entière, ni
tronquée, ni un préfixe : ils ne portent que des faits de forme (longueur
déclarée, étiquette de forme). `test_la_cle_privee_inversee_est_refusee_pour_tous_les_formats`
et `test_toute_forme_non_publique_est_refusee_sans_etre_recopiee` (9 formes
paramétrées) vérifient la réponse **brute**, pas le JSON analysé.

### 3.4 Barrière 4 — les tests cherchent la fuite dans le corps brut

`TestClePriveeJamaisExposee` (11 tests) cherche la clé privée dans la réponse
brute : la valeur entière, ses préfixes de 16, 24, 32, 48 et 64 caractères, un
découpage glissant par blocs de 24, la chaîne `-----BEGIN`, et le journal. La
contre-épreuve est incluse : `test_la_cle_publique_servie_n_est_pas_utilisable_comme_cle_privee`
vérifie que la valeur servie ne se charge pas comme une clé privée DER.

### 3.5 La preuve par l'exécution (voir §5, points 7, 8 et 10)

Sur un serveur réel, avec de vraies clés, `grep -c` sur le corps de la réponse
donne **0** pour la clé privée, et 0 pour chacun de ses préfixes de 8, 16, 24,
32, 48 et 64 caractères — tandis que la clé publique, témoin, y est trouvée.

---

## 4. Décisions, et pourquoi

### 4.1 `configure` est vrai seulement si le serveur peut AUSSI envoyer

`configure` vaut `etat_canal("webpush").configure ET clé publique exploitable`.
Autrement dit : clés publiques **et** privées présentes, bibliothèque installée,
et clé publique réellement utilisable par un navigateur.

Le widget ne propose la fonctionnalité que sur `configure = vrai`. Une clé
publique présente mais une clé privée absente laisserait le visiteur s'abonner
pour ne jamais rien recevoir : recueillir un consentement qu'on ne peut pas
honorer est pire que ne rien proposer. La réponse reste néanmoins transparente
sur ce cas : `cle_publique` **est** servie (elle est publique par nature, et son
diagnostic est utile) tandis que `configure` est faux et que `raison` nomme la
variable manquante — c'est le test
`test_cle_publique_seule_le_canal_reste_non_configure`.

L'état brut du canal reste disponible séparément dans `canal`, pour que la
distinction entre « le serveur peut envoyer » et « le navigateur peut
s'abonner » ne soit jamais perdue.

### 4.2 L'absence de clé est un ÉTAT, pas une erreur

La route répond **200** dans tous les cas, avec `configure = faux` et une
`raison` en clair. Un 404 ou un 503 obligerait le widget à interpréter un code
d'erreur pour un cas parfaitement nominal — et le widget, lui, doit pouvoir
distinguer « fonctionnalité pas encore disponible » de « le serveur ne répond
pas ». C'est la convention déjà posée par `GET /api/chatbot/search`, qui répond
toujours 200 avec un état (`RAPPORT.md` du cycle précédent, §3.4 pour
l'abonnement).

### 4.3 La route ne touche pas la base

Elle ne déclare pas `Depends(get_db)`. Sa réponse ne dépend que de
l'environnement, donc elle répond même si la base est indisponible — ce qui est
utile puisque le widget la consulte à son démarrage. Deux tests le prouvent :
`test_la_route_ne_touche_pas_la_base` remplace la dépendance de base par une
fonction qui **lève** (si la route la déclarait, l'appel échouerait) et
`test_la_route_n_accepte_aucune_ecriture` vérifie que POST, PUT, DELETE et PATCH
répondent 405.

### 4.4 Pas de limiteur de débit, volontairement

La route ne prend aucun paramètre, n'écrit rien et n'appelle rien : sa réponse
est une constante de l'environnement. Il n'y a rien à abuser, et une entrée de
plus dans `_RATE_LIMITS` serait un réglage sans objet. Vérifié en pratique : 30
appels d'affilée répondent 200 (§5, point 3).

### 4.5 Aucune variable d'environnement nouvelle

Le garde-fou de parité C12 exige que toute variable lue par le code soit
déclarée dans le `.env` de la copie Docker, et le `.env` ne doit pas être
réécrit par cette session. La route n'introduit donc aucune variable : elle
réutilise les trois qui existent.

### 4.6 Le format de clé : le piège documenté au cycle précédent

Le cycle précédent a établi que **le PEM est refusé par la bibliothèque** et que
seul le base64url du DER/PKCS8 est accepté (§7.2 de ce rapport-là). Le cas
symétrique existe côté navigateur : `applicationServerKey` attend la clé
publique en base64url du point X962 non compressé. C'est cette forme, et elle
seule, qui est servie ici — et le contrôle de la barrière 2 vérifie que la
valeur posée est bien de cette forme, ce qui détecte côté serveur l'erreur que
le navigateur signalerait sinon par un `InvalidAccessError` incompréhensible
pour le propriétaire.

---

## 5. Sorties brutes (curl réel, serveur uvicorn local)

Environnement : `/tmp/venv_deploiement/bin/python` (venv réel avec `pywebpush`
installé, celui du cycle précédent), base SQLite isolée dans `/tmp`, clés VAPID
générées pour la démonstration et jamais écrites sur disque. Script :
`/tmp/push_config_demo.sh`. Les clés ne sont jamais imprimées — seules leurs
longueurs le sont.

```
cle publique generee : 87 caracteres
cle privee generee   : 184 caracteres (jamais imprimee, jamais servie)
```

### 5.1 Sans aucune clé VAPID — la route est publique et ne casse rien

```
########## 1. LA ROUTE EST PUBLIQUE : AUCUN EN-TETE D'AUTHENTIFICATION ##########
HTTP/1.1 200 OK
content-type: application/json

{"canal":{"canal":"webpush","configure":false,"raison":"non configuré : VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY manquant(s) — le propriétaire n'a pas encore créé les clés VAPID du push navigateur","detail":{}},"configure":false,"cle_publique":null,"raison":"non configuré : VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY manquant(s) — …","forme_cle":"absente","message":"push non configuré côté serveur : le widget ne propose pas les notifications, aucun réglage n'est nécessaire côté visiteur"}

########## 2. ELLE NE PREND AUCUN PARAMETRE : LA REPONSE NE CHANGE PAS ##########
sans parametre  : HTTP 200
avec parametres: HTTP 200
corps identiques: OUI

########## 3. ELLE N'EST PAS LIMITEE EN DEBIT : 30 APPELS D'AFFILEE ##########
200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200 200

########## 4. AUCUNE ECRITURE : POST / PUT / DELETE REFUSES ##########
POST  : HTTP 405
PUT  : HTTP 405
DELETE  : HTTP 405
PATCH  : HTTP 405

########## 5. L'ABONNEMENT FONCTIONNE MEME SANS CLE (degradation propre) ##########
abonnement cree : True | canal configure : False
```

### 5.2 Avec des clés VAPID réelles — la clé publique est servie

```
########## 6. LA CLE PUBLIQUE EST SERVIE, DANS LA FORME ATTENDUE ##########
HTTP/1.1 200 OK
content-type: application/json

{"canal":{"canal":"webpush","configure":true,"raison":"configuré (clés VAPID et bibliothèque présentes)","detail":{"contact":"notifications@exemple.test"}},"configure":true,"cle_publique":"BGrBuFB_qN9YMlmiAhhuEbxOtCT2zUZ6H7XS5DRN8JKpWmfpsUxDgDh95txi2gGuv2VzXZGcdX77mWvgdWmh3NI","raison":null,"forme_cle":"point public P-256 (base64url X962)","message":"clé publique disponible : le widget peut proposer les notifications, après consentement explicite du visiteur"}
```

### 5.3 La clé privée n'apparaît nulle part — comptage sur le corps brut

```
########## 7. PREUVE : LA CLE PRIVEE N'APPARAIT NULLE PART ##########
occurrences de la cle privee entiere     : 0
occurrences de ses 8 premiers caracteres  : 0
occurrences de ses 16 premiers caracteres  : 0
occurrences de ses 24 premiers caracteres  : 0
occurrences de ses 32 premiers caracteres  : 0
occurrences de ses 48 premiers caracteres  : 0
occurrences de ses 64 premiers caracteres  : 0
occurrences de la cle publique (temoin)  : 1
```

### 5.4 La variable inversée : refusée, et la valeur n'est pas recopiée

```
########## 8. LA CLE PRIVEE INVERSEE DANS LA VARIABLE PUBLIQUE EST REFUSEE ##########
HTTP/1.1 200 OK
content-type: application/json

{"canal":{...,"configure":true,...},"configure":false,"cle_publique":null,"raison":"VAPID_PUBLIC_KEY ne se décode pas comme un point public P-256 valide (184 caractères déclarés ; attendu 87 pour la clé publique, 184 pour la clé privée PKCS8 — une variable inversée est l'erreur la plus fréquente). Aucune clé n'est servie tant que la valeur n'est pas une clé publique.","forme_cle":"clé privée PKCS8 (variable inversée ?)","message":"push non configuré côté serveur : …"}

occurrences de la cle privee dans CETTE reponse : 0
occurrences de ses 24 premiers caracteres      : 0
```

À noter, et c'est le comportement voulu : `canal.configure` reste vrai (le
serveur, lui, saurait envoyer) tandis que `configure` passe à faux — le
navigateur, lui, ne peut pas s'abonner sans clé publique valide. Les deux
notions sont distinctes et le restent dans la réponse.

### 5.5 Un PEM est refusé de la même façon

```
########## 9. UN PEM EST REFUSE DE LA MEME FACON ##########
configure : False | cle servie : None | forme : PEM
```

### 5.6 Ni les journaux du serveur

```
########## 10. JOURNAL DU SERVEUR : AUCUNE CLE PRIVEE TRACEE ##########
occurrences de la cle privee dans le journal : 0
```

---

## 6. Tests

### 6.1 État de la suite, avant et après

| | Avant | Après |
|---|---|---|
| `python3 -m pytest backend/ -q` | **232 passés**, 19 sautés, **2 erreurs** | **277 passés**, 19 sautés, **2 erreurs** |
| dont `backend/chatbot/test_push_config.py` | *(n'existe pas)* | **45 passés** |

Les 2 erreurs sont **préexistantes et inchangées** :
`test_whatsapp_quick.py::test_whatsapp_send_text` et `::test_whatsapp_template`
(erreurs de collecte dues à une fixture absente, sans rapport avec le push). Les
19 tests sautés sont ceux qui exigent `pywebpush`, absent de l'environnement de
test local ; ils étaient déjà sautés avant.

### 6.2 Les six cas exigés, et où ils sont vérifiés

| Cas exigé | Vérifié par |
|---|---|
| abonnement | `test_push_subscribe.py::TestAbonnement` (5 tests) + `test_push_config.py::test_le_widget_peut_s_abonner_avec_la_cle_servie` |
| réabonnement sans doublon | `test_push_subscribe.py::TestReabonnementSansDoublon` |
| désabonnement | `test_push_subscribe.py::TestDesabonnement` |
| corps invalide → 422 | `test_push_subscribe.py::TestCorpsInvalide` (12 corps paramétrés) |
| envoi sans VAPID → « non configuré », sans exception | `test_push_subscribe.py` §5 et `test_tache_6_5_notifications.py` |
| **clé privée jamais exposée par le nouvel endpoint** | `test_push_config.py::TestClePriveeJamaisExposee` (11 tests) |

### 6.3 Ce que les 45 nouveaux tests couvrent

| Classe | Objet |
|---|---|
| `TestLaRoute` (6) | publique sans jeton, ne touche pas la base (dépendance de base remplacée par une fonction qui lève), aucune écriture (405 sur 4 méthodes), réponse constante, aucun paramètre, aucun jeton ni endpoint dans la réponse |
| `TestSansCle` (6) | 200 sans clé, `configure` faux, aucune clé servie, `raison` explicite nommant la variable, `message` de dégradation, **aucune exception** sans aucune variable |
| `TestAvecCle` (8) | `configure` vrai, la clé servie est exactement celle de l'environnement, elle se décode en point P-256 valide, sans remplissage, remplissage toléré, espaces ignorés, cas « publique seule » |
| `TestClePriveeJamaisExposee` (11) | §3 ci-dessus |
| `TestContratWidget` (4) | champs stables, `configure` toujours booléen, réponse JSON, enchaînement config → subscribe |

### 6.4 Deux points de méthode, pour qu'ils ne surprennent pas

* `etat_canal("webpush")` refuse de déclarer le canal configuré si `pywebpush`
  est absent. L'environnement de test local ne l'installe pas. Les tests qui
  portent sur le cas configuré rendent donc cet état **déterministe** avec une
  fixture (`bibliotheque_presente` / `bibliotheque_absente`) qui remplace la
  seule recherche de spécification, sans installer ni désinstaller quoi que ce
  soit. Installer la bibliothèque aurait changé la ligne de base (19 tests
  sautés seraient devenus exécutés) et rendu la comparaison avant/après
  trompeuse.
* Les clés des tests sont générées à la volée et ne sont jamais écrites sur
  disque ni versionnées.
* Le garde-fou `scripts/verifier-secrets.py` a **bloqué le premier push** : il
  signale tout en-tête PEM privé en clair, et un test cite forcément cet
  en-tête (`-----BEGIN … PRIVATE KEY-----`) pour vérifier qu'un PEM est refusé.
  Le test ne contient aucune clé, mais la règle est ligne à ligne. La correction
  n'a pas touché le garde-fou : l'en-tête du test porte le marqueur de gabarit
  du projet (`EXAMPLE`), mécanisme déjà prévu par le script pour les valeurs qui
  ne sont pas des secrets. Un commentaire dans le test explique pourquoi ce
  marqueur ne doit pas être retiré. Le garde-fou reste donc actif sur ce
  fichier — il l'a d'ailleurs rescanné après correction (129 fichiers), et il a
  signalé une seconde fois la même chaîne citée dans ce rapport, corrigée ici.

---

## 7. Parité avec la copie Docker (contrat C12)

Trois fichiers ont divergé, exactement ceux touchés par cette tâche — aucun
fichier de code n'a changé côté Docker sans que cette session l'ait fait :

```
[parite] ECHEC — ecart entre le backend Railway et la copie Docker :
[parite]   MANQUANT dans Docker      : backend/chatbot/test_push_config.py
[parite]   DIVERGENT                : backend/api/routes/chatbot.py
[parite]   DIVERGENT                : backend/chatbot/push_abonnements.py
```

Après réplication (copie des seuls fichiers concernés ; `Dockerfile`,
`.dockerignore`, `docker-compose.yml` et `.env` **non touchés**) :

```
$ python3 scripts/verifier-parite-docker.py
[parite] PASS — arborescences identiques (133 fichiers, md5) · 54 variables lues par le code, toutes declarees
[parite] PASS — Dockerfile, .dockerignore, docker-compose.yml, .env presents
$ echo $?
0
```

Les 54 variables lues par le code sont inchangées : cette tâche n'en ajoute
aucune.

---

## 8. Ce qui est bloqué, et ce qui revient au propriétaire

### 8.1 Rien n'est bloqué côté backend

L'endpoint ne dépend d'aucune décision extérieure : il fonctionne dès à présent,
en répondant « non configuré ». Le seul élément qui reste au propriétaire est la
création des clés VAPID (§7.1 du rapport précédent), et elle n'est pas
nécessaire pour que le widget se comporte correctement : sans clé, le widget ne
propose simplement pas la fonctionnalité.

### 8.2 Ce qui revient au propriétaire

1. **Créer les clés VAPID** et les poser dans les variables du service Railway
   (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CONTACT`) — commande et
   piège de format documentés au §7.1 et §7.2 du rapport précédent.
2. **Vérifier la variable publique** : le jour où les clés sont posées,
   `GET /api/chatbot/push/config` doit répondre `"configure": true` et une
   `cle_publique` de 87 caractères. Si la réponse dit
   `clé privée PKCS8 (variable inversée ?)`, les deux lignes ont été
   interchangées : la clé privée est dans la variable publique et doit être
   remplacée immédiatement. L'endpoint le dit sans jamais publier la valeur.
3. **Décider du push** : le déploiement Railway se déclenche à chaque push sur
   `main`, c'est une décision du propriétaire, pas de cette session.

### 8.3 Limites connues, assumées

* `configure` dit « le serveur a tout ce qu'il faut », pas « le fournisseur de
  push répondra » : c'est la convention de `etat_canal`, qui ne fait aucun appel
  réseau pour rester utilisable en diagnostic.
* La route ne dit pas si un abonnement donné existe : elle ne prend aucun
  paramètre et ne lit pas la base. Le comptage des abonnements reste dans la
  route d'administration de la tâche 6.5.
* `cryptography` absent ferait retomber sur le contrôle de forme (65 octets,
  premier octet `0x04`), plus faible que la vérification sur la courbe mais
  suffisant à distinguer une clé publique d'une clé privée. Cette situation
  n'existe pas en production, où la bibliothèque est une dépendance de
  `python-jose[cryptography]` et de `pywebpush`.

---

## 9. Vérifications de sortie

```
$ bash scripts/pre-push-smoke-test.sh
[smoke-test] Import du module backend...
[startup] init_db OK — tables vérifiées/créées
[smoke-test] OK — application FastAPI importable
[smoke-test] Compilation py_compile de tous les fichiers modifiés...
[smoke-test] Recherche de secrets dans les fichiers suivis...
[secrets] PASS — aucun secret detecte (127 fichier(s))
[smoke-test] Parité avec la copie Docker (contrat C12)...
[parite] PASS — arborescences identiques (133 fichiers, md5) · 54 variables lues par le code, toutes declarees
[parite] PASS — Dockerfile, .dockerignore, docker-compose.yml, .env presents
[smoke-test] PASS — push autorisé
```

```
$ python3 -m pytest backend/chatbot/test_push_config.py -q
45 passed

$ python3 -m pytest backend/ -q
277 passed, 19 skipped, 2 errors
```

### Commit

Un seul commit, un seul sujet :

```
feat(push): GET /api/chatbot/push/config — la clé publique VAPID, jamais la privée
```

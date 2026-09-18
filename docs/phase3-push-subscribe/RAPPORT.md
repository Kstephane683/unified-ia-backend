# P3-PUSH — Abonnement au push navigateur : les endpoints serveur

| | |
|---|---|
| **Dépôt** | `unified-ia-backend` (branche `main`) |
| **Périmètre** | backend uniquement — aucun autre dépôt touché |
| **Objet** | le maillon manquant entre la tâche 6.5 (qui sait envoyer un Web Push) et la tâche 6.4 (dont le service worker sait en recevoir un) |
| **État** | livré et vérifié ; **non poussé**, voir §8 |

---

## 1. Ce qui est livré

### 1.1 Endpoints

| Méthode | Chemin exact | Authentification | Rôle |
|---|---|---|---|
| `POST` | `/api/chatbot/push/subscribe` | **aucune** (public) | enregistrer ou mettre à jour l'abonnement d'un navigateur |
| `DELETE` | `/api/chatbot/push/unsubscribe` | **aucune** (public) | désabonner, par endpoint exact |
| `GET` | `/api/chatbot/admin/push/subscriptions` | jeton admin | lister les abonnements (ajout hors liste demandée, justifié en §3.9) |

Corps accepté par `POST /api/chatbot/push/subscribe` — celui de la proposition
déposée au journal de coordination par le Bloc B de la tâche 6.4 :

```json
{
  "endpoint": "https://fcm.googleapis.com/fcm/send/<jeton>",
  "keys": { "p256dh": "<87 caractères base64url>", "auth": "<22 caractères base64url>" },
  "conversation_id": "conv-0001",
  "site_id": "eperformance_vitrine"
}
```

`conversation_id` et `site_id` sont facultatifs (`site_id` vaut
`eperformance_vitrine` par défaut) : un visiteur peut s'abonner avant qu'une
conversation existe, et l'abonnement ne doit pas dépendre d'un échange.

### 1.2 Table `push_subscriptions`

Colonnes : `endpoint` (unique), `keys_p256dh`, `keys_auth`, `conversation_id`,
`site_id`, `date_creation`, `date_derniere_utilisation`, `user_agent`, `actif`.

Aucune clé étrangère, aucune colonne JSON, aucune donnée personnelle.
Créée par `init_db()` au démarrage, comme les autres tables.

### 1.3 Fichiers

| Fichier | Nature |
|---|---|
| `backend/chatbot/models.py` | `PushSubscription` (table `push_subscriptions`) + un index composite |
| `backend/chatbot/push_abonnements.py` | **nouveau** — validation des endpoints, enregistrement, désabonnement, énumération des deux sources, horodatage d'utilisation |
| `backend/api/routes/chatbot.py` | les deux routes publiques et leurs schémas de validation |
| `backend/api/routes/admin_chatbot.py` | l'envoi lit désormais les deux tables ; horodatage ; compteurs ; listage admin |
| `backend/api/app.py` | deux entrées de limiteur de débit |
| `requirements.txt` | `pywebpush==2.5.0` |
| `backend/chatbot/test_push_subscribe.py` | **nouveau** — 63 tests |

`backend/chatbot/notifications.py` (tâche 6.5) **n'est pas modifié** : l'envoi
reçoit une liste d'objets qui exposent `.endpoint`, `.cle_p256dh` et
`.cle_auth`, exactement ce qu'il consommait déjà.

---

## 2. La chaîne, maintenant complète

```
  navigateur du visiteur
        │  PushManager.subscribe()            (fait par la session widget, hors périmètre)
        ▼
  POST /api/chatbot/push/subscribe            ← LIVRÉ ICI (public, sans jeton)
        │  endpoint unique : réabonnement = mise à jour, jamais de doublon
        ▼
  table push_subscriptions                    ← LIVRÉE ICI
        │  + table chatbot_push_subscriptions (créée par la tâche 6.5)
        │  lues ensemble, dédoublonnées sur l'endpoint
        ▼
  POST /api/chatbot/admin/notify → notifications.envoyer("webpush")   (tâche 6.5, inchangée)
        │  paresseux : pywebpush importé à l'usage, jamais au démarrage
        ▼
  service de push du navigateur (FCM, Mozilla, Apple, WNS)
        ▼
  service worker du widget : événement `push` + ouverture au clic   (tâche 6.4)
```

`DELETE /api/chatbot/push/unsubscribe` ferme la boucle : la ligne passe à
`actif = faux` et n'est plus transmise à l'envoi.

---

## 3. Décisions, et pourquoi

### 3.1 Une table de plus, plutôt qu'une colonne de plus

`init_db()` appelle `Base.metadata.create_all()`. Cette fonction crée les tables
ABSENTES et **n'ajoute jamais une colonne à une table existante**. Ajouter
`conversation_id` ou `date_derniere_utilisation` au modèle de
`chatbot_push_subscriptions` aurait donc annoncé à l'ORM, en production, des
colonnes que la base ne possède pas — et toute lecture de la table serait
tombée en erreur. C'est exactement le genre de cas où « ne rien casser »
impose une table nouvelle. Les deux tables coexistent : les abonnements créés
par la route d'administration de la tâche 6.5 restent valides et continuent de
recevoir les notifications.

### 3.2 L'endpoint exact tient lieu d'autorisation, au désabonnement

L'`endpoint` est exigé à l'identique : il n'est connu que du navigateur
concerné. Personne ne peut donc désabonner le navigateur d'un autre — la
question ne se règle pas par un contrôle d'accès, qui est impossible pour un
visiteur sans compte, mais par la nature de ce qu'il faut connaître pour agir.
`conversation_id`, s'il est fourni, est une condition **supplémentaire**.

### 3.3 Liste blanche des services de push

L'endpoint est fourni par le navigateur d'un inconnu, et c'est à cette adresse
que le serveur enverra une requête HTTP le jour de la notification. Accepter
n'importe quelle URL ferait de l'abonnement public un relais vers le réseau
interne (le cas classique étant l'adresse de métadonnées de l'hébergeur). Le
contrôle porte donc sur le domaine, pas seulement sur le schéma `https` :

* `fcm.googleapis.com` — Chrome, Chromium, Edge, Brave, Opera, Samsung ;
* `push.services.mozilla.com` — Firefox ;
* `push.apple.com` — Safari ;
* `notify.windows.com` — Edge sous Windows.

Un fournisseur supplémentaire s'ajoute par `PUSH_ENDPOINTS_AUTORISES`
(domaines séparés par des virgules), sans toucher au code. Aucun joker `*`
n'est accepté : une variable d'environnement ne doit pas pouvoir désactiver un
contrôle de sécurité en une valeur. La comparaison exige une frontière sur un
point — `evilfcm.googleapis.com` et `fcm.googleapis.com.attaquant.test` sont
refusés, et quatre tests le vérifient.

### 3.4 La route d'abonnement répond 200 même sans clés VAPID

L'abonnement ne dépend pas des clés : il dépend du navigateur. Refuser
l'enregistrement tant que le propriétaire n'a pas créé ses clés ferait perdre
tous les consentements déjà donnés par les visiteurs, et le jour où les clés
arrivent, il n'y aurait personne à notifier. La réponse porte donc l'état du
canal (`canal.configure`, `canal.raison`) pour que l'absence de configuration
soit **visible**, et non silencieuse.

### 3.5 Le désabonnement désactive, il ne supprime pas

La ligne conserve sa date de création, son site et sa conversation : c'est ce
qui permet de constater après coup qu'un navigateur s'était abonné puis qu'il
s'est retiré. Un réabonnement du même endpoint remet simplement `actif` à vrai.

### 3.6 Les deux pièges connus du projet

* **Colonnes JSON.** Sur une colonne JSON, SQLAlchemy compare `new == old` au
  flush et n'écrit pas une mutation en place sans `flag_modified()`. La table
  `push_subscriptions` n'a **aucune** colonne JSON : le problème est supprimé
  au lieu d'être contourné, et un test vérifie l'absence de colonne de ce type.
  Le motif `set_metadata` de `admin_chatbot` reste le seul écrivain JSON, et il
  n'est pas touché.
* **`= ANY(:liste)` sous psycopg2.** Aucune requête SQL brute n'est écrite.
  L'énumération se fait par un simple filtre `actif IS TRUE`, et l'horodatage
  d'utilisation porte sur des objets ORM déjà tenus en main — pas d'`IN (...)` à
  construire, pas d'`ANY (...)` à lier.

### 3.7 Limiteur de débit

Les deux routes publiques écrivent (ou tentent d'écrire) sans jeton : elles sont
donc bornées comme les autres routes publiques de l'application
(`/api/chatbot/push/subscribe` 20/minute, `/api/chatbot/push/unsubscribe`
30/minute, par IP). Un navigateur s'abonne une fois ; la limite ne le gêne pas.

### 3.8 `date_derniere_utilisation`, ce qu'elle dit exactement

Elle est écrite après un envoi **qui a abouti au moins une fois**, sur les
abonnements présentés à cet envoi. La tâche 6.5 rend un total, pas le détail par
abonnement : la date marque donc les abonnements tentés lors d'un envoi réussi,
et non ceux dont la livraison est prouvée individuellement. C'est suffisant
pour repérer un abonnement qui ne sert plus, et c'est exact — la nuance est
écrite dans le module.

### 3.9 Le listage admin (hors liste demandée)

`GET /api/chatbot/admin/push/subscriptions` a été ajouté parce que les
compteurs seuls ne permettent pas de trancher la question qui décide de tout :
« les abonnements des visiteurs arrivent-ils, et lesquels reçoivent encore ? ».
Il est réservé aux administrateurs, ne renvoie **jamais** les clés de
chiffrement, et ne renvoie les endpoints que tronqués. Aucune autre route n'a
été ajoutée.

---

## 4. Preuve que `pywebpush` s'installe réellement

La consigne était explicite : une ligne ajoutée qui casse le déploiement serait
pire que pas de ligne du tout. L'installation a donc été faite pour de bon, dans
un environnement **vierge**, avec le `requirements.txt` du projet.

```
$ python3 -m venv /tmp/venv_deploiement
$ /tmp/venv_deploiement/bin/python -m pip install -r requirements.txt
Building wheels for collected packages: http-ece
  Created wheel for http-ece: filename=http_ece-1.2.1-py2.py3-none-any.whl size=4851 sha256=cb6e3115f671c0020233a980e332fda5f1219f61c6e8477def728b3796c45ced
Successfully installed Mako-1.4.1 MarkupSafe-3.0.3 aiohappyeyeballs-2.7.1 aiohttp-3.14.3 aiosignal-1.4.0 alembic-1.12.1 annotated-types-0.8.0 anyio-3.7.1 attrs-26.1.0 bcrypt-4.0.1 certifi-2026.7.22 cffi-2.1.1 charset-normalizer-3.5.1 click-8.5.0 cryptography-50.0.1 dnspython-2.8.0 ecdsa-0.19.2 email-validator-2.1.0 fastapi-0.104.1 frozenlist-1.8.0 greenlet-3.5.6 h11-0.16.0 http-ece-1.2.1 httpcore-1.0.9 httptools-0.8.0 httpx-0.25.2 idna-3.20 multidict-6.9.0 passlib-1.7.4 pillow-10.1.0 propcache-0.5.4 psycopg2-binary-2.9.9 py-vapid-1.9.4 pyasn1-0.6.4 pycparser-3.0 pydantic-2.5.0 pydantic-core-2.14.1 pydantic-settings-2.1.0 python-dotenv-1.0.0 python-jose-3.3.0 python-multipart-0.0.6 pywebpush-2.5.0 pyyaml-6.0.3 requests-2.31.0 rsa-4.9.1 six-1.17.0 sniffio-1.3.1 sqlalchemy-2.0.23 starlette-0.27.0 typing-extensions-4.16.0 urllib3-2.8.0 uvicorn-0.24.0 uvloop-0.22.1 watchfiles-1.2.0 websockets-17.1 yarl-1.25.1
=== EXIT=0 ===
pywebpush importable, version ?
cryptography 50.0.1
```

### 4.1 Ce que la nouvelle ligne change — et ce qu'elle ne change pas

Résolution complète comparée, `requirements.txt` avec et sans `pywebpush` :

| | sans `pywebpush` | avec `pywebpush==2.5.0` |
|---|---|---|
| paquets installés | 45 | 56 |
| `cryptography` retenu | **50.0.1** | **50.0.1** |
| paquets ajoutés | — | `pywebpush`, `py-vapid`, `http-ece`, `aiohttp` et ses 7 dépendances |

Le point important : `cryptography` est retenu à la **même** version dans les
deux cas. La ligne ajoutée n'introduit donc aucun changement de version dans
les dépendances existantes ; elle ajoute des paquets, elle n'en remplace aucun.
`aiohttp` vient avec `pywebpush` 2.x (support asynchrone de la bibliothèque), il
n'est pas utilisé par le code du projet.

Versions et compatibilité : `pywebpush==2.5.0` exige Python >= 3.10
(`runtime.txt` du projet : `python-3.11`). Sa fonction `webpush()` accepte
exactement les paramètres que la tâche 6.5 lui passe déjà
(`subscription_info`, `data`, `vapid_private_key`, `vapid_claims`, `timeout`) :
vérifié en lisant la signature de la version installée, puis en l'appelant
réellement (§6.3).

### 4.2 Import paresseux, vérifié

`pywebpush` n'est pas importé au chargement du module : un test existant
(`test_pywebpush_n_est_pas_importe_au_chargement`) vérifie que
`sys.modules` ne le contient pas après import de `notifications`. Le test
d'envoi réel s'exécute dans un **sous-processus** précisément pour ne pas
salir ce contrôle.

---

## 5. Les `curl` exécutés, sorties brutes

Le script qui a produit ces sorties est reproduit **en entier** au §5.2 : il
n'est pas versionné (c'est un outil de vérification, pas un livrable), mais il
est assez court pour être rejoué tel quel.

Serveur `uvicorn` local sur `127.0.0.1:8099`, base **SQLite isolée** dans
`/tmp` (aucune donnée de production n'est lue ni écrite), aucune variable de
notification dans un premier temps, puis deux clés VAPID **factices** dans un
second temps pour montrer le changement d'état du canal. Les clés VAPID
factices ne peuvent pas produire d'envoi : l'étape 13 échoue volontairement sur
la désérialisation de la clé, avant tout appel réseau.

### 5.1 Sortie brute

```text
############ SERVEUR 1 : AUCUNE VARIABLE DE NOTIFICATION (monde réel) ############

########## 1. ABONNEMENT VALIDE (aucun jeton, visiteur non authentifié) ##########
HTTP/1.1 200 OK
date: Fri, 18 Sep 2026 20:08:13 GMT
server: uvicorn
content-length: 671
content-type: application/json

{"abonnement":{"id":1,"endpoint_tronque":"https://fcm.googleapis.com/fcm/send/exemple-de-j…","conversation_id":"conv-demo-1","site_id":"eperformance_vitrine","actif":true,"date_creation":"2026-09-18T20:08:13","date_derniere_utilisation":null,"user_agent":"DemonstrationCurl/1.0","cree":true},"canal":{"canal":"webpush","configure":false,"raison":"non configuré : VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY manquant(s) — le propriétaire n'a pas encore créé les clés VAPID du push navigateur","detail":{}},"message":"abonnement enregistré ; les notifications partiront dès que le propriétaire aura créé les clés VAPID — rien d'autre n'est requis côté visiteur"}
########## 2. CORPS INVALIDE : ENDPOINT VIDE ##########
HTTP/1.1 422 Unprocessable Entity
date: Fri, 18 Sep 2026 20:08:13 GMT
server: uvicorn
content-length: 184
content-type: application/json

{"detail":[{"type":"value_error","loc":["body","endpoint"],"msg":"Value error, endpoint manquant","input":"","ctx":{"error":{}},"url":"https://errors.pydantic.dev/2.5/v/value_error"}]}
########## 3. CORPS INVALIDE : CLES MANQUANTES ##########
HTTP/1.1 422 Unprocessable Entity
date: Fri, 18 Sep 2026 20:08:13 GMT
server: uvicorn
content-length: 211
content-type: application/json

{"detail":[{"type":"missing","loc":["body","keys"],"msg":"Field required","input":{"endpoint":"https://fcm.googleapis.com/fcm/send/exemple-de-jeton-non-reel"},"url":"https://errors.pydantic.dev/2.5/v/missing"}]}
########## 3bis. CORPS INVALIDE : DOMAINE NON AUTORISE ##########
HTTP/1.1 422 Unprocessable Entity
date: Fri, 18 Sep 2026 20:08:13 GMT
server: uvicorn
content-length: 455
content-type: application/json

{"detail":[{"type":"value_error","loc":["body","endpoint"],"msg":"Value error, endpoint : domaine non autorisé « exemple.test » — les services de push connus sont fcm.googleapis.com, push.services.mozilla.com, push.apple.com, notify.windows.com. Un autre fournisseur s'ajoute par la variable d'environnement PUSH_ENDPOINTS_AUTORISES.","input":"https://exemple.test/push/abc","ctx":{"error":{}},"url":"https://errors.pydantic.dev/2.5/v/value_error"}]}
########## 4. REABONNEMENT DU MEME ENDPOINT (cles differentes) ##########
HTTP/1.1 200 OK
date: Fri, 18 Sep 2026 20:08:13 GMT
server: uvicorn
content-length: 661
content-type: application/json

{"abonnement":{"id":1,"endpoint_tronque":"https://fcm.googleapis.com/fcm/send/exemple-de-j…","conversation_id":"conv-demo-1","site_id":"eperformance_vitrine","actif":true,"date_creation":"2026-09-18T20:08:13","date_derniere_utilisation":null,"user_agent":"curl/8.5.0","cree":false},"canal":{"canal":"webpush","configure":false,"raison":"non configuré : VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY manquant(s) — le propriétaire n'a pas encore créé les clés VAPID du push navigateur","detail":{}},"message":"abonnement enregistré ; les notifications partiront dès que le propriétaire aura créé les clés VAPID — rien d'autre n'est requis côté visiteur"}
########## 4bis. SECOND NAVIGATEUR (endpoint different) ##########
HTTP 200

########## 5. ETAT EN BASE (lecture directe, sans ORM) ##########
2 ligne(s) dans push_subscriptions :
  id=1 endpoint=https://fcm.googleapis.com/fcm/send/exemple-de… conversation=conv-demo-1 site=eperformance_vitrine actif=1 p256dh=DDDDDDDDDDDD… creation=2026-09-18 20:08:13 derniere_utilisation=None ua=curl/8.5.0
  id=2 endpoint=https://updates.push.services.mozilla.com/wpus… conversation=None site=eperformance_vitrine actif=1 p256dh=FFFFFFFFFFFF… creation=2026-09-18 20:08:13 derniere_utilisation=None ua=curl/8.5.0
total lignes pour l'endpoint 1 : 1

########## 6. ENVOI PUSH SANS VAPID CONFIGURE (admin) ##########
HTTP/1.1 503 Service Unavailable
date: Fri, 18 Sep 2026 20:08:15 GMT
server: uvicorn
content-length: 952
content-type: application/json

{"resultat":{"canal":"webpush","succes":false,"statut":"non_configure","destinataire":"","messages_envoyes":0,"identifiant_fournisseur":null,"code_erreur":null,"erreur":"non configuré : VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY manquant(s) — le propriétaire n'a pas encore créé les clés VAPID du push navigateur","duree_ms":0},"site_id":null,"canaux":[{"canal":"telegram","configure":false,"raison":"non configuré : TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID manquant(s)","detail":{}},{"canal":"email","configure":false,"raison":"non configuré : BREVO_API_KEY, BREVO_SENDER_EMAIL manquant(s)","detail":{}},{"canal":"webpush","configure":false,"raison":"non configuré : VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY manquant(s) — le propriétaire n'a pas encore créé les clés VAPID du push navigateur","detail":{}},{"canal":"whatsapp","configure":false,"raison":"non configuré : WHATSAPP_ACCESS_TOKEN ou WHATSAPP_PHONE_NUMBER_ID manquant","detail":{}}]}
########## 7. DESABONNEMENT (endpoint exact) ##########
HTTP/1.1 200 OK
date: Fri, 18 Sep 2026 20:08:15 GMT
server: uvicorn
content-length: 215
content-type: application/json

{"endpoint_tronque":"https://fcm.googleapis.com/fcm/send/exemple-de-j…","abonnements_desactives":1,"detail":{"public":1,"admin":0},"message":"abonnement désactivé — la ligne est conservée pour le diagnostic"}
########## 8. ETAT EN BASE APRES DESABONNEMENT ##########
  id=1 endpoint=https://fcm.googleapis.com/fcm/send/exemple-de… actif=0
  id=2 endpoint=https://updates.push.services.mozilla.com/wpus… actif=1
la ligne desabonnee est CONSERVEE (actif = 0), elle n'est pas supprimee

########## 9. DESABONNEMENT REPETE (idempotence) ##########
HTTP/1.1 200 OK
date: Fri, 18 Sep 2026 20:08:16 GMT
server: uvicorn
content-length: 198
content-type: application/json

{"endpoint_tronque":"https://fcm.googleapis.com/fcm/send/exemple-de-j…","abonnements_desactives":0,"detail":{"public":0,"admin":0},"message":"aucun abonnement actif ne correspond à cet endpoint"}
########## 10. DESABONNEMENT D'UN ENDPOINT INCONNU ##########
HTTP/1.1 200 OK
date: Fri, 18 Sep 2026 20:08:16 GMT
server: uvicorn
content-length: 192
content-type: application/json

{"endpoint_tronque":"https://fcm.googleapis.com/fcm/send/jamais-vu","abonnements_desactives":0,"detail":{"public":0,"admin":0},"message":"aucun abonnement actif ne correspond à cet endpoint"}
########## 11. LISTAGE ADMIN DES ABONNEMENTS (les deux sources) ##########
HTTP/1.1 200 OK
date: Fri, 18 Sep 2026 20:08:16 GMT
server: uvicorn
content-length: 643
content-type: application/json

{"abonnements":[{"id":2,"endpoint_tronque":"https://updates.push.services.mozilla.com/wpush/…","conversation_id":null,"site_id":"eperformance_vitrine","actif":true,"date_creation":"2026-09-18T20:08:13","date_derniere_utilisation":null,"user_agent":"curl/8.5.0","source":"widget"},{"id":1,"endpoint_tronque":"https://fcm.googleapis.com/fcm/send/exemple-de-j…","conversation_id":"conv-demo-1","site_id":"eperformance_vitrine","actif":false,"date_creation":"2026-09-18T20:08:13","date_derniere_utilisation":null,"user_agent":"curl/8.5.0","source":"widget"}],"resume":{"widget":{"total":2,"actifs":1},"admin":{"total":0,"actifs":0}},"total":2}
########## 12. TRACE DES NOTIFICATIONS (canaux + tentatives) ##########
HTTP/1.1 200 OK
date: Fri, 18 Sep 2026 20:08:16 GMT
server: uvicorn
content-length: 1242
content-type: application/json

{"canaux":[{"canal":"telegram","configure":false,"raison":"non configuré : TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID manquant(s)","detail":{}},{"canal":"email","configure":false,"raison":"non configuré : BREVO_API_KEY, BREVO_SENDER_EMAIL manquant(s)","detail":{}},{"canal":"webpush","configure":false,"raison":"non configuré : VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY manquant(s) — le propriétaire n'a pas encore créé les clés VAPID du push navigateur","detail":{}},{"canal":"whatsapp","configure":false,"raison":"non configuré : WHATSAPP_ACCESS_TOKEN ou WHATSAPP_PHONE_NUMBER_ID manquant","detail":{}}],"notifications":[{"id":1,"canal":"webpush","statut":"non_configure","succes":false,"destinataire":"","sujet":"Demonstration","corps":"Verification de la degradation propre","code_erreur":null,"erreur":"non configuré : VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY manquant(s) — le propriétaire n'a pas encore créé les clés VAPID du push navigateur","identifiant_fournisseur":null,"auteur":"demo@local.test","duree_ms":0,"created_at":"2026-09-18T20:08:16","envoye_le":"2026-09-18T20:08:16.063222"}],"total":1,"resume":{"envoye":0,"echec":0,"non_configure":1},"abonnements_push_actifs":1,"abonnements_push_detail":{"widget":1,"admin":0}}
############ SERVEUR 2 : CLES VAPID FACTICES PRESENTES ############

########## 13. ETAT DU CANAL AVEC CLES PRESENTES (envoi sans abonnement actif) ##########
HTTP/1.1 502 Bad Gateway
date: Fri, 18 Sep 2026 20:08:26 GMT
server: uvicorn
content-length: 957
content-type: application/json

{"resultat":{"canal":"webpush","succes":false,"statut":"echec","destinataire":"","messages_envoyes":0,"identifiant_fournisseur":null,"code_erreur":null,"erreur":"ValueError: Could not deserialize key data. The data may be in an incorrect format, it may be encrypted with an unsupported algorithm, or it may be an unsupported key type (e.g. EC curves with explici […]","duree_ms":322},"site_id":null,"canaux":[{"canal":"telegram","configure":false,"raison":"non configuré : TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID manquant(s)","detail":{}},{"canal":"email","configure":false,"raison":"non configuré : BREVO_API_KEY, BREVO_SENDER_EMAIL manquant(s)","detail":{}},{"canal":"webpush","configure":true,"raison":"configuré (clés VAPID et bibliothèque présentes)","detail":{"contact":"notifications@exemple.test"}},{"canal":"whatsapp","configure":false,"raison":"non configuré : WHATSAPP_ACCESS_TOKEN ou WHATSAPP_PHONE_NUMBER_ID manquant","detail":{}}]}
########## 14. ABONNEMENT TOUJOURS ACCEPTE AVEC LES CLES EN PLACE ##########
HTTP 200

############ FIN ############
```

### 5.2 Script exécuté

```bash
#!/bin/bash
# Démonstration réelle des endpoints de push (P3-PUSH) — sorties brutes.
# Serveur uvicorn local, base SQLite isolée dans /tmp (aucune donnée de production).
set -u

PY=/tmp/venv_deploiement/bin/python
RACINE=/home/ballo/OX6A/unified-ia-backend
DEMO=/tmp/push_demo
PORT=8099
BASE="http://127.0.0.1:$PORT"
ENDPOINT="https://fcm.googleapis.com/fcm/send/exemple-de-jeton-non-reel"
ENDPOINT2="https://updates.push.services.mozilla.com/wpush/v2/exemple-jeton"

rm -rf "$DEMO"
mkdir -p "$DEMO"

demarrer_serveur() {
  cd "$RACINE"
  DATABASE_URL="sqlite:///$DEMO/push_demo.db" ENV=development DEBUG=True \
    "$PY" -m uvicorn backend.api.app:app --host 127.0.0.1 --port "$PORT" \
    > "$DEMO/serveur.log" 2>&1 &
  SERVEUR=$!
  for _ in $(seq 1 60); do
    if curl -s -o /dev/null "$BASE/health"; then return 0; fi
    sleep 0.5
  done
  echo "SERVEUR NON DEMARRE"; tail -20 "$DEMO/serveur.log"; return 1
}

arreter_serveur() {
  kill "$SERVEUR" 2>/dev/null
  wait "$SERVEUR" 2>/dev/null
}

echo "############ SERVEUR 1 : AUCUNE VARIABLE DE NOTIFICATION (monde réel) ############"
demarrer_serveur || exit 1

echo
echo "########## 1. ABONNEMENT VALIDE (aucun jeton, visiteur non authentifié) ##########"
curl -s -i -X POST "$BASE/api/chatbot/push/subscribe" \
  -H 'Content-Type: application/json' \
  -H 'User-Agent: DemonstrationCurl/1.0' \
  -d "{\"endpoint\":\"$ENDPOINT\",\"keys\":{\"p256dh\":\"$(printf 'B%.0s' $(seq 1 87))\",\"auth\":\"$(printf 'C%.0s' $(seq 1 22))\"},\"conversation_id\":\"conv-demo-1\",\"site_id\":\"eperformance_vitrine\"}"

echo
echo "########## 2. CORPS INVALIDE : ENDPOINT VIDE ##########"
curl -s -i -X POST "$BASE/api/chatbot/push/subscribe" \
  -H 'Content-Type: application/json' \
  -d '{"endpoint":"","keys":{"p256dh":"BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB","auth":"CCCCCCCCCCCCCCCCCCCCCC"}}'

echo
echo "########## 3. CORPS INVALIDE : CLES MANQUANTES ##########"
curl -s -i -X POST "$BASE/api/chatbot/push/subscribe" \
  -H 'Content-Type: application/json' \
  -d "{\"endpoint\":\"$ENDPOINT\"}"

echo
echo "########## 3bis. CORPS INVALIDE : DOMAINE NON AUTORISE ##########"
curl -s -i -X POST "$BASE/api/chatbot/push/subscribe" \
  -H 'Content-Type: application/json' \
  -d '{"endpoint":"https://exemple.test/push/abc","keys":{"p256dh":"BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB","auth":"CCCCCCCCCCCCCCCCCCCCCC"}}'

echo
echo "########## 4. REABONNEMENT DU MEME ENDPOINT (cles differentes) ##########"
curl -s -i -X POST "$BASE/api/chatbot/push/subscribe" \
  -H 'Content-Type: application/json' \
  -d "{\"endpoint\":\"$ENDPOINT\",\"keys\":{\"p256dh\":\"$(printf 'D%.0s' $(seq 1 87))\",\"auth\":\"$(printf 'E%.0s' $(seq 1 22))\"},\"conversation_id\":\"conv-demo-1\",\"site_id\":\"eperformance_vitrine\"}"

echo
echo "########## 4bis. SECOND NAVIGATEUR (endpoint different) ##########"
curl -s -o /dev/null -w 'HTTP %{http_code}\n' -X POST "$BASE/api/chatbot/push/subscribe" \
  -H 'Content-Type: application/json' \
  -d "{\"endpoint\":\"$ENDPOINT2\",\"keys\":{\"p256dh\":\"$(printf 'F%.0s' $(seq 1 87))\",\"auth\":\"$(printf 'G%.0s' $(seq 1 22))\"}}"

echo
echo "########## 5. ETAT EN BASE (lecture directe, sans ORM) ##########"
"$PY" - "$DEMO/push_demo.db" <<'PYEOF'
import sqlite3, sys
lignes = sqlite3.connect(sys.argv[1]).execute(
    "SELECT id, substr(endpoint, 1, 46) || '…', conversation_id, site_id, "
    "actif, keys_p256dh, date_creation, date_derniere_utilisation, user_agent "
    "FROM push_subscriptions ORDER BY id"
).fetchall()
print(f"{len(lignes)} ligne(s) dans push_subscriptions :")
for l in lignes:
    print("  id=%s endpoint=%s conversation=%s site=%s actif=%s p256dh=%s creation=%s derniere_utilisation=%s ua=%s"
          % (l[0], l[1], l[2], l[3], l[4], l[5][:12] + "…", l[6], l[7], l[8]))
print("total lignes pour l'endpoint 1 :",
      sqlite3.connect(sys.argv[1]).execute(
          "SELECT count(*) FROM push_subscriptions WHERE endpoint LIKE 'https://fcm.googleapis.com/%'"
      ).fetchone()[0])
PYEOF

echo
echo "########## 6. ENVOI PUSH SANS VAPID CONFIGURE (admin) ##########"
JETON=$("$PY" -c "
import sys; sys.path.insert(0, '$RACINE')
from backend.core.auth import create_access_token
print(create_access_token({'sub': 'demo@local.test', 'role': 'admin'}))")
curl -s -i -X POST "$BASE/api/chatbot/admin/notify" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $JETON" \
  -d '{"canal":"webpush","sujet":"Demonstration","message":"Verification de la degradation propre"}'

echo
echo "########## 7. DESABONNEMENT (endpoint exact) ##########"
curl -s -i -X DELETE "$BASE/api/chatbot/push/unsubscribe?endpoint=$ENDPOINT"

echo
echo "########## 8. ETAT EN BASE APRES DESABONNEMENT ##########"
"$PY" - "$DEMO/push_demo.db" <<'PYEOF'
import sqlite3, sys
for l in sqlite3.connect(sys.argv[1]).execute(
        "SELECT id, substr(endpoint, 1, 46) || '…', actif FROM push_subscriptions ORDER BY id"):
    print("  id=%s endpoint=%s actif=%s" % l)
print("la ligne desabonnee est CONSERVEE (actif = 0), elle n'est pas supprimee")
PYEOF

echo
echo "########## 9. DESABONNEMENT REPETE (idempotence) ##########"
curl -s -i -X DELETE "$BASE/api/chatbot/push/unsubscribe?endpoint=$ENDPOINT"

echo
echo "########## 10. DESABONNEMENT D'UN ENDPOINT INCONNU ##########"
curl -s -i -X DELETE "$BASE/api/chatbot/push/unsubscribe?endpoint=https://fcm.googleapis.com/fcm/send/jamais-vu"

echo
echo "########## 11. LISTAGE ADMIN DES ABONNEMENTS (les deux sources) ##########"
curl -s -i "$BASE/api/chatbot/admin/push/subscriptions" -H "Authorization: Bearer $JETON"

echo
echo "########## 12. TRACE DES NOTIFICATIONS (canaux + tentatives) ##########"
curl -s -i "$BASE/api/chatbot/notifications" -H "Authorization: Bearer $JETON"

arreter_serveur

echo
echo "############ SERVEUR 2 : CLES VAPID FACTICES PRESENTES ############"
VAPID_PUBLIC_KEY="cle-publique-de-demonstration" VAPID_PRIVATE_KEY="cle-privee-de-demonstration" \
  VAPID_CONTACT="notifications@exemple.test" demarrer_serveur --vapid || {
    echo "demarrage impossible"; exit 1; }

echo
echo "########## 13. ETAT DU CANAL AVEC CLES PRESENTES (envoi sans abonnement actif) ##########"
JETON=$("$PY" -c "
import sys; sys.path.insert(0, '$RACINE')
from backend.core.auth import create_access_token
print(create_access_token({'sub': 'demo@local.test', 'role': 'admin'}))")
curl -s -i -X POST "$BASE/api/chatbot/admin/notify" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $JETON" \
  -d '{"canal":"webpush","sujet":"Demonstration","message":"Aucun abonnement actif"}'

echo
echo "########## 14. ABONNEMENT TOUJOURS ACCEPTE AVEC LES CLES EN PLACE ##########"
curl -s -o /dev/null -w 'HTTP %{http_code}\n' -X POST "$BASE/api/chatbot/push/subscribe" \
  -H 'Content-Type: application/json' \
  -d "{\"endpoint\":\"$ENDPOINT2\",\"keys\":{\"p256dh\":\"$(printf 'F%.0s' $(seq 1 87))\",\"auth\":\"$(printf 'G%.0s' $(seq 1 22))\"}}"

arreter_serveur
echo
echo "############ FIN ############"
```

---

## 6. Tests

### 6.1 État de la suite, avant et après

Deux environnements, parce qu'ils ne disent pas la même chose.

**Environnement du projet** (`python -m pytest -q`, celui qui servait de
référence avant la tâche) :

| | passés | sautés | erreurs |
|---|---|---|---|
| **avant** (code de départ) | 170 | 18 | 2 |
| **après** | **232** | **19** | **2** |

Deux écarts, tous deux attendus et expliqués : +62 tests passés (le fichier
`test_push_subscribe.py`, dont un test se saute ici car `pywebpush` n'y est pas
installé), et le compteur de sauts passe de 18 à 19 pour cette raison exacte.
Les 2 erreurs sont les erreurs **préexistantes** de
`backend/communication/test_whatsapp_quick.py` (accès réseau à l'API WhatsApp),
inchangées.

**Environnement vierge, déploiement simulé** (dépendances du nouveau
`requirements.txt`, `pywebpush` installé) :

| | passés | échoués | sautés | erreurs |
|---|---|---|---|---|
| **avant** (code de départ, même venv) | 168 | 17 | 3 | 2 |
| **après** | **231** | **17** | **3** | **2** |

Les 17 échecs sont **identiques avant et après** : ce sont des tests de
`backend/communication/` qui dépendent de paquets optionnels absents de cet
environnement vierge. Aucun échec nouveau. Le delta est de +63, soit exactement
le nouveau fichier de tests. La comparaison a été faite en extrayant le code de
départ (`git archive HEAD`) dans un répertoire séparé, donc à code identique
hormis mes modifications.

### 6.2 Les six cas exigés

| Cas exigé | Test | Résultat |
|---|---|---|
| abonnement valide → 200 et ligne créée | `TestAbonnement::test_abonnement_valide_repond_200_et_cree_la_ligne` + `test_le_visiteur_s_abonne_SANS_JETON` | passe |
| corps invalide → 422 (endpoint vide, clés manquantes) | `TestCorpsInvalide` — 12 variantes paramétrées, plus domaine inconnu, schéma non https, endpoint interne, domaine imité, endpoint trop long | passe |
| réabonnement du même endpoint → pas de doublon | `TestReabonnement::test_meme_endpoint_ne_cree_pas_de_doublon` (une seule ligne, clés remplacées) | passe |
| désabonnement → `actif = false` | `TestDesabonnement::test_le_desabonnement_passe_la_ligne_a_inactif` + `test_le_desabonnement_ne_supprime_rien` | passe |
| envoi push sans VAPID configuré → état « non configuré » | `TestEnvoiDegrade::test_envoi_sans_vapid_est_non_configure_et_ne_leve_pas` (aucun appel réseau autorisé) | passe |
| abonnement enregistré mais clés absentes → dégradation propre | `TestEnvoiDegrade::test_abonnement_enregistre_mais_cles_absentes_degrade_proprement` (503, trace écrite, abonnement conservé) | passe |

Autres points durs couverts par des tests : la table est déclarée pour
`init_db()` et se crée réellement ; elle n'a ni colonne JSON, ni donnée
personnelle, ni clé étrangère ; les deux tables sont lues et dédoublonnées ;
un abonnement désactivé n'est pas transmis ; les clés ne sont jamais renvoyées ;
l'endpoint complet n'est jamais renvoyé ; l'abonnement reste enregistré malgré
l'absence de clés VAPID.

### 6.3 L'envoi réel, avec la vraie bibliothèque

`TestEnvoiReel::test_un_vrai_message_chiffre_et_signe_est_produit` s'exécute
dans un sous-processus, avec une paire VAPID générée à la volée et un serveur
HTTP local jouant le rôle du service de push. Il vérifie que :

* l'envoi rend `envoye`, un message envoyé, sans erreur ;
* une requête arrive, signée `vapid t=<jwt>,k=<clé>` ;
* le jeton vise bien l'audience du service appelé et porte le contact configuré ;
* le corps est illisible en clair, **et** se déchiffre avec la clé privée du
  navigateur pour rendre exactement `{"title": "Nouveau lead", "body": "…"}` ;
* aucun terme interne (agent, persona, routage, invite) n'apparaît dans ce qui
  part au navigateur.

C'est la première fois que l'envoi de la tâche 6.5 est exercé avec la vraie
bibliothèque : les tests de 6.5 utilisaient des réponses simulées, la
bibliothèque n'étant pas installée.

### 6.4 Le cas 6.5 « clés présentes, clé invalide »

Rencontré pendant la démonstration (§5, étape 13) : avec des clés **factices**,
le canal se déclare configuré (l'état dit « les variables sont là », pas « la
clé est valide »), l'envoi échoue sur la désérialisation de la clé, et le
résultat est un échec **tracé** avec le motif exact — 502, jamais 500, aucune
exception. C'est le comportement voulu, et il est visible dans la sortie brute.

---

## 7. Ce qui revient au propriétaire

### 7.1 Créer les clés VAPID (deux variables)

Commande vérifiée, à exécuter une seule fois (`pip install py-vapid`) :

```bash
python3 -c "
import base64
from py_vapid import Vapid
from cryptography.hazmat.primitives import serialization as ser
v = Vapid(); v.generate_keys()
b64 = lambda o: base64.urlsafe_b64encode(o).rstrip(b'=').decode()
print('VAPID_PRIVATE_KEY=' + b64(v.private_key.private_bytes(ser.Encoding.DER, ser.PrivateFormat.PKCS8, ser.NoEncryption())))
print('VAPID_PUBLIC_KEY=' + b64(v.public_key.public_bytes(ser.Encoding.X962, ser.PublicFormat.UncompressedPoint)))
"
```

Elle imprime deux lignes. La clé privée commence par `MIGHAgEAMBMGByqGSM49…` et
fait 184 caractères ; la clé publique fait 87 caractères.

À poser dans les variables d'environnement du service (Railway), **sans jamais
les écrire dans un fichier versionné** — le dépôt est public :

```
VAPID_PRIVATE_KEY=<la première ligne>
VAPID_PUBLIC_KEY=<la seconde ligne>
VAPID_CONTACT=mailto:notifications@eperformance.pro   (ou l'adresse de contact voulue)
```

`VAPID_CONTACT` est facultatif mais recommandé : sans lui, le code retombe sur
`BREVO_SENDER_EMAIL`. C'est ce contact qui figure dans la signature envoyée aux
services de push.

### 7.2 Le piège de format, vérifié

Quatre formats ont été essayés sur la vraie bibliothèque :

| Format de `VAPID_PRIVATE_KEY` | Résultat |
|---|---|
| base64url du DER PKCS8 (ce que produit la commande ci-dessus) | **accepté**, envoi produit |
| base64url de la graine brute de 32 octets | **accepté**, envoi produit |
| base64url avec remplissage `=` | **accepté**, envoi produit |
| PEM, multiligne ou sur une ligne | **refusé** — `ValueError: Could not deserialize key data`, échec tracé, aucune requête émise, aucun plantage |

Autrement dit : si la clé privée est collée au format PEM (`-----BEGIN…`), le
push ne partira pas, et l'échec sera visible dans la trace des notifications
avec ce motif exact. C'est le seul point qui pourrait faire croire à une panne
alors que la configuration est simplement mal formée. La commande du §7.1
produit directement le bon format.

### 7.3 La clé publique doit atteindre le navigateur

`PushManager.subscribe()` a besoin de la clé **publique** en
`applicationServerKey`. Elle est publique par nature (elle est envoyée à chaque
abonnement), mais aucun endpoint ne la sert aujourd'hui : c'est le seul point
d'interface qui manque encore entre le widget et ce backend. Voir §8.1.

### 7.4 Ce que débloquent ces deux variables

Dès qu'elles sont posées et le service redéployé : `canal.configure` passe à
vrai, `POST /api/chatbot/admin/notify` avec `canal = "webpush"` cesse de
répondre 503 et envoie réellement à tous les abonnements actifs — ceux du widget
comme ceux enregistrés par la route d'administration. Aucun autre changement de
code n'est nécessaire.

---

## 8. Bloqué, et points de coordination

### 8.1 La clé publique VAPID vers le widget (à trancher, non fait ici)

Le versant client (`PushManager.subscribe`) appartient à la session widget et est
hors de ma portée. Il lui faut la clé publique côté navigateur, et rien ne la
sert aujourd'hui. Deux issues :

1. un `GET /api/chatbot/push/config` public et en lecture seule, qui renvoie la
   clé publique quand elle existe et un état explicite sinon — 15 lignes, aucun
   secret exposé (la clé privée ne sortirait jamais) ;
2. une clé publique écrite en dur dans le widget, au prix d'une reprise du
   widget le jour d'une rotation de clés.

Je n'ai pas ajouté cet endpoint de moi-même : il ne figure pas dans les
livrables demandés, et la décision de l'interface revient à la session widget et au
propriétaire. Si l'option 1 est retenue, elle tient dans un commit séparé.

### 8.2 Non déployé

Les commits sont **locaux**. Un `git push` sur `main` déclenche un
redéploiement automatique Railway : c'est une décision du propriétaire, pas la
mienne. Le test de fumée pre-push passe (voir §9), donc le push est prêt à
partir.

### 8.3 Rappel, hors périmètre

Le canal e-mail reste en échec pour une raison qui n'est pas du code : Brevo
refuse l'adresse IP émettrice de Railway (« unrecognised IP address ») tant
qu'elle n'est pas autorisée dans leur interface. Rien à faire côté backend.

### 8.4 Limites connues, assumées

* `etat_canal("webpush")` dit « les variables sont là », pas « la clé est
  valide » : c'est voulu (aucun appel réseau au diagnostic), et le cas d'une clé
  invalide produit un échec tracé, jamais un plantage.
* Les endpoints créés **avant** la liste blanche du §3.3 n'existent pas : la
  table vient d'être créée. La route d'administration, elle, ne passe pas par
  cette liste — elle est réservée aux administrateurs.
* `date_derniere_utilisation` n'attribue pas le succès à un abonnement précis
  (§3.8).

---

## 9. Vérifications de sortie

```
$ bash scripts/pre-push-smoke-test.sh
[smoke-test] OK — application FastAPI importable
[smoke-test] PASS — push autorisé

$ python3 scripts/verifier-secrets.py
[secrets] PASS — aucun secret detecte (122 fichier(s))
```

Aucune valeur de clé n'apparaît dans les fichiers ajoutés : les commandes du
§7.1 sont des gabarits, et les seules clés générées pendant les vérifications
l'ont été en mémoire ou dans `/tmp`, jamais dans le dépôt.

### Commits

| Commit | Message |
|---|---|
| 1 | `feat(push): abonnements navigateur — table push_subscriptions, endpoints publics, envoi raccordé` |
| 2 | `build(deps): pywebpush 2.5.0, installation vérifiée en environnement vierge` |
| 3 | `docs(push): rapport de la tâche — preuves curl, tests avant/après, reste au propriétaire` |

Chaque commit porte un seul sujet ; le test de fumée et le contrôle de secrets
passent sur l'arbre final.

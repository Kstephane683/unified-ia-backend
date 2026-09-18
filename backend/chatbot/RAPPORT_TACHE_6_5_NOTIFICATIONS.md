# RAPPORT — Tâche 6.5 : notifications

Date : 2026-09-18 · Dépôt : `unified-ia-backend` · Branche : `main`

---

## 1. Ce qui est livré

| Livrable | Fichier |
|---|---|
| Canaux, envois, états, trace | `backend/chatbot/notifications.py` |
| Tables `chatbot_notification_logs`, `chatbot_push_subscriptions` | `backend/chatbot/models.py` |
| `POST /api/chatbot/admin/notify`, `GET /api/chatbot/notifications`, `POST /api/chatbot/admin/push/subscriptions` | `backend/api/routes/admin_chatbot.py` |
| Tests (36) | `backend/chatbot/test_tache_6_5_notifications.py` |

### Les endpoints

- `POST /api/chatbot/admin/notify` — corps : `canal`, `message`, `sujet`,
  `destinataire` (facultatif), `site_id` (facultatif). **Admin requis.**
- `GET /api/chatbot/notifications` — trace des envois **et état des canaux**.
  Filtres `canal`, `statut`, `limit`. **Admin requis.**
- `POST /api/chatbot/admin/push/subscriptions` — enregistrement d'un abonnement
  au push. **Provisoire et admin** (voir §5).

L'authentification **réutilise le mécanisme existant** :
`Depends(get_current_user)` + le garde `require_admin` déjà présent dans
`admin_chatbot.py`. Aucun second système d'authentification n'a été créé.
Vérifié en réel : `401` sans jeton, `403` avec un jeton non-admin.

### Codes HTTP, et pourquoi ils ne sont pas tous 200

| Code | Sens |
|---|---|
| `200` | l'envoi a abouti |
| `503` | le canal n'est **pas configuré** — l'envoi n'a pas été tenté |
| `502` | le canal est configuré mais le **fournisseur a refusé** |

Renvoyer `200` pour un canal non configuré ferait croire à un envoi parti.
Dans les trois cas, la tentative est **tracée** et le corps contient le résultat
complet plus l'état de tous les canaux.

---

## 2. État réel des canaux, mesuré

| Canal | État | Preuve |
|---|---|---|
| **Telegram** | **CONFIGURÉ ET FONCTIONNEL** | `getMe` → HTTP 200, bot « ePerformance système » |
| **E-mail (Brevo)** | **CONFIGURÉ MAIS EN ÉCHEC depuis cette machine** | `GET /v3/account` → HTTP 401 « unrecognised IP address » |
| **Push navigateur** | **NON CONFIGURÉ** | aucune clé VAPID en production, `pywebpush` non installé |
| **WhatsApp** | configuré (jeton présent), non vérifié | — |

Le point important : `BREVO_API_KEY` est **déclarée** en production mais
**refusée** par Brevo, qui n'autorise pas l'adresse IP émettrice. C'est
exactement ce qui justifie la règle « une clé déclarée dans un fichier de
configuration n'est pas une clé qui fonctionne » — et c'est devenu le cas de
test « configuré mais échec », joué sur le vrai fournisseur, pas simulé.

---

## 3. Le point dur : rien ne peut empêcher le démarrage

Le backend a déjà subi une panne de production à cause d'un import manquant.
Trois règles sont appliquées, sans exception :

1. **Aucun import de bibliothèque optionnelle au chargement du module.**
   `pywebpush` est importé **à l'intérieur** de la fonction d'envoi, dans un
   `try`. Son absence est un état, pas une erreur. Un test vérifie
   explicitement que `pywebpush` n'est pas dans `sys.modules` après chargement.
2. **Aucun appel réseau au chargement.** Les états des canaux sont calculés sur
   la seule présence des variables d'environnement. Un endpoint de diagnostic ne
   doit pas échouer parce qu'un fournisseur est lent.
3. **Aucune exception ne remonte.** `envoyer()` renvoie toujours un
   `ResultatEnvoi` ; `tracer()` absorbe ses propres erreurs.

Preuve : démarrage avec **zéro** variable de notification, en réel :

```
=== demarrage SANS aucune cle de notification ===
GET /health -> HTTP 200
canaux :
   telegram  configure=False non configuré : TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID manquant(s)
   email     configure=False non configuré : BREVO_API_KEY, BREVO_SENDER_EMAIL manquant(s)
   webpush   configure=False non configuré : VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY manquant(s) — le propriétaire n'a pas encore créé les clés VAPID du push navigateur
   whatsapp  configure=False non configuré : WHATSAPP_ACCESS_TOKEN ou WHATSAPP_PHONE_NUMBER_ID manquant

=== notification refusee proprement (aucune cle) ===
POST /admin/notify telegram -> HTTP 503
statut: non_configure | motif: non configuré : TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID manquant(s)
```

Et un test dédié lance un interpréteur **neuf**, sans aucune variable, et vérifie
que le module s'importe (code de sortie 0).

---

## 4. Persistance et trace

Deux tables, créées par `init_db()` au démarrage (aucune migration à écrire,
`create_all` n'ajoute que les tables absentes) :

- `chatbot_notification_logs` : `canal`, `statut`, `succes`, `destinataire`,
  `sujet`, `corps` (tronqué à 500 caractères), `code_erreur`, `erreur`,
  `identifiant_fournisseur`, `auteur`, `duree_ms`, `created_at`, `envoye_le`.
- `chatbot_push_subscriptions` : `endpoint` (unique), `cle_p256dh`, `cle_auth`,
  `site_id`, `libelle`, `est_actif`, `derniere_reussite`, `dernier_echec`.

**Le statut distingue `non_configure` de `echec`** : ce n'est pas un détail de
nommage — les deux ne se réparent pas de la même façon, et les confondre rendrait
le diagnostic impossible.

Aucun `flag_modified()` n'est nécessaire : les deux tables n'ont **aucune colonne
JSON**, ce qui supprime par construction le piège de la comparaison
`new == old` au flush. C'est un choix, pas un oubli.

Vérifié en réel sur le serveur local, les trois cas dans une même trace :

```
resume: {'envoye': 1, 'echec': 1, 'non_configure': 1}
lignes:
   #3 webpush   non_configure
   #2 telegram  envoye
   #1 email     echec
```

---

## 5. Les trois cas exigés, joués en réel

### Cas 1 — non configuré (aucune clé VAPID)

```
POST /api/chatbot/admin/notify {"canal":"webpush", ...}
HTTP 503
statut: non_configure | succes: False
motif : non configuré : VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY manquant(s) — le
propriétaire n'a pas encore créé les clés VAPID du push navigateur
```

### Cas 2 — configuré mais l'envoi échoue (Brevo, vrai 401)

```
POST /api/chatbot/admin/notify {"canal":"email","destinataire":"notifications@eperformance.pro", ...}
HTTP 502
statut: echec | succes: False | code_erreur: 401
motif : unauthorized We have detected you are using an unrecognised IP address
        2c0f:4c40:d22:c7a9:d4eb:aa85:8da4:1c3a. [...]
```

Le motif du fournisseur est remonté **tel quel** : c'est ce qui permettra de
comprendre un refus sans avoir à instrumenter le code.

### Cas 3 — succès (Telegram, envoi réel)

```
POST /api/chatbot/admin/notify {"canal":"telegram","sujet":"[TEST] Tache 6.5 notifications", ...}
HTTP 200
statut: envoye | succes: True
destinataire: 8441274889 | messages: 1
identifiant chez Telegram: 623 | duree: 527 ms
```

Un message de test a réellement été délivré au bot `@ePerformanceBot`
(`message_id 623`).

### Tests

```
python3 -m pytest backend/chatbot/test_tache_6_5_notifications.py -q
36 passed in 4.28s
```

Couvre les 3 cas, l'import en interpréteur neuf, la création réelle des tables,
l'absence d'appel réseau quand le canal n'est pas configuré (le `post` est
remplacé par une fonction qui échoue si elle est appelée), l'absorption des
erreurs réseau et des délais dépassés, la conservation de l'identifiant
fournisseur, les refus d'authentification (401/403), le refus explicite de
l'abonnement push tant que le push n'est pas configuré.

---

## 6. Ce qui est bloqué, et ce qui revient au propriétaire

### Bloqué par le propriétaire

1. **Push navigateur — deux actions, dans cet ordre :**
   a. créer un jeu de clés VAPID (paire publique/privée) et les poser en
      variables `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` (+ `VAPID_CONTACT`,
      un `mailto:`) ;
   b. **ajouter `pywebpush` à `requirements.txt`** puis redéployer.
   Les deux sont nécessaires : l'état du canal le dit explicitement, et sans
   elles rien ne casse — la fonctionnalité est simplement absente.
2. **Brevo : autoriser l'adresse IP émettrice** dans l'interface Brevo
   (Sécurité → IP autorisées), ou vérifier que l'IP de sortie de Railway y est.
   Tant que ce n'est pas fait, l'email échouera avec un 401 : la trace le
   montrera, l'endpoint répondra 502 avec le motif exact.
3. **Front (widget / dashboard)** : rien n'appelle encore ces endpoints. C'est
   le travail de l'agent du widget.

### Décisions de conception à valider

- **L'enregistrement d'un abonnement push est réservé aux administrateurs**,
  de façon provisoire. Un abonnement est normalement créé par le navigateur du
  visiteur : il faudra une route publique quand le widget implémentera son
  service worker. Elle est différée **parce qu'elle est inutile aujourd'hui**
  (aucune clé VAPID ne permettrait de servir l'abonnement) et qu'ouvrir une
  écriture publique non testable serait un risque sans contrepartie.
- **Aucun envoi automatique n'est câblé.** Cette tâche livre l'infrastructure
  d'envoi et sa trace, pas les déclencheurs métier. Les brancher (nouveau lead,
  prise de contact humain, échec du chatbot) est une décision produit qui n'a
  pas été prise ici. Le point d'accroche naturel est `ActionExecutor`, à côté
  des notifications de lead existantes.

---

## 7. Variables d'environnement

| Variable | Canal | Rôle |
|---|---|---|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_ID` | telegram | jeton, destinataire par défaut |
| `BREVO_API_KEY`, `BREVO_SENDER_EMAIL`, `BREVO_SENDER_NAME` | email | envoi via l'API Brevo v3 |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CONTACT` | webpush | clés du push navigateur (absentes aujourd'hui) |
| `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` | whatsapp | API Cloud de Meta |
| `NOTIF_TIMEOUT` | tous | délai d'un appel fournisseur (défaut `15` s) |
| `NOTIF_TRACE_CORPS` | tous | longueur du corps conservé dans la trace (défaut `500`) |

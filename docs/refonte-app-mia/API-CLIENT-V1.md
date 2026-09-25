# API CLIENT V1 — Contrat de l'app Mia (backend)

**Date** : 2026-09-19 · **Chantiers** : B1 (provisionnement) · B2 (rôles scopés + 2FA + audit) · B3 (API client) · B4 (déclencheurs de notification) · **Fondations d'extensibilité** (feature flags, plans, abonnement Jeko, tracking, WhatsApp/RCS pré-implémentés inactifs — cf. `EXTENSIBILITE.md`)
**Base URL production (vérifiée le 19/09)** : `https://web-production-4ab53.up.railway.app` · **Préfixe client** : `/api/client/v1` (versionnement : toute rupture ira en v2)
**Destinataire de ce document** : l'agent SITE — ce sont les DONNÉES des écrans de l'app Mia.

> **⚠️ CORRIGÉ LE 19/09 (signalement SITE, révisé par mesure)** : une première version annonçait « 20 endpoints client (+ 3 routes admin) » en comptant ensemble les routes client, les routes admin et plusieurs méthodes par chemin. **Le compte réel vérifié par lecture du code : `20` routes dans `backend/api/routes/client.py`** + `3` routes admin (`POST/GET /api/chatbot/admin/clients`, `GET /api/chatbot/admin/audit`). La vérification croisée doc ↔ code ne montre **aucun chemin fantôme** (tout chemin annoncé existe) — le défaut était le compte, pas des routes inventées. **En cas de divergence, le code fait foi** : une entrée au journal le signale.
>
> **MISE À JOUR 19/09 (fondations d'extensibilité)** : `client.py` porte désormais **26 routes** (les 20 d'origine + `/plans`, `/subscribe`, `POST /analytics/event`, `GET /analytics/app`, `GET .../analytics/export`), plus le routeur `webhooks.py` (`POST /api/webhooks/jeko`, `GET|POST /api/webhooks/whatsapp`). Sections 15 à 18.

---

## 1. Vue d'ensemble

L'app Mia est un SaaS de gestion **multi-tenant** pour les PROPRIÉTAIRES des sites clients. Chaque compte est lié à UN site (`user.site_id`) ; chaque route de données porte `{site_id}` dans son chemin et le backend vérifie que le compte gère bien CE site.

Trois règles produit encodées dans l'API (non négociables) :

1. **Isolation multi-tenant** : un propriétaire qui demande les données d'un site qui n'est pas le sien reçoit **404** (jamais 403) — la réponse ne révèle jamais l'existence des autres sites.
2. **Mia seule** : aucune réponse n'expose le nom, le compteur ni l'identité des agents internes (`agent_used`, `assigned_agent`, compteurs). On parle de « compétences de Mia ».
3. **Ne jamais vendre ce qui n'existe pas** : `GET .../orders` répond 200 avec un état explicite `disponible: false`, pas une erreur ni une liste vide trompeuse.

---

## 2. Authentification

### 2.1 Rôles

| Rôle | Valeur (`role_client`) | Niveau | Peut faire |
|---|---|---|---|
| Admin ePerformance | — (`role='admin'`) | ∞ | tout, sur tous les sites |
| Admin du site | `client_admin` | 3 | réglages du site, suppression RGPD, 2FA obligatoire |
| Opérateur | `client_operator` | 2 | conversations, réponses, prise de main |
| Lecteur | `client_reader` | 1 | lecture seule |

La granularité vit dans `role_client` (VARCHAR validé applicativement) ; la colonne `role` du compte vaut `'client'` (valeur existante de l'enum PostgreSQL — voir la note de design dans `backend/core/models.py`). Un compte sans `role_client` (comptes préexistants) est refusé sur les routes client (403 « Compte client non provisioné »).

### 2.2 Connexion

`POST /api/auth/login` (OAuth2 form : `username` = e-mail, `password`) ou `POST /api/auth/login/json` (JSON).

Champs additionnels (facultatifs, rétrocompatibles) :

| Champ | Form | JSON | Effet |
|---|---|---|---|
| `remember_me` | `"true"` | `true` | jeton de **30 jours** au lieu de 24 h (`expires_in: 2592000`) |
| `totp_code` | code 6 chiffres | idem | requis si la 2FA est active sur le compte |

Réponse 200 :

```json
{
  "access_token": "…",
  "token_type": "bearer",
  "expires_in": 86400,
  "must_change_password": false
}
```

Erreurs : 401 `Incorrect email or password` · 401 raison **`2fa_requise`** (l'app doit alors afficher le champ code, ce n'est pas une erreur générique) · 401 `code 2FA invalide` · 403 `Account is disabled` · 403 `2FA non vérifiable côté serveur` (secret illisible — échec fermé).

### 2.3 Le flux de première connexion (livraison d'un site)

1. ePerformance crée le compte → mot de passe **temporaire** renvoyé UNE FOIS (voir §8.1).
2. Connexion : 200 avec `must_change_password: true`.
3. **Tant que c'est vrai, toutes les routes client refusent (403 « Changement de mot de passe requis… »)** SAUF `GET /me` et `POST /password`.
4. `POST /api/client/v1/password` → `must_change_password` passe à faux (tracé en audit).
5. Si le rôle est `client_admin` : configurer la **2FA** (§5) — les routes du site refusent (403 « 2FA obligatoire… ») tant qu'elle n'est pas active.
6. Les routes du site répondent.

### 2.4 Ordre des vérifications (contrat)

`require_site_owner` vérifie, DANS CET ORDRE : admin ePerformance passe toujours → compte provisioné (403) → **le site demandé est celui du compte (404 sinon)** → suffisance de rôle (403) → porte 2FA pour `client_admin` (403). L'isolation prime sur tout : même un `client_admin` en attente de 2FA reçoit 404 sur un site étranger.

---

## 3. Compte (account-level)

### 3.1 `GET /api/client/v1/me`

Auth : Bearer (accessible pendant le changement forcé). Réponse 200 :

```json
{
  "user_id": 12, "email": "proprietaire@client.fr", "nom": "…",
  "role": "client", "role_client": "client_admin",
  "must_change_password": false,
  "sites": [{"site_id": "…", "site_name": "…", "site_url": "…",
              "secteur": "restauration", "is_active": true}],
  "tfa": {"active": true, "requise": true},
  "plan": "free",
  "fonctionnalites_actives": ["notifications_push", "analytics_export", "ia_en_direct"],
  "fonctionnalites_verrouillees": [
    {"cle": "whatsapp_notifications", "plan_requis": "premium", "raison": "fonctionnalité inactive"}
  ]
}
```

`tfa.requise` vaut vrai pour `client_admin` — l'app affiche l'écran de configuration tant que `tfa.active` est faux.

**Fonctionnalités (fondations d'extensibilité)** : `plan` vaut `free` (défaut), `premium` ou `pro`. `fonctionnalites_actives` liste les clés que le compte peut utiliser ; `fonctionnalites_verrouillees` les autres, chacune avec son `plan_requis` et sa `raison` (`fonctionnalité inactive` ou `plan X requis`). L'app découvre TOUTE nouvelle fonctionnalité par cette seule réponse — recette d'extension dans `EXTENSIBILITE.md §1`.

### 3.2 `POST /api/client/v1/password`

Auth : Bearer (accessible pendant le changement forcé). Corps :

```json
{"ancien_mot_de_passe": "…", "nouveau_mot_de_passe": "8 caractères minimum"}
```

Réponse 200 : `{"ok": true, "must_change_password": false, "message": "…"}`
Erreurs : 400 `Ancien mot de passe incorrect` · 422 validation. **Rate limit : 5 / 300 s** (force brute). Tracé en audit (`changement_mot_de_passe`).

### 3.3 2FA TOTP (`client_admin` obligatoire)

| Route | Corps | Réponse / erreurs |
|---|---|---|
| `POST /api/client/v1/2fa/setup` | — | 200 `{"secret": "BASE32…", "otpauth_uri": "otpauth://totp/Mia%20ePerformance:…", "message": "…"}` — secret et URI renvoyés **UNE SEULE FOIS**, l'app génère le QR. 400 si déjà activée. 503 si le chiffrement serveur est indisponible. |
| `POST /api/client/v1/2fa/activate` | `{"code": "123456"}` | 200 `{"ok": true, "tfa_active": true}`. 400 `Code 2FA invalide` / `Aucun secret en attente : commencez par POST /2fa/setup`. Tolérance ±30 s (fenêtre adjacente). |
| `POST /api/client/v1/2fa/disable` | `{"mot_de_passe": "…"}` | 200 `{"ok": true, "tfa_active": false}` — le mot de passe est exigé, le secret est effacé. 400 `Mot de passe incorrect` / `2FA non activée`. |

Le secret est stocké **chiffré** (Fernet, clé dérivée de `SECRET_KEY`, préfixe `fernet:v1:`) — jamais en clair, jamais renvoyé après le setup. Rate limits : setup/activate 10/300 s, disable 5/300 s. Activation et désactivation sont tracées en audit.

Login avec 2FA active : sans code → 401 `2fa_requise` ; avec code valide → 200.

---

## 4. Conversations (écrans 3 et 4)

Toutes scopées : `require_site_owner` (voir §2.4).

### 4.1 `GET /api/client/v1/sites/{site_id}/conversations`

Query : `page` (≥1), `page_size` (1-100, défaut 20), `non_lu` (bool), `escalade` (bool), `avec_lead` (bool), `q` (recherche : nom, e-mail, téléphone, contenu des messages).

Définition de « non lu » : le DERNIER message de la conversation est celui du visiteur.

Réponse 200 :

```json
{
  "conversations": [{
    "conversation_id": "…", "site_id": "…", "status": "active|escalated|resolved|abandoned",
    "human_active": false, "lead_captured": false,
    "visitor_name": "…", "visitor_phone": "…",
    "message_count": 4, "non_lu": true,
    "last_message": "120 premiers caractères", "last_message_role": "user",
    "created_at": "ISO", "last_message_at": "ISO"
  }],
  "total": 42, "page": 1, "page_size": 20
}
```

### 4.2 `GET .../conversations/{conversation_id}`

Détail + messages + lead. 200 :

```json
{
  "conversation": {"conversation_id": "…", "status": "…", "human_active": false,
                    "lead_captured": true, "message_count": 4,
                    "created_at": "ISO", "last_message_at": "ISO"},
  "visitor": {"name": "…", "email": "…", "phone": "…"},
  "lead": {"id": 7, "lead_type": "hot", "status": "new", "intent": "…",
            "message": "…", "created_at": "ISO"},
  "messages": [{"id": 1, "role": "user|assistant", "content": "…",
                 "human": false, "human_name": null, "created_at": "ISO"}]
}
```

`human: true` + `human_name` identifient un message écrit par un conseiller (badge de l'interface). 404 si la conversation n'existe pas OU appartient à un autre site.

### 4.3 `POST .../conversations/{conversation_id}/reply`  (opérateur minimum)

Corps : `{"content": "4000 caractères max"}`. Écrit un message humain et **PREND LA MAIN** (`human_active=true`, le LLM se met en pause). 200 : `{"ok": true, "message_id": 99, "human_active": true, "created_at": "ISO"}`. Erreurs : 403 (rôle), 404.

### 4.4 `POST .../conversations/{conversation_id}/takeover` et `/release`  (opérateur minimum)

Prise/rendu de la main — même mécanique que les routes admin (logique factorisée dans `backend/chatbot/conversations_service.py`). 200 : `{"conversation_id": "…", "status": "escalated|active", "human_active": true|false}`.

### 4.5 `GET .../analytics`

Réutilise EXACTEMENT le calcul de `GET /api/chatbot/analytics/{site_id}`. Query `period_days` (1-365, défaut 30). 200 : `{"site_id", "period_start", "period_end", "total_conversations", "total_messages", "total_leads_captured", "top_intents", "conversion_rate", "avg_messages_per_conversation"}`.

### 4.6 `GET .../leads`

Pagination (`page`, `page_size`). 200 : `{"leads": [{"id", "conversation_id", "name", "email", "phone", "company", "lead_type": "hot|warm|cold|information", "status", "intent", "message", "created_at"}], "total", "page", "page_size"}`.

### 4.7 `GET .../orders` — état explicite

**Toujours 200** (l'intégration e-commerce n'est pas branchée, roadmap « Mia exécute ») :

```json
{"disponible": false, "raison": "l'intégration e-commerce n'est pas branchée (roadmap)", "orders": []}
```

L'app masque l'écran Commandes quand `disponible` est faux.

---

## 5. Réglages du site (écrans 7, 8, 9)

### 5.1 `GET /api/client/v1/sites/{site_id}/settings`

200 :

```json
{
  "site_id": "…", "site_name": "…", "secteur": "restauration",
  "system_prompt": "…", "system_prompt_modifiable": false,
  "welcome_message": "…",
  "notifications": {
    "telegram_active": true, "email_active": true,
    "destinataires": {"email": ["…"], "telegram": ["…"]},
    "par_type": {
      "nouveau_lead":     {"push": true,  "email": true,  "telegram": true},
      "escalade":         {"push": true,  "email": true,  "telegram": true},
      "nouveau_visiteur": {"push": false, "email": false, "telegram": false}
    }
  },
  "rate_limits": {"messages_per_minute": 20, "conversations_per_day": 100},
  "horaires": null,
  "competences": null
}
```

`competences: null` = toutes actives (liste des thèmes actifs sinon).

### 5.2 `PUT .../settings`  (client_admin uniquement)

Corps — tous les champs facultatifs, seuls ceux fournis sont modifiés :

| Champ | Contrainte |
|---|---|
| `welcome_message` | 2000 caractères max |
| `notification_telegram_enabled`, `notification_email_enabled` | bool |
| `notification_recipients` | liste d'e-mails ou `{"email": [...], "telegram": [...]}`
| `notification_settings` | `{type: {push, email, telegram}}` — types : `nouveau_lead`, `escalade`, `nouveau_visiteur` ; canaux absents = défaut du type ; type inconnu → **422** |
| `rate_limit_messages_per_minute` | 1-120 (**422** hors bornes) |
| `rate_limit_conversations_per_day` | 1-10000 |
| `horaires` | objet JSON libre (§6) |
| `competences` | liste des thèmes actifs (cf. §5.3) ; liste vide = tout couper |

**`system_prompt` : refusé avec 400** et la raison (« géré par ePerformance ») — c'est la voix de Mia, décision produit. 400 aussi si aucun réglage n'est fourni. Réponse 200 : `{"ok": true, "champs_modifies": [...], "settings": {…}}`. Tracé en audit (`configuration_site`, liste des champs — jamais les valeurs).

### 5.3 `GET .../competences` — ce que Mia sait faire dans le métier du site

Les thèmes FAQ viennent du **noyau** (`agent-ia-web/eperf_core/sectors.py`) via le snapshot versionné `backend/chatbot/competences_noyau.py` (le noyau n'est pas déployé sur Railway ; il reste la source de vérité, régénérable par `python3 scripts/generer_competences_noyau.py`). L'état actif/inactif vient de `allowed_intents`.

200 (site avec secteur) :

```json
{
  "site_id": "…", "disponible": true, "secteur": "restauration",
  "secteur_nom": "Restauration", "intention": "…", "item": {"nom": "Plat", "…": "…"},
  "competences": [{"theme": "carte et plats", "active": true}, …]
}
```

200 (site sans secteur renseigné) : `{"disponible": false, "message": "Le secteur du site n'est pas encore renseigné par ePerformance…", "competences": []}` — état explicite, pas une erreur.

---

## 6. Horaires (écran 9) — structure JSON

`ChatbotSite.horaires` (JSON) — structure recommandée (libre, le chatbot la lit comme contexte) :

```json
{
  "ouverture": {
    "lundi":     {"ouvert": true,  "creneaux": [{"debut": "09:00", "fin": "14:00"}]},
    "dimanche":  {"ouvert": false}
  },
  "fermetures": [{"debut": "2026-12-24", "fin": "2026-12-26", "motif": "Noël"}],
  "fuseau": "Africa/Ouagadougou",
  "notes": "Service continu le week-end"
}
```

Modifiable par `PUT .../settings` (champ `horaires`, objet obligatoire — 422 sinon).

---

## 7. Notifications in-app (écran 5)

### 7.1 `GET /api/client/v1/sites/{site_id}/notifications`

Query : `lu` (true/false, facultatif), `page`, `page_size`. 200 :

```json
{
  "notifications": [{"id": 31, "type": "nouveau_lead|escalade|nouveau_visiteur",
                      "titre": "Nouveau lead capturé par Mia", "corps": "…",
                      "conversation_id": "…", "lu": false, "date_creation": "ISO"}],
  "non_lues": 3, "total": 27, "page": 1, "page_size": 20
}
```

### 7.2 `POST .../notifications/read`

Corps : `{"ids": [31, 32]}` OU `{"toutes": true}`. 200 : `{"ok": true, "marquees_lues": 2}`. 400 si ni `ids` ni `toutes`.

### 7.3 D'où viennent ces notifications (B4)

Le pipeline `POST /message` (visiteur) déclenche, en ARRIÈRE-PLAN (le visiteur n'attend rien) :

| Événement | Détection | Défaut canaux |
|---|---|---|
| `nouveau_lead` | action `lead_capture` réussie ou bascule `lead_captured` | push + email + telegram |
| `escalade` | action `escalate_to_human` réussie ou passage à `escalated` | push + email + telegram |
| `nouveau_visiteur` | nouvelle conversation | **silencieux** (in-app seule) |

La notification **in-app est écrite TOUJOURS** (elle ne dépend d'aucune clé). Les canaux (webpush sur les abonnements du site, e-mail Brevo, Telegram) partent selon `notification_settings` ET les interrupteurs `notification_*_enabled` du site. Sans clés VAPID ou sans destinataires : dégradation propre — statut **`non_configure`** tracé dans `chatbot_notification_logs`, jamais d'exception. Chaque envoi est tracé dans les trois états : `envoye`, `echec`, `non_configure`.

---

## 8. Routes admin ePerformance (hors app client)

### 8.1 `POST /api/chatbot/admin/clients`  (auth admin) — provisionnement B1

Corps : `{"email": "…", "nom": "…", "site_id": "…", "role_client": "client_admin|client_operator|client_reader"}` (rôle facultatif, défaut `client_admin`).

201 :

```json
{
  "user_id": 45, "email": "…", "nom": "…", "site_id": "…",
  "role_client": "client_admin", "must_change_password": true,
  "mot_de_passe_temporaire": "16+ caractères, symboles ambiguës écartés"
}
```

Le mot de passe temporaire est renvoyé **UNE SEULE FOIS** — il alimente le fichier de livraison ; il n'est ni journalisé, ni audité, ni réaffichable (mot de passe perdu → réinitialisation). Le site doit exister (404 sinon, conseil : `POST /api/chatbot/sites/{site_id}/configure`). 400 si l'e-mail existe déjà, 422 si le rôle est inconnu. Tracé en audit (`creation_compte_client`, SANS le mot de passe).

### 8.2 `GET /api/chatbot/admin/clients?site_id=…`  (auth admin)

Listing des comptes propriétaires — aucun secret renvoyé (`totp_enabled`, `must_change_password`, `last_login` visibles).

### 8.3 `GET /api/chatbot/admin/audit?site_id=&user_id=&action=&limit=`  (auth admin)

Journal d'audit, plus récentes d'abord. Actions tracées (liste fermée) : `creation_compte_client`, `changement_mot_de_passe`, `activation_2fa`, `desactivation_2fa`, `configuration_site`, `export_rgpd_conversation`, `suppression_rgpd_conversation`. Le journal ne contient jamais de contenu de conversation ni de secret.

---

## 9. RGPD (droits du visiteur final exercés par le propriétaire)

### 9.1 `GET .../rgpd/conversations/{conversation_id}/export`  (opérateur minimum)

Export JSON complet : `{"export_rgpd": true, "genere_le": "ISO", "conversation": {…}, "messages": [{role, content, created_at}], "leads": [{name, email, phone, …}]}`. Tracé en audit (compteurs, jamais le contenu). 404 si la conversation n'est pas du site.

### 9.2 `DELETE .../rgpd/conversations/{conversation_id}`  (client_admin uniquement)

Suppression définitive : conversation + messages + leads (cascade). 200 : `{"ok": true, "supprime": true, "conversation_id": "…", "messages_supprimes": 12, "leads_supprimes": 1}`. Tracé en audit. 404 sinon. La notification in-app liée à la conversation reste (trace d'événement, sans contenu).

---

## 10. Matrice d'erreurs standard

| HTTP | Signification |
|---|---|
| 401 | jeton absent/invalide/expiré — ou login sans code 2FA (`2fa_requise`) |
| 403 | rôle insuffisant, compte non provisioné, `must_change_password` actif, 2FA manquante pour `client_admin`, compte désactivé, **fonctionnalité verrouillée** (corps plat : `detail` + `fonctionnalite` + `plan_requis` + `plan_actuel` + `raison` — §15) |
| 404 | ressource inexistante **ou appartenant à un autre site** (isolation — indiscernables volontairement) |
| 422 | validation (bornes, types, types de notification ou de tracking inconnus) |
| 429 | rate limit (voir §11) |
| 503 | dépendance de sécurité indisponible (chiffrement du secret 2FA) |

---

## 11. Rate limiting (mécanisme in-memory existant)

Par chemin + IP, phare partagé par instance :

| Chemin | Limite |
|---|---|
| `/api/auth/login` | 10 / 300 s |
| `/api/client/v1/password` | 5 / 300 s |
| `/api/client/v1/2fa/setup`, `/activate` | 10 / 300 s |
| `/api/client/v1/2fa/disable` | 5 / 300 s |
| `/api/client/v1/subscribe` | 5 / 300 s (déclenche un appel fournisseur) |
| `/api/client/v1/analytics/event` | 30 / 60 s (batch au retour du réseau) |
| `/api/webhooks/jeko` | 30 / 60 s |
| `/api/webhooks/whatsapp` | 60 / 60 s |
| `/api/chatbot/message` | 12 / 60 s |

429 : `{"detail": "Trop de requêtes. Réessayez dans un instant."}` — l'app doit proposer une relance temporisée.

---

## 12. Schéma de données (migration)

**Tables nouvelles** (créées par `create_all`) : `audit_log`, `client_notifications` (B1-B4) ; `fonctionnalites`, `abonnements`, `app_analytics` (fondations d'extensibilité).

**Colonnes ajoutées à des tables EXISTANTES** — le piège du projet : `init_db()` fait `create_all` au boot, qui crée les tables absentes mais **ne modifie jamais une table existante**. La migration est donc appliquée AU BOOT par `backend/core/migrations_boot.py` (inspecteur SQLAlchemy + `ALTER TABLE`, idempotent, journalisé) :

- `users` : `nom`, `site_id`, `role_client`, `must_change_password`, `totp_secret`, `totp_enabled` (+ index `idx_users_site_id`, `idx_users_role_client`) ;
- `chatbot_sites` : `sector`, `horaires` (JSON), `notification_settings` (JSON) ;
- `users` : **`plan`** (VARCHAR(20) DEFAULT 'free', + index `idx_users_plan` — fondations, Mission 1).

Le même travail existe en SQL manuel : `migrations/postgresql/005_refonte_app_mia.sql` puis `006_fondations_extensibilite.sql` (contrat `IMPORT_MIGRATIONS_RAILWAY.sh`). Le `sector` d'un site se renseigne via la route admin existante `POST /api/chatbot/sites/{site_id}/configure`. La seed des flags (`fonctionnalites`) est jouée au boot par `backend/core/fonctionnalites.py::seed_fonctionnalites` — idempotente, elle n'écrase JAMAIS une ligne existante.

---

## 13. Dépendance 2FA

`pyotp==2.9.0` (requirements.txt) — installation vérifiée en venv vierge, **zéro dépendance transitive**. Import **paresseux** uniquement (à l'intérieur des fonctions de vérification) : l'absence de la bibliothèque est un échec fermé de la 2FA (403), jamais une panne de démarrage (leçon de l'incident du 17/09).

---

## 14. Tests de garantie (suite `pytest`)

- `backend/api/test_refonte_app_mia.py` — B1-B3 : flux complet provisionnement → connexion → changement forcé → **2FA** → accès aux données ; **isolation multi-tenant explicite** (site A demande site B → 404, y compris en RGPD) ; hiérarchie des rôles ; refus du `system_prompt` ; `/orders` état explicite ; rate limiting 429 ; migration au boot idempotente.
- `backend/chatbot/test_refonte_declencheurs.py` — B4 : les trois événements, réglages par type (défauts sensibles), les **trois états de canal** (envoyé / échec / non configuré), mode arrière-plan non bloquant, aucun nom d'agent dans les notifications.
- `backend/api/test_fondations_extensibilite.py` — fondations d'extensibilité (47 tests) : seed idempotente, `/me` enrichi, catalogue de démonstration, verrou 403 explicite end-to-end, `/subscribe` sans clés, webhook Jeko signé, tracking (batch, dédup, agrégats scopés), WhatsApp/RCS inactifs sans appel réseau, webhook WhatsApp (hub.challenge + statuts signés), migration `users.plan`.

---

## 15. Plans et fonctionnalités (fondations d'extensibilité)

### 15.1 `GET /api/client/v1/plans`

Auth : Bearer (accessible pendant le changement forcé). **200** — catalogue de démonstration explicite tant que la tarification n'est pas décidée :

```json
{
  "catalogue": "démonstration",
  "note": "Catalogue de démonstration : la tarification et le modèle d'abonnement ne sont pas décidés…",
  "plans": [
    {"plan": "free", "niveau": 1,
     "fonctionnalites": [{"cle": "notifications_push", "etat": "actif", "description": "…"}]},
    {"plan": "premium", "niveau": 2, "fonctionnalites": […]},
    {"plan": "pro", "niveau": 3, "fonctionnalites": […]}
  ]
}
```

Chaque plan liste les fonctionnalités qu'il couvre avec leur état RÉEL (`actif`/`inactif`) — rien n'est vendu tant que ce n'est pas branché (C2).

### 15.2 Le verrou `exiger_fonctionnalite` (référence backend)

Une route marquée répond **403 avec corps PLAT** :

```json
{"detail": "fonctionnalité verrouillée", "fonctionnalite": "…",
 "plan_requis": "premium", "plan_actuel": "free", "raison": "…"}
```

L'ISOLATION PASSE D'AVANT LE VERROU : un compte qui demande un site étranger reçoit 404, jamais la raison du verrou. Recette d'extension : `EXTENSIBILITE.md §1`.

### 15.3 `GET /api/client/v1/sites/{site_id}/analytics/export`

Auth : Bearer + `require_site_owner` + **verrou `analytics_export`** (plan `free`, actif — exemple end-to-end du verrou). Query `period_days` (1-365). 200 :

```json
{"export": true, "format": "json", "fonctionnalite": "analytics_export",
 "genere_le": "ISO", "donnees": {…les analytics du site, même forme que §4.5…}}
```

---

## 16. Abonnement Jeko (pré-implémenté, fournisseur non configuré)

### 16.1 `POST /api/client/v1/subscribe`

Auth : Bearer. Corps : `{"plan": "premium|pro"}` (`free` ne se souscrit pas → 400 ; plan inconnu → 400 ; plan déjà actif → 400).

**Sans clés `JEKO_API_URL` / `JEKO_API_KEY` (état actuel) — 200, dégradation propre** :

```json
{"statut": "non_configure",
 "raison": "fournisseur d'abonnement Jeko non configuré (JEKO_API_URL / JEKO_API_KEY absents)…",
 "abonnement_id": 7, "plan": "premium"}
```

L'intention est ENREGISTRÉE en table `abonnements` (statut `intention`) : rien n'est perdu, aucune promesse n'est faite.

**Avec clés (sandbox)** : appel REST `POST {JEKO_API_URL}/subscriptions` → 200 `{"statut": "en_attente_paiement", "abonnement_id": …, "reference_fournisseur": "…", "plan": …}`. Fournisseur injoignable ou en erreur → **502 explicite**, intention enregistrée (statut `echec_fournisseur`). Rate limit 5/300 s. Tracé en audit.

### 16.2 `POST /api/webhooks/jeko` (public, signature OBLIGATOIRE)

Contrat : en-tête `X-Jeko-Signature: sha256=<hmac-sha256 hex du corps brut avec JEKO_WEBHOOK_SECRET>`, corps `{"reference": "…", "statut": "en_attente|actif|annule|echec"}`.

| Cas | Réponse |
|---|---|
| `JEKO_WEBHOOK_SECRET` absent | **400** — un webhook non signé n'est jamais accepté |
| signature absente/invalid | **400** `{"detail": "signature webhook invalide"}` |
| corps non JSON | 400 |
| `reference`/`statut` manquants | 422 |
| statut inconnu | 422 |
| référence inconnue | 200 `{"ok": false, "raison": …}` + trace d'audit (pas de tempête de relances) |
| `statut: "actif"` | 200 — abonnement passe `actif` ET **`user.plan` est élevé** (seul endroit où un plan s'active) |

`statut: "annule"` met la ligne à jour SANS toucher au plan : la politique de churn n'est pas décidée (`EXTENSIBILITE.md §5`). Toute transition est tracée en audit (`webhook_jeko`).

---

## 17. Tracking applicatif (usage de l'APP — jamais les conversations visiteurs)

### 17.1 `POST /api/client/v1/analytics/event` — batch, public OU authentifié

Corps : `{"installation_id": "…", "evenements": [1 à 500 × {"event_id", "type", "date_evenement", "site_id"?, "metadata"?}]}`.

- `event_id` : **UUID produit par l'app** — clé de déduplication : un rejeu (retour du réseau hors ligne) est ignoré silencieusement ;
- `type` : `install | app_open | session_start | session_end | screen_view | feature_use | notification_open | upgrade_intent | consent` (type inconnu → 422 en nommant la liste ; extensible côté backend uniquement) ;
- `date_evenement` : horodatage **CLIENT** (local-first) ; la date de réception serveur est posée par la base ;
- `metadata` : objet JSON borné à **4 Ko** — AUCUNE donnée personnelle du visiteur final (c'est l'usage de l'app) ;
- avant connexion, `installation_id` suffit (aucun jeton) ; avec un jeton valide, `user_id` et `site_id` sont remplis depuis le compte.

200 : `{"ok": true, "recus": 3, "acceptes": 2, "doublons_ignores": 1}`. Rate limit 30/60 s.

### 17.2 `GET /api/client/v1/analytics/app` — agrégats du propriétaire, SCOPÉS à son site

Query : `period_days` (1-365, défaut 30). Un compte client ne peut PAS demander un autre site (→ 404, isolation) ; l'admin ePerformance DOIT passer `?site_id=…` (400 sinon).

```json
{
  "site_id": "…", "periode": {"jours": 30, "depuis_reception": "ISO"},
  "installations": {"total": 12, "par_jour": [{"date": "2026-09-19", "total": 2}]},
  "taux_ouverture": 0.83,
  "sessions_moyennes_par_installation": 3.4,
  "ecrans_plus_vus": [{"ecran": "accueil", "total": 120}],
  "derniere_activite": "ISO",
  "evenements_par_type": {"app_open": 40, "install": 12, …}
}
```

Définitions : installations = `installation_id` distincts vus dans la période (borne par la date de réception serveur) ; taux d'ouverture = installations ayant émis `app_open` / installations ; par jour = `install` groupés par la date CLIENT (local-first) ; écrans = `screen_view` agrégés par `metadata.ecran`.

---

## 18. Canaux WhatsApp et RCS (pré-implémentés, INACTIFS par défaut)

Aucun envoi ne part tant que les flags ne sont pas posés — **aucun changement de code à l'activation** (`EXTENSIBILITE.md §2`) :

| Canal | État tant que non activé | Activation |
|---|---|---|
| `whatsapp` | `etat_canal` → `non configuré : canal DÉSACTIVÉ — WHATSAPP_ENABLED n'est pas à true…` ; tout envoi → `non_configure`, **sans appel réseau** | clés Meta + `WHATSAPP_ENABLED=true` |
| `rcs` | idem avec `RCS_ENABLED` (structure texte + cartes riches déclarative, fallback SMS déclaratif) | accès fournisseur + `RCS_ENABLED=true` |

Webhooks WhatsApp (`/api/webhooks/whatsapp`) : `GET` = vérification Meta (`hub.challenge`, jeton `WHATSAPP_WEBHOOK_VERIFY_TOKEN`) ; `POST` = statuts `sent/delivered/read/failed`, signature `X-Hub-Signature-256` validée si `WHATSAPP_APP_SECRET` est posé (403 sinon), chaque statut tracé dans `chatbot_notification_logs` (sujet `statut_fournisseur: …`).

Où poser les clés : Railway → Variables (production) ou `.env` Docker (déjà déclaré à vide). Liste complète des variables nouvelles : `EXTENSIBILITE.md §6`.

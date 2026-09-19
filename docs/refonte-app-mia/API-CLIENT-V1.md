# API CLIENT V1 — Contrat de l'app Mia (backend)

**Date** : 2026-09-19 · **Chantiers** : B1 (provisionnement) · B2 (rôles scopés + 2FA + audit) · B3 (API client) · B4 (déclencheurs de notification)
**Base URL production** : `https://api.eperformance.pro` · **Préfixe client** : `/api/client/v1` (versionnement : toute rupture ira en v2)
**Destinataire de ce document** : l'agent SITE — ce sont les DONNÉES des écrans de l'app Mia.

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
  "tfa": {"active": true, "requise": true}
}
```

`tfa.requise` vaut vrai pour `client_admin` — l'app affiche l'écran de configuration tant que `tfa.active` est faux.

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
| 403 | rôle insuffisant, compte non provisioné, `must_change_password` actif, 2FA manquante pour `client_admin`, compte désactivé |
| 404 | ressource inexistante **ou appartenant à un autre site** (isolation — indiscernables volontairement) |
| 422 | validation (bornes, types, types de notification inconnus) |
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
| `/api/chatbot/message` | 12 / 60 s |

429 : `{"detail": "Trop de requêtes. Réessayez dans un instant."}` — l'app doit proposer une relance temporisée.

---

## 12. Schéma de données (migration)

**Tables nouvelles** (créées par `create_all`) : `audit_log`, `client_notifications`.

**Colonnes ajoutées à des tables EXISTANTES** — le piège du projet : `init_db()` fait `create_all` au boot, qui crée les tables absentes mais **ne modifie jamais une table existante**. La migration est donc appliquée AU BOOT par `backend/core/migrations_boot.py` (inspecteur SQLAlchemy + `ALTER TABLE`, idempotent, journalisé) :

- `users` : `nom`, `site_id`, `role_client`, `must_change_password`, `totp_secret`, `totp_enabled` (+ index `idx_users_site_id`, `idx_users_role_client`) ;
- `chatbot_sites` : `sector`, `horaires` (JSON), `notification_settings` (JSON).

Le même travail existe en SQL manuel : `migrations/postgresql/005_refonte_app_mia.sql` (contrat `IMPORT_MIGRATIONS_RAILWAY.sh`). Le `sector` d'un site se renseigne via la route admin existante `POST /api/chatbot/sites/{site_id}/configure`.

---

## 13. Dépendance 2FA

`pyotp==2.9.0` (requirements.txt) — installation vérifiée en venv vierge, **zéro dépendance transitive**. Import **paresseux** uniquement (à l'intérieur des fonctions de vérification) : l'absence de la bibliothèque est un échec fermé de la 2FA (403), jamais une panne de démarrage (leçon de l'incident du 17/09).

---

## 14. Tests de garantie (suite `pytest`)

- `backend/api/test_refonte_app_mia.py` — B1-B3 : flux complet provisionnement → connexion → changement forcé → **2FA** → accès aux données ; **isolation multi-tenant explicite** (site A demande site B → 404, y compris en RGPD) ; hiérarchie des rôles ; refus du `system_prompt` ; `/orders` état explicite ; rate limiting 429 ; migration au boot idempotente.
- `backend/chatbot/test_refonte_declencheurs.py` — B4 : les trois événements, réglages par type (défauts sensibles), les **trois états de canal** (envoyé / échec / non configuré), mode arrière-plan non bloquant, aucun nom d'agent dans les notifications.

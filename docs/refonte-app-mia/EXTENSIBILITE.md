# EXTENSIBILITÉ — Contrat des fondations de l'app Mia

**Date** : 2026-09-19 · **Principe** : les fondations maintenant, l'activation plus tard — accueillir les fonctionnalités premium, l'abonnement Jeko, WhatsApp, RCS et le tracking **sans refactor, sans changement de code à l'activation**.
**Public** : le propriétaire (K. Stéphane Ballo) et tout agent qui étendra le backend.

> Règle transversale (C2) : **ne jamais vendre ce qui n'existe pas**. Les états `non configuré` / `désactivé` / `disponible: false` sont le motif établi du projet : une chose non branchée répond un état explicite, jamais une erreur silencieuse, jamais une réussite annoncée à tort.

---

## 1. Ajouter une fonctionnalité premium (exemple end-to-end)

Trois pièces, toutes déjà en place et démontrées par un exemple RÉEL du code (`analytics_export`) :

1. **Le flag en seed** — `backend/core/fonctionnalites.py`, liste `FONCTIONNALITES_DEPART` :

```python
{
    "cle": "rapports_avances",
    "plan_minimum": PLAN_PREMIUM,
    "active": False,          # INACTIF tant que le propriétaire ne l'active pas
    "description": "Rapports avancés hebdomadaires",
},
```

La seed au boot (`seed_fonctionnalites`) est **idempotente** : elle crée la ligne absente, n'écrase JAMAIS une ligne existante (les activations survivent aux redéploiements). La table `fonctionnalites` est créée par `create_all` (table nouvelle — pas de piège).

2. **La route marquée du verrou** — dans `backend/api/routes/client.py` :

```python
from backend.core.fonctionnalites import exiger_fonctionnalite, exiger_fonctionnalite_site

# Route compte-level :
@router.post("/rapports")
async def generer_rapport(
    _verrou: None = Depends(exiger_fonctionnalite("rapports_avances")),
    ...,
): ...

# Route de site — l'ISOLATION passe AVANT le verrou (un étranger reçoit 404,
# jamais la raison du verrou) :
@router.get("/sites/{site_id}/rapports")
async def rapports_du_site(
    site_id: str,
    db: Session = Depends(get_db),
    _verrou: None = Depends(exiger_fonctionnalite_site("rapports_avances", ROLE_CLIENT_READER)),
): ...
```

Une clé inconnue du catalogue fait échouer l'IMPORT (`ValueError`) — le smoke test pre-push l'affiche en 2 s, jamais un 500 en production.

3. **L'app la voit automatiquement** — `GET /api/client/v1/me` renvoie au premier niveau :

```json
{
  "plan": "free",
  "fonctionnalites_actives": ["notifications_push", "analytics_export", "ia_en_direct"],
  "fonctionnalites_verrouillees": [
    {"cle": "rapports_avances", "plan_requis": "premium", "raison": "fonctionnalité inactive"},
    {"cle": "whatsapp_notifications", "plan_requis": "premium", "raison": "fonctionnalité inactive"},
    {"cle": "rcs_messages", "plan_requis": "premium", "raison": "fonctionnalité inactive"},
    {"cle": "abonnement_jeko", "plan_requis": "premium", "raison": "fonctionnalité inactive"}
  ]
}
```

Si l'appelant tente la route verrouillée, il reçoit **403 avec corps PLAT** (contrat, pas un texte à parser) :

```json
{"detail": "fonctionnalité verrouillée", "fonctionnalite": "rapports_avances",
 "plan_requis": "premium", "plan_actuel": "free", "raison": "plan premium requis"}
```

L'écran d'upgrade de l'app lit `plan_requis` directement. **Aucun changement côté app** quand on ajoute un flag : elle découvre par /me.

Preuve vivante : la route `GET /api/client/v1/sites/{site_id}/analytics/export` est marquée `exiger_fonctionnalite_site("analytics_export", …)` — les tests `backend/api/test_fondations_extensibilite.py::TestVerrou` prouvent le 200 (flag actif + plan suffisant), le 403 (flag inactif), le 403 (plan insuffisant) et le 404-avant-403 (isolation d'abord).

---

## 2. Activer un canal (WhatsApp, RCS) — aucun changement de code

Les deux canaux sont **pré-implémentés et inactifs par défaut**. L'activation est une opération de CONFIGURATION uniquement :

| Étape | WhatsApp (Meta Cloud API) | RCS |
|---|---|---|
| 1. Poser les clés | `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_WABA_ID` (Railway → Variables, ou `.env` Docker) | `RCS_AGENT_ID`, `RCS_API_URL`, `RCS_API_KEY` |
| 2. Basculer le flag | `WHATSAPP_ENABLED=true` | `RCS_ENABLED=true` |
| 3. Redémarrer | le service redéploie/redémarre, `etat_canal` passe à `configuré` | idem |
| 4. Webhook (optionnel) | enregistrer l'URL dans Meta avec `WHATSAPP_WEBHOOK_VERIFY_TOKEN` ; poser `WHATSAPP_APP_SECRET` pour la validation des signatures | selon le fournisseur choisi |

Aucun code à écrire : `etat_canal` (calculé SANS appel réseau) reflète l'état, et `envoyer(canal, …)` passe de `non_configure` à `envoye` tout seul. Les templates WhatsApp structurés (`nouveau_lead`, `escalade`) sont définis dans `backend/chatbot/notifications.py::TEMPLATES_WHATSAPP` — les noms doivent correspondre à des templates **créés et approuvés** dans Meta Business Manager (catégorie UTILITY, guide complet : `backend/communication/providers/whatsapp_provider.py`).

**Où se posent les clés** :
- **Railway (production actuelle)** : `railway variables --set "NOM=valeur"` ou l'interface Railway → service → Variables ;
- **Docker (bascule serveur dédié)** : `/home/ballo/OX6A/docker-unified/unified-ia-backend/.env` — les variables nouvelles y sont déjà déclarées À VIDE (même motif que les VAPID) ; remplir la valeur à l'activation.

Détail important : le jeton Meta s'appelle `WHATSAPP_ACCESS_TOKEN` dans tout le code existant (c'est le nom reconnu par `etat_canal` depuis la tâche 6.5) — ne pas introduire un second nom pour la même chose. Le destinataire par défaut des envois WhatsApp est `WHATSAPP_NOTIF_DESTINATAIRE` (motif `BREVO_NOTIF_EMAIL`) : sans lui, l'envoi répond `non configuré` avec la raison.

---

## 3. Ajouter un événement de tracking

Le tracking applicatif décrit l'USAGE DE L'APP (jamais les conversations visiteurs). Un nouveau type d'événement se déclare à UN SEUL endroit :

1. `backend/api/routes/client.py` → tuple `TYPES_EVENEMENTS_TRACKING` : ajouter `"partage_effectue"` ;
2. redéployer — c'est tout ;
3. l'app envoie le batch comme pour les autres types, l'événement apparaît automatiquement dans `evenements_par_type` de `GET /api/client/v1/analytics/app`.

Contrat d'envoi (inchangé) : `POST /api/client/v1/analytics/event`, batch de 1 à 500 événements, chaque événement portant son `event_id` (UUID produit par l'app — **déduplication** : un rejeu au retour du réseau est ignoré silencieusement), `date_evenement` horodatée **côté client** (local-first), métadonnées bornées à 4 Ko, **aucune donnée personnelle du visiteur final**. Un type inconnu répond 422 en nommant la liste acceptée — l'app sait immédiatement qu'elle est en avance sur le backend.

---

## 4. Jeko — du sandbox au réel

L'abonnement est une **abstraction de fournisseur** : le backend connaît trois variables, aucune URL ni clé en dur.

| Variable | Rôle |
|---|---|
| `JEKO_API_URL` | Base de l'API du fournisseur (ex. sandbox : `https://sandbox.jeko…`) |
| `JEKO_API_KEY` | Clé d'API (en-tête `Authorization: Bearer …`) |
| `JEKO_WEBHOOK_SECRET` | Secret HMAC-SHA256 de signature des webhooks |

**Flux complet** (implémenté, testé) :

1. L'app appelle `POST /api/client/v1/subscribe` `{"plan": "premium"}`.
2. **Sans clés** (aujourd'hui) : réponse 200 `{"statut": "non_configure", "raison": …}` ET l'intention est enregistrée en table `abonnements` (statut `intention`) — rien n'est perdu, aucune promesse n'est faite.
3. **Avec clés (sandbox)** : le backend appelle `POST {JEKO_API_URL}/subscriptions` (payload : plan, e-mail, référence interne `user:{id}`, callback) → ligne `abonnements` statut `en_attente` + `reference_fournisseur`.
4. Le fournisseur confirme par `POST /api/webhooks/jeko` avec l'en-tête `X-Jeko-Signature: sha256=<hmac hex du corps brut avec JEKO_WEBHOOK_SECRET>` et le corps `{"reference": …, "statut": "actif|annule|echec|en_attente"}`.
   - Sans secret posé : **400** (un webhook non signé n'est jamais accepté).
   - Signature invalide : **400**. Statut inconnu : **422**. Référence inconnue : 200 `{"ok": false}` + trace d'audit (pas de tempête de relances).
   - `statut: "actif"` : la ligne `abonnements` passe à `actif` ET `user.plan` est élevé — **c'est le seul endroit du backend où un plan s'active**.
5. Le plan est ensuite visible partout (`/me` → `plan`, verrous levés selon les flags).

**Passage sandbox → réel** : remplacer `JEKO_API_URL` par l'URL de production, permuter `JEKO_API_KEY`, régénérer `JEKO_WEBHOOK_SECRET` chez le fournisseur et le poser ici, puis activer le flag `abonnement_jeko` dans la table `fonctionnalites`. Aucun changement de code. Les intentions enregistrées pendant la période sans fournisseur restent en base : les traiter à la main à l'activation (elles portent `user_id` + `plan` demandé).

---

## 5. Points de décision NON tranchés (au propriétaire)

Tout ce qui suit est **délibérément ouvert** — les fondations les accueillent sans refactor, mais rien n'est branché ni promis :

| Décision | Options | Ce qui est déjà prêt |
|---|---|---|
| **Modèle d'abonnement** | mensuel, annuel, à l'usage, hybride | table `abonnements` (dates, statuts), webhook de cycle de vie ; aucun montant modélisé |
| **Plans** | combien ? noms ? (aujourd'hui : `free` / `premium` / `pro` en interne, `GET /plans` est un **catalogue de démonstration** explicite) | hiérarchie `HIERARCHIE_PLANS`, renommage = constante + données |
| **Tarification** | prix par plan, périodes d'essai, prix sectoriels ? | aucun prix dans le code ni en base (volontaire) |
| **Rétention / churn** | à l'annulation : plan descendu immédiatement ? en fin de période ? grace period ? | le webhook `annule` met le statut à jour SANS toucher au plan — la politique reste à décider (test qui l'explicite) |
| **Traitement des intentions** | relancer les `intention` enregistrées sans fournisseur ? les purger ? | elles sont conservées avec user_id + plan |

---

## 6. Variables d'environnement nouvelles (toutes VIDES par défaut)

À poser au moment de l'activation — jamais avant, jamais avec une valeur factice (dépôt public, `scripts/verifier-secrets.py` au pre-push). Elles sont déjà déclarées à vide dans le `.env` Docker.

| Variable | Canal/fonction | Rôle | Activation |
|---|---|---|---|
| `WHATSAPP_ENABLED` | WhatsApp | `true` = canal actif (absent/vide = désactivé) | Mission 3 |
| `WHATSAPP_ACCESS_TOKEN` | WhatsApp | Jeton Meta Cloud API (nom existant du projet) | Mission 3 |
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp | Identifiant du numéro émetteur (existant) | Mission 3 |
| `WHATSAPP_WABA_ID` | WhatsApp | Identifiant WhatsApp Business Account | Mission 3 |
| `WHATSAPP_APP_SECRET` | WhatsApp | Validation HMAC `X-Hub-Signature-256` des webhooks Meta | Mission 3 (webhook) |
| `WHATSAPP_WEBHOOK_VERIFY_TOKEN` | WhatsApp | Jeton de vérification GET `hub.challenge` (existant) | Mission 3 (webhook) |
| `WHATSAPP_NOTIF_DESTINATAIRE` | WhatsApp | Destinataire par défaut des notifications (motif `BREVO_NOTIF_EMAIL`) | Mission 3 |
| `RCS_ENABLED` | RCS | `true` = canal actif | Mission 4 |
| `RCS_AGENT_ID` | RCS | Identifiant de l'agent RCS chez le fournisseur | Mission 4 |
| `RCS_API_URL` | RCS | URL d'envoi du fournisseur (à choisir) | Mission 4 |
| `RCS_API_KEY` | RCS | Clé d'API du fournisseur RCS | Mission 4 |
| `RCS_FALLBACK_SMS` | RCS | `true` = fallback SMS DÉCLARÉ (la bascule d'envoi reste à implémenter avec le fournisseur final) | Mission 4 |
| `JEKO_API_URL` | Abonnement | Base de l'API Jeko (sandbox puis production) | Mission 1 |
| `JEKO_API_KEY` | Abonnement | Clé d'API (Bearer) | Mission 1 |
| `JEKO_WEBHOOK_SECRET` | Abonnement | Secret HMAC des webhooks (signature OBLIGATOIRE) | Mission 1 |

**Aucune de ces variables n'a de valeur par défaut autre que vide** : le comportement sans elles est l'état explicite (`non configuré` / `désactivé`), jamais une erreur, jamais un appel réseau.

---

## 7. Ce qui est testé (garantie)

`backend/api/test_fondations_extensibilite.py` (47 tests) — seed idempotente, /me enrichi, catalogue de démonstration, verrou 403 explicite end-to-end (flag inactif, plan insuffisant, isolation avant verrou), /subscribe sans clés (`non_configure` + intention enregistrée), webhook Jeko (400 sans secret, 400 sans signature, 400 signature invalide, 422 statut inconnu, 200 signé → plan élevé, annulation sans politique de churn), tracking (batch public, déduplication par rejeu, enrichissement authentifié, 422 type inconnu, agrégats scopés — le site B ne fuit pas, admin 400/200), WhatsApp (désactivé sans appel réseau, payload template Meta, webhook hub.challenge + statuts signés tracés), RCS (désactivé sans appel réseau, variables nommées, structure texte + cartes, fallback déclaratif jamais une réussite), migration `users.plan` idempotente.

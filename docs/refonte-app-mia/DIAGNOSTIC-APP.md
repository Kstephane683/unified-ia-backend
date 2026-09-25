# DIAGNOSTIC — APP MIA RÉELLE (ÉTAPE 1)

**Agent CHATBOT · 2026-09-25 · STATUT : en attente de validation de Ballo.**
Conformément à la consigne : aucune construction lancée, rien supprimé (rien à supprimer — voir §0), le diagnostic seul est livré et poussé.

---

## 0. État des lieux mesuré — les prémisses, corrigées par mesure

La consigne partait de trois prémisses. Je les ai vérifiées avant d'exécuter ; deux sont exactes, une méritait une précision.

1. **L'app servie sur `/app/` est la maquette validée à l'identique** — exact. Mesuré le 25/09 : 57 334 octets servis, 7 marqueurs « Mia en direct », zéro `login/json`, zéro `otpauth`. C'est le commit `ae1f61b` de SITE (01:45, sur ordre direct de Ballo, consigné au journal partagé) : le stub Preact a déjà été supprimé, la maquette copiée telle quelle, plus une plomberie invisible d'installation (manifeste, apple-touch-icon, service worker de coquille).
2. **L'app actuelle ne fait rien** — exact pour la page servie (aucun `fetch()`, aucune URL). Précision importante : **les acquis fonctionnels ne sont pas perdus**. Ils sont dans l'historique git du dépôt `eperformance-mia` et je les porterai depuis là (§3). La suppression de SITE (`ae1f61b`) les a retirés du servi, pas de l'histoire.
3. **Le dépôt local était en retard sur origin** — mesuré : mon clone restait à `c22a4fd` alors qu'`origin/main` est à `ae1f61b` (les deux commits de SITE). Resynchronisé (fetch + rebase) avant toute écriture.

---

## 1. Ce que contient la maquette validée (`app-mia.html`, 56 821 o)

**Écrans** (commutables par `data-screen`/`id`) :
- `ecran-accueil` — salutation, carte d'actions surélevée, bouton central « Mia en direct » (ouvre `modale-direct`)
- `ecran-conversations` — liste + filtres (Toutes · Non lues 3 · Escaladées 1 · Avec lead 2), état vide filtré
- `ecran-analyses` — vues d'usage
- `ecran-reglages` — cartes : Message d'accueil · Horaires et fermetures · Notifications · Analytics de l'application · Données des visiteurs (export/suppression)
- **Abonnement** (`groupe-abonnement`) : plan actuel + badge + note, `liste-verrous`, `matrice-canaux`, `interrupteur-consent` + note de consentement
- **Modales** : `modale-direct` (fil, saisie, envoi, voile) et `modale-upgrade` (titre, raison, avantages, `bouton-souscrire`, `flux-paiement`, `simuler-cles`, `resultat-non-configure`)

**Identité** : DM Sans + Cormorant Garamond auto-hébergées, ~24,6 Ko de CSS inline (jetons eperf), bascule thème clair/sombre, bascule hors-ligne.

**Interactions** : simulées en local — aucun `fetch()`, aucune URL externe. C'est assumé : la maquette est la référence visuelle et structurelle, pas un client API.

**Absent de la maquette** : l'écran **Entraînement (F/G)** — gestion des connaissances propriétaire et instructions sectorielles. Il n'a jamais existé dans la maquette ; il existait dans la v1 (§3). Son placement est à arbitrer (Q1).

---

## 2. Ce que le contrat API-CLIENT-V1 expose (18 routes uniques)

Présent et suffisant pour la v1 de l'app :
`GET /me` · `POST /password` · 2FA `setup`/`activate`/`disable` (`otpauth_uri` → QR rendu client) · `GET /plans` · `POST /subscribe` · par site : `settings`, `secteur` (GET/PUT), `connaissances` (GET/POST/DELETE), `conversations`, `notifications`, `analytics/export` · `analytics/app` · `analytics/event` (tracking local-first).
Auth : `POST /api/auth/login/json` ({email, password}) + flux `2fa_requise`.

**Manquante** : le branchement réel de « Mia en direct ». Deux voies mesurées :
- le flag `test:true` dont parle SITE (journal 01:20) n'est **pas traité côté backend** — recherche exhaustive sur `backend/` (`est_test`, `mode_test`, `is_test`, `"test"`) : néant. Un `POST /message` d'aujourd'hui crée une conversation visiteuse réelle, pollue les statistiques et l'escalade ;
- le flag de fonctionnalité `ia_en_direct` existe déjà dans les fondations d'extensibilité (`fonctionnalites_actives`).

→ Ma recommandation (Q2) : une **route client dédiée** `POST /api/client/v1/sites/{site_id}/direct`, authentifiée, sous flag `ia_en_direct`, conversations marquées « test » et exclues des statistiques/escalades. Le contrat `API-CLIENT-V1.md` serait amendé d'une route (mon périmètre), après validation.

---

## 3. Les acquis à porter (ils sont dans l'historique git — rien à réinventer)

| Acquis | Source (commit `eperformance-mia`) | Destination dans la nouvelle app |
|---|---|---|
| Fix connexion `{email, password}` (le 422 attrapé par TEST.2) + gestion `2fa_requise` | `c22a4fd` | Écran connexion |
| QR 2FA : `/2fa/setup` → `otpauth_uri` → QR rendu client (qrcode-generator vendorisé) → activate, secret affiché une seule fois | `2baf4ab` | Réglages — sécurité |
| Écran Entraînement F/G (CRUD Q/R + documents, secteur canonique, routes `/sites/{id}/connaissances` + `/secteur`) | `37ca8b8` | Placement à arbitrer (Q1) |
| Icônes eP + apple-touch-icon 180 | `9b2ea56` | Déjà servis par la plomberie actuelle ; à reprendre dans le nouveau shell |
| Shell natif iOS (100dvh, safe-areas, overscroll, anti double-tap, appui scale .96) | `2baf4ab` | Shell du nouveau build |
| Tracking local-first `suivi('screen_view', …)` | v1 | Composable unique + `POST /analytics/event` |
| Leçon `b8fedbb` : base API **en absolu** (le `/api` relatif pointait le domaine Pages) | `b8fedbb` | Constante unique d'environnement |
| Bandeau hors-ligne + service worker de coquille | plomberie `ae1f61b` | À reprendre telle quelle |

---

## 4. Dépendances

- **SITE** : la maquette validée est la référence figée — je ne modifie aucun écran, aucune identité ; polices auto-hébergées déjà dans le dépôt ; jetons eperf consommés, pas redéfinis.
- **Backend (moi)** : les 18 routes ci-dessus sont en production (406 tests verts). Ajout possible d'une route (Q2) après validation.
- **Propriétaire (Ballo)** : arbitrages du §5 + test iPhone final.

---

## 5. Questions ouvertes — arbitrages Ballo

| # | Question | Ma recommandation |
|---|---|---|
| Q1 | Où pose-t-on l'écran **Entraînement** (absent de la maquette) ? | Une carte dans **Réglages** (« Entraîner Mia ») + l'entrée d'action de l'accueil réservée admin, comme en v1 |
| Q2 | Branchement de **« Mia en direct »** | Route client dédiée authentifiée sous flag `ia_en_direct`, conversations marquées test — PAS de `test:true` sur `/message` public (non traité, mesuré) |
| Q3 | **Domaine API** : mesuré le 25/09, les préflights via `api.eperformance.pro` sont répondus par le cache de bord LWS **sans aucun en-tête CORS** (et `cache-control` d'un an sur OPTIONS) ; en direct Railway, `access-control-allow-origin: https://mia.eperformance.pro` est présent sur les deux routes testées | L'app appelle Railway en absolu (comme la v1) tant que le propriétaire ne pose pas une règle edge/proxy pour `/api` (pass-through sans cache) — geste cPanel, hors de mon périmètre |
| Q4 | **Où vit le build Preact** ? `eperformance-mia` est un dépôt Pages statique | Build local commité (comme la v1 : vendor preact/htm) — zéro pipeline à maintenir ; une GitHub Action si tu préfères des sources séparées |
| Q5 | Que fait **« Souscrire »** tant que la tarification n'est pas tranchée (décision en attente au registre) ? | Afficher l'état réel de l'API (plan actuel + verrous) et laisser `POST /subscribe` répondre son état explicite — pas de simulation d'achat |
| Q6 | **Test iPhone réel** | Je livre, tu retestes (flux complet au premier provisionnement, comme en v1) |

---

## 6. Plan de construction proposé (après ta validation — pas avant)

1. Squelette Preact + shell natif + thème/polices depuis la maquette (écrans fidèles, aucun changement d'identité)
2. Connexion complète (`login/json` + `2fa_requise` + QR setup) — acquis portés
3. Accueil + carte d'actions + « Mia en direct » branché selon Q2
4. Conversations (filtres) + notifications
5. Analyses (`analytics/app` + export)
6. Réglages (settings, secteur, abonnement selon Q5, 2FA, données visiteurs)
7. Entraînement F/G selon Q1 (acquis portés)
8. Service worker / manifeste / icônes (plomberie reprise), tracking sur chaque écran
9. Déploiement Pages + vérification des domaines + ton test iPhone

Rien de tout cela ne démarre sans ta validation du diagnostic.

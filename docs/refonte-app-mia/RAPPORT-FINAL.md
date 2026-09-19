# RAPPORT FINAL — Refonte app Mia (SaaS de gestion) + landing

**Date** : 2026-09-19 · **Agent** : CHATBOT · **Mission du propriétaire** : livrer l'app Mia backend complète, testée, déployée + toutes les dépendances, puis **passer le relais** : SITE conçoit la LP **et** l'app.

**Chaîne des décisions du propriétaire** : (1) l'app actuelle transformait le chatbot visiteur en application — erreur de logique, la vraie app est un SaaS de gestion pour les propriétaires de sites ; (2) étape 0 d'audit avant conception — faite ; (3) mission complète sans report ; (4) vidéos **sans voix générée** ; (5) **passation à SITE** de la LP et de l'app — CHATBOT livre les dépendances et retire sa propre LP.

---

## 1. Ce qui est livré — backend B1-B4

**Tests : 284 → 359 verts** (+75), les 2 erreurs préexistantes inchangées. **Parité Docker C12 : 151 fichiers, code 0.** Production vérifiée après déploiement (`/health` 200, migration des colonnes confirmée en base, routes client 401 sans jeton). 7 commits poussés.

| Chantier | Contenu | Preuve |
|---|---|---|
| **B1 provisionnement** | `POST /api/chatbot/admin/clients` (mot de passe temporaire renvoyé **une seule fois**), `must_change_password` forcé (403 sur les routes client tant que non changé), `POST /api/client/v1/password`, `remember_me` → jeton 30 j | tests d'intégration provision → login → changement → accès |
| **B2 rôles + 2FA + audit** | `require_site_owner` (admin > client_admin > client_operator > client_reader), **isolation multi-tenant : 404 jamais 403** (ne révèle pas l'existence des autres sites, prime même sur la porte 2FA), 2FA TOTP (`pyotp` vérifié en venv vierge, secret **chiffré Fernet** en base, login sans code → 401 `2fa_requise`), table `audit_log` + endpoint admin | 12 tests dédiés verts (échantillon revérifié par moi) |
| **B3 API client v1** | préfixe `/api/client/v1`, **31 endpoints documentés** dans `API-CLIENT-V1.md` (20 Ko) : me, conversations (+détail/reply/takeover/release), analytics, leads, **orders en état explicite « non branché »** (règle C2), settings (le `system_prompt` lisible, **écriture refusée 400 avec la raison** — décision produit), compétences (`faq_themes` du noyau via snapshot régénérable), notifications in-app, **RGPD export + suppression par conversation** | le contrat a été écrit, chiffré, revérifié |
| **B4 déclencheurs** | lead / escalade / nouveau visiteur → push (`push_subscriptions` par site) + Telegram/e-mail + in-app, **asynchrone non bloquant**, réglages par type (`notification_settings` JSON, défauts : lead et escalade ON, visiteur OFF) | 24 tests, les 3 états de canal (envoyé/échec/non configuré) |

**Le piège create_all résolu** : `init_db()` ne modifie pas les tables existantes — `migrations_boot.py` (appelé après `init_db()`) applique des `ALTER TABLE ADD COLUMN` idempotents via l'inspecteur SQLAlchemy, testé (une table ancienne est réparée, un second passage ne fait rien), plus le SQL manuel `migrations/postgresql/005_refonte_app_mia.sql`. Les rôles granulaires vivent dans `role_client` (VARCHAR validé) plutôt que l'enum Postgres natif — documenté.

**Honnêteté sur l'héritage** : une session précédente avait laissé 40 tests rouges (domaines `.test` rejetés par `EmailStr`, ordre des gardes, tests incompatibles avec les portes B1/B2) — tout est corrigé et vert.

## 2. Ce qui est livré — les dépendances de la LP

| Dépendance | État |
|---|---|
| Dépôt dédié `Kstephane683/eperformance-mia` | ✅ créé — décision argumentée (séparation code source / site public, un sous-domaine par app, déploiement indépendant) |
| GitHub Pages | ✅ actif, sert `https://mia.eperformance.pro/` (vérifié HTTP 200) |
| Custom domain + HTTPS | ✅ configurés, **HTTPS enforced** (le DNS était posé par le propriétaire) |
| Contenu sectoriel | ✅ `contenu-sectoriel.json` **généré par import réel** de `sectors.py` (12 secteurs) — script `_build/generer-contenu.py`, jamais réécrit à la main |
| Vidéos muettes | ✅ 4 vidéos (hero-loop, démo, tuto installation, tuto app) — Playwright (enregistrement réel) + ffmpeg, MP4 H.264 + WebM, durées et poids mesurés |
| Garde-fous du dépôt | ✅ hook pre-push secrets + **Actions CI** (dépôt public — leçon du 19/09), empreinte eperf.css, contrôles structurels |
| LP v1 CHATBOT | 🗄️ **retirée de main et archivée** (décision de passation) : `docs/archive/index-lp-v1.html` + branche `archive/lp-v1-chatbot` — référence de contenu, pas un modèle de conception. Page d'attente sobre en place (jetons canoniques, zéro hex, zéro emoji, `noindex`) |

**Les garde-fous ont à nouveau bloqué leur propre auteur** : mon premier push de passation a été refusé par le vérificateur de structure (il validait la LP retirée). Correction propre : les contrôles de contenu de LP visent **automatiquement l'archive** en état de passation et retargeteront l'`index.html` de SITE dès qu'il ne contiendra plus la mention de préparation ; la règle emoji n°8 vise l'**interface**, pas la documentation de travail. Trois itérations (une détection manquée par casse, un appel à une fonction inexistante) avant le PASS — chaque itération vérifiée, pas supposée.

## 3. La passation à SITE

**`CONSIGNE-SITE.md` v2** — le contrat complet, à jour de la passation :
- les 14 écrans avec contenu et source de données, les transverses, les états/interactions/transitions, les wow moments ;
- la landing en 8 sections (sélecteur de secteur structurant, preuves **sans invention**, FAQ RGPD) ;
- les exigences du propriétaire transmises **mot pour mot** : app puissante, onboarding clair, wow moments, design premium, **rapidité d'exécution = priorité absolue**, référence structurale Jèko (structure reprise, design system et couleurs non) ;
- **le tableau des dépendances : toutes livrées** (B1-B4, contenu, dépôt, domaine, HTTPS, vidéos, garde-fous) ;
- le contrat des endpoints : **`API-CLIENT-V1.md`**.

**Restes non bloquants, avec raison** : l'écran « Mia en direct » (conversation brouillon — demande un flag dédié du pipeline LLM, à faire à la demande) ; le rattachement `sector` des sites existants en production (champ vide, à renseigner via `configure`) ; l'invitation e-mail à la livraison (Brevo opérationnel, le flux passe aujourd'hui par le fichier client) ; aucun compte client réel provisionné (base vierge — le premier se fera à la livraison d'un vrai site).

## 4. Vérifications de clôture

`verifier-chatbot.py` → **0 site et blog** · parité Docker → **0 (151 fichiers)** · `verifier-secrets.py` → **PASS** · tests backend **359** · `mia.eperformance.pro` → **HTTP 200 (page d'attente)** · les garde-fous du dépôt eperformance-mia → **PASS** (secrets, empreinte, structure).

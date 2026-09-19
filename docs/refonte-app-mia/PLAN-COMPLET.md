# PLAN COMPLET — App Mia (SaaS de gestion) + landing sectorielle

**Date** : 2026-09-19 · **Agent** : CHATBOT · **Base** : `AUDIT-PREALABLE.md` (10 recommandations C1-C10, toutes intégrées ci-dessous).

---

## 1. Le produit en une phrase

**Mia** est un assistant conversationnel **contextuel au site** de chaque client (12 secteurs), et l'**application Mia** est l'outil dont ce client dispose pour **gérer SON chatbot** : voir ce qu'il dit, le régler, être prévenu, intervenir. La landing vend Mia **par métier**, avec ce qu'elle sait faire aujourd'hui — et ne promet que ce qui est branché.

**Deux sources de vérité, une règle** :
- le **contenu sectoriel vient du noyau** (`agent-ia-web/eperf_core/sectors.py` : intention, faq_themes, item) — la landing et l'app le **consomment**, jamais le réécrivent ;
- **« Mia répond » ≠ « Mia exécute »** : toute communication (landing, app, consignes) distingue ce que Mia répond aujourd'hui de ce qu'elle pourra exécuter après intégration. Aucune promesse opérationnelle sans support (C2).

---

## 2. Capacités sectorielles — validées contre le noyau

Les 12 secteurs clients (les 14 du noyau moins `blog` et `email`). Pour chacun : **intention** (du noyau) → ce que Mia **répond** aujourd'hui → ce qu'elle pourra **exécuter** (roadmap intégrations).

| Secteur | Intention du noyau | Mia répond (v1, branché) | Mia exécute (roadmap) |
|---|---|---|---|
| **restauration** | « Donner faim et lever le doute pratique : la carte, l'accueil… » | carte et plats (allergènes, régimes), horaires, réservation → **prise de contact**, groupes et événements privés, FAQ complète | réservation réelle (agenda), commande en ligne, liste d'attente |
| **hotellerie** | « Faire réserver une nuit : montrer les chambres… » | chambres (capacité, surface, vue, prix), arrivée/départ, équipements, accès, annulation → **demande de réservation** | réservation réelle, check-in digital, room service, upselling |
| **ecommerce** | « Faire commander : montrer le catalogue avec les prix » | produits (prix, tailles, matériaux), livraison, retours et remboursements, paiement, compte client → **capture de contact** sur panier abandonné | lecture des commandes du site (app, écran 8), récupération paniers automatisée, recommandations |
| **immobilier** | « Faire visiter : présenter les biens… » | biens (type, offre, prix), visite, financement, frais et notaire, estimation → **qualification du prospect** (budget, localisation, type) | agenda d'agent pour les visites, fiches envoyées automatiquement, CRM |
| **mlm** | « Faire rejoindre un réseau : expliquer comment on démarre » | démarrage et investissement, plan de rémunération en langage simple, produits, parrainage → **qualification + recrutement 24/7**, onboarding des nouveaux distributeurs | suivi d'activité du réseau, formations recommandées |
| **beaute** | « Vendre des soins à l'acte » | soins (catégorie, durée), produits utilisés, annulation et report → **prise de rendez-vous** (contact) | RDV réel avec agenda et rappels |
| **sante** | « Convertir une inquiétude en rendez-vous » | prise de rendez-vous (contact), remboursement et mutuelle, assurance, urgences → **tri et orientation**, rappels | RDV réel, préparation avant consultation |
| **education** | « Faire candidater : présenter les programmes » | programmes (niveau, durée, domaine), inscription et dossier, frais, diplômes et accréditations, calendrier | admission réelle, support étudiant automatisé |
| **evenementiel** | « Remplir une date : publier le programme, ouvrir la billetterie » | programme, billetterie et places, lieu et accès, prestataires et traiteurs → **devis en contact** | billetterie réelle, gestion des prestataires |
| **tourisme** | « Faire partir : présenter des séjours et des circuits » | séjours et circuits, devis et réservation (contact), formalités et visa, annulation, groupes | réservation réelle, documents de voyage |
| **artisan** | « Obtenir un devis : montrer les prestations, les chantiers » | prestations et chantiers, matériaux et finitions, délais et planning, zone d'intervention → **demande de devis** | devis réels, planning de chantier |
| **vitrine** (inclut « services professionnels » du plan) | « Présenter une activité de service qui se vend au contact » | déroulement d'une prestation, devis (contact), délais, zone d'intervention | prise de consultation, devis/facturation |

**Règles d'affichage** : les capacités « répond » sont les `faq_themes` du noyau, complétées de la qualification/capture/escalade qui sont déjà branchées. Les capacités « exécute » portent un badge « bientôt » sur la landing et apparaissent dans l'app comme « en préparation », jamais comme des réglages actifs.

---

## 3. L'application Mia — structure complète

### 3.1 Les 14 écrans (10 du plan + 4 de l'audit)

| # | Écran | Contenu | Source de données | Priorité |
|---|---|---|---|---|
| 0 | **Onboarding guidé** | 3 étapes à la première connexion : voici Mia (test direct) → ce qu'elle dit de votre site → où la régler | — | v1 |
| 1 | Connexion | identifiants de livraison, changement forcé du mot de passe temporaire, session 30 j + ré-authentification passkey après inactivité | `POST /api/auth/login` + provisionnement (chantier 1) | v1 |
| 2 | Accueil | **état vivant et actions du jour** : Mia en ligne, messages non lus, leads du jour, dernière escalade, accès direct « tester Mia » | analytics + conversations | v1 |
| 3 | Conversations | boîte de réception unifiée du site, filtres (non lu, escaladé, avec lead), recherche | `site_id` sur conversations | v1 |
| 4 | Détail conversation | historique complet, prise en main (existe : `human_active`), notes internes, tags | existant + notes/tags (chantier 3) | v1 |
| 5 | Notifications | alertes reçues, réglage des canaux (push app, e-mail, Telegram — les deux derniers **existent** dans `ChatbotSite`) | `notification_*` + déclencheurs (chantier 4) | v1 |
| 6 | Analytics | **historique et tendances** (distinct de l'Accueil) : volume, intents, taux de capture, escalades | `GET /analytics/{site_id}` | v1 |
| 7 | Configuration | système (prompt, message d'accueil), compétences activées, limites (rate limits), thème | `ChatbotSite` — tout existe | v1 |
| 8 | **Compétences de Mia** | ce que Mia sait faire **dans votre métier** : les thèmes FAQ du secteur, activables/désactivables (`allowed_intents`) | `allowed_intents` + `faq_themes` du noyau | v1 |
| 9 | **Horaires et disponibilités** | horaires d'ouverture, jours fermés, vacances — la donnée que Mia utilise pour répondre | **nouveau champ** `ChatbotSite.horaires` (chantier 3) | v1 |
| 10 | **Mia en direct (test)** | conversation brouillon avec sa propre Mia, non enregistrée — le test avant d'activer | message API + flag `test` | v1 |
| 11 | Commandes | **masqué hors e-commerce** — liste des commandes lues depuis le système du site | intégration site (roadmap « exécute ») | v2 |
| 12 | Prospects | **masqué hors immobilier/artisan/services** — pipeline des leads qualifiés | leads existants | v1.1 |
| 13 | Messages ePerformance | messages de l'admin (support, maintenance, nouvelles capacités) | **nouveau canal admin → client** (explicitement exclu de cette mission) | v2 |
| + | **Confidentialité (RGPD)** | export/suppression par conversation du visiteur final, durée de rétention visible | purge existante + routes (chantier 3) | v1 — C4 |

### 3.2 Transverses (du plan, arbitrage de l'audit)

Multi-sites (sélecteur de scope) · Rôles Admin/Opérateur/Lecteur par site · Notifications push (déclencheurs : nouveau lead, escalade, message non lu) · Hors ligne (cache **chiffré** des conversations récentes, purgé à la déconnexion) · Export CSV/PDF · Recherche globale · Notes internes · Tags · Réponses rapides · Transfert de conversation (escalade existante) · Passkeys/WebAuthn (« biométrie ») · Mode sombre · 2FA TOTP pour le rôle Admin.

Reportées v2 (de l'audit) : i18n EN (chaînes externalisées dès la v1), fiche 360° (l'identité visiteur n'est pas modélisée), widget natif, intégrations tierces (calendrier, CRM, paiement — via les événements du chantier 4).

### 3.3 Le flux de connexion (complété)

1. Livraison du site → fichier client : URL de l'app, e-mail, mot de passe **temporaire**, lien de première connexion (chantier 1).
2. Première ouverture → connexion → **changement forcé du mot de passe** → **onboarding guidé** (écran 0).
3. Session 30 jours ; reprise après 15 min d'inactivité → passkey/code.
4. Multi-sites : sélecteur en haut, le scope (`site_id`) s'applique à tout.
5. Rôles : Admin (tout), Opérateur (conversations + notes, pas la config), Lecteur (lecture seule).

### 3.4 Plateforme

- **PWA installable** (l'infrastructure existe : manifeste, service worker, invite non intrusive, hors-ligne — Lighthouse PWA 100) réutilisée telle quelle.
- **Android TWA** : configuration déjà posée (`twa-manifest.json`) ; la publication reste au propriétaire (compte Play, déjà au registre).
- iOS : sans wrapper v1 (règle Apple 4.2, décision déjà actée).
- Performance : Lighthouse ≥ 95 — le standard réel du projet est 97-100.

---

## 4. La landing page Mia — structure finale (8 sections, arbitrage de l'audit)

| Section | Contenu | Notes d'audit |
|---|---|---|
| **S1 Hero** | Titre par métier (du sélecteur) ; vidéo en boucle au chargement (repli : capture animée) ; **double CTA [Installer Mia] [Voir Mia en action]** — le second scrolle vers S4 ; **sélecteur de secteur = élément structurant de toute la page** | C7 : la vidéo ne bloque pas la mise en ligne |
| **S2 « Ce que Mia sait faire dans votre métier »** | alimentée **par `sectors.py`** : l'intention du secteur + les thèmes FAQ réels, en « Mia répond » ; les « exécute » avec badge « bientôt » | C1 + C2 ; remplace les cartes sectorielles du plan (fusion avec le sélecteur) |
| **S3 Comment ça marche** | 3 étapes : le visiteur pose sa question → Mia répond avec les informations du site → vous recevez le lead et prenez la main | aligné sur ce qui est branché (C2) |
| **S4 Démonstration interactive** | vraie conversation avec une Mia de démonstration (question libre ou suggestions par secteur) ; la vidéo de 60-90 s arrive en plus quand la chaîne existe | le CTA de S1 pointe ici |
| **S5 « Gérez Mia depuis votre téléphone »** | l'app client : captures réelles des écrans 2, 3, 8 (état vivant, conversations, compétences), fonctionnalités clés, CTA [Installer l'application] | captures générées depuis l'app réelle (harnais existant) |
| **S6 Preuves** | **sans témoignage tant qu'il n'y a pas de clients** : le banc des 14 secteurs (« un moteur, 12 métiers clients, vérifié par 11 contrôles automatiques »), les mesures réelles (temps de réponse, disponibilité), la démo brute non montée | C6 — aucun chiffre inventé, aucun témoignage fictif |
| **S7 FAQ** | prix et engagement, données personnelles (RGPD : « qui voit les conversations ? »), ce que Mia fait/ne fait pas (C2), installation, multilingue | la FAQ des données est une obligation, pas un argument |
| **S8 CTA final** | les deux boutons, rappel du sélecteur de secteur | |

**Deux profils de visiteur** (du plan, conservés) : le visiteur découvre et installe ; le propriétaire déjà client va vers S5 (l'app) — un accès « Vous avez déjà Mia ? Gérez-la » dans le hero.

---

## 5. Les vidéos — décision nécessaire avant production

| Vidéo | Durée | Contenu | Statut |
|---|---|---|---|
| Hero loop | 15-20 s | Mia en action (silencieuse, en boucle) | **bloquée** : chaîne de production inexistante |
| Démo produit | 60-90 s | parcours complet avec voix | **bloquée** : idem |
| Tutoriel installation | 30-45 s | installation du widget sur un site | **bloquée** : idem |
| Tutoriel app | 30 s | gestion depuis l'app | **bloquée** : idem |

**Ce qu'il manque** : un outil de synthèse vocale FR + un outil de montage (décision du propriétaire : service tiers type ElevenLabs/CapCut, ou l'agent dev précise sa chaîne). **Ce qui existe déjà** : le harnais de captures (112 maquettes reproductibles) — des captures animées (scrolles, transitions) sans voix sont produites aujourd'hui. **Recommandation (C7)** : la landing se lance avec la démo interactive et les captures animées ; les vidéos arrivent dès la chaîne décidée — c'est une amélioration, pas un prérequis.

---

## 6. Les quatre chantiers backend (avant l'UI)

| # | Chantier | Contenu | Livrable |
|---|---|---|---|
| **B1** | Provisionnement client | compte propriétaire à la livraison (mot de passe temporaire, premier login, changement forcé), lien user ↔ `site_id`, invitation par e-mail | routes + modèle `User.site_id` + rôles `client_admin/client_operator/client_reader` |
| **B2** | Autorisation par site | `require_site_owner(site_id)` : lecture/écriture scoper au site du compte — la surface admin existante n'est PAS exposée | dépendance FastAPI + tests |
| **B3** | API client v1 | exposer sous le scope client : conversations, leads, analytics, config du site (`ChatbotSite`), **horaires** (nouveau champ), compétences (`allowed_intents` + faq_themes du secteur), export RGPD | routes `/api/chatbot/client/*` |
| **B4** | Déclencheurs de notification | nouveau lead / escalade / message non lu → push (l'infrastructure `push_subscriptions.site_id` l'attend) + e-mail/Telegram (champs existants) | événements + envoi, test des 3 cas |

**Ordre** : B1 → B2 → B3 → B4, chaque chantier livré avec ses tests et la parité Docker (C12). **La consigne SITE n'est envoyée qu'après B1-B3** : des écrans sans données ne se conçoivent pas.

---

## 7. Séquence et délégation

1. **Moi (CHATBOT)** : B1 → B2 → B3 → B4 (backend, dans le cycle, parité Docker).
2. **SITE** : la refonte UI/UX (écrans + landing) — consigne `CONSIGNE-SITE.md`, déposée en ⚠️ DEMANDE au journal. Le SITE conçoit sur les données réelles de B1-B3.
3. **NOYAU** : aucune action requise — son `sectors.py` est consommé tel quel (lecture seule) ; une note de contrat est déposée si le contenu sectoriel affiché dépend de ses fichiers.
4. **Ballo** : la chaîne vidéo (C7), la publication stores (déjà au registre), et l'arbitrage « Mia exécute » par intégration (calendrier, e-commerce) en v2.
5. **Jamais** : concevoir l'UI moi-même ; toucher au dashboard admin ePerformance ; toucher au canal admin → clients (v2).

---

## 8. Ce qui n'est PAS dans cette mission (explicitement)

- La refonte UI/UX (déléguée à SITE — je fournis écrans, données, exigences).
- Le dashboard admin de ePerformance (Ballo, plus tard).
- Le canal admin → clients (Ballo, plus tard).
- Les intégrations tierces et la fiche 360° (v2, voir audit).
- La publication sur les stores (comptes développeur = prérequis propriétaire, déjà au registre).

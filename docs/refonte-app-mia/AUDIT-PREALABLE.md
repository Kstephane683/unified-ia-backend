# AUDIT PRÉALABLE — Refonte de l'app Mia (SaaS de gestion) + landing sectorielle

**Date** : 2026-09-19 · **Agent** : CHATBOT · **Statut** : audit terminé, **aucune conception n'a été faite avant lui**.
**Sources mesurées** : `agent-ia-web/eperf_core/sectors.py` (les 14 secteurs réels), `agent-ia-web/eperf_core/RAPPORT_BANC_14_SECTEURS.md`, `agent-ia-web/docs/adr/ADR-0005-specs-sectorielles.md`, `unified-ia-backend/backend/chatbot/models.py` (`ChatbotSite`), `backend/core/auth.py` (`verify_role`), `backend/api/routes/{auth,chatbot}.py`, le widget existant (`eperformance-widget`).

---

## 1. Le verdict d'ensemble sur le plan

Le plan du propriétaire est **fondamentalement juste sur la logique produit** — l'app est un outil de gestion multi-tenant pour les propriétaires de sites, pas une transformation du chatbot visiteur. C'est la décision la plus importante et elle est prise.

Le plan a en revanche **trois angles morts mesurés** : il ignore 6 secteurs sur 14 du noyau, il confond des capacités *conversationnelles* (que Mia a) avec des capacités *opérationnelles* (que personne n'a branchées), et il sous-estime ce que le backend a déjà. Chaque point est chiffré ci-dessous.

---

## 2. Les secteurs : le plan en couvre 9, le noyau en déclare 14

La liste **réelle** de `eperf_core/sectors.py` (le banc des 14 secteurs les génère tous, 13/14 franchissent les contrôles du noyau) :

`vitrine · beaute · restauration · hotellerie · sante · education · immobilier · evenementiel · ecommerce · mlm · blog · email · tourisme · artisan`

| Secteur du plan | Dans le noyau ? | Note |
|---|---|---|
| 1.1 Restauration | ✅ `restauration` | |
| 1.2 E-commerce | ✅ `ecommerce` | |
| 1.3 Immobilier | ✅ `immobilier` | |
| 1.4 MLM / Parrainage | ✅ `mlm` | |
| 1.5 Hôtellerie | ✅ `hotellerie` | |
| 1.6 Beauté | ✅ `beaute` | |
| 1.7 Santé | ✅ `sante` | |
| 1.8 Services professionnels | ❌ **n'existe pas** | couvert par `vitrine` (« déroulement d'une prestation, devis, délais, zone d'intervention ») et `artisan`. **Recommandation : fusionner dans ces deux-là**, ne pas créer un quinzième secteur pour le plan |
| 1.9 Éducation | ✅ `education` | |
| 1.10 « à compléter » | — | voir la ligne ci-dessous |
| **Manquants du plan** | **vitrine · evenementiel · tourisme · artisan** | **4 vrais secteurs clients ignorés par le plan** |
| | blog · email | **ne sont pas des secteurs de site client** : `blog` est un site éditorial, `email` est une bibliothèque de gabarits d'e-mails — **à exclure de la landing et de l'app** (une Mia pour « le secteur email » n'a pas de sens produit) |

**Recommandation C1** : la landing et l'app couvrent **10 secteurs clients** (`vitrine, beaute, restauration, hotellerie, sante, education, immobilier, evenementiel, ecommerce, mlm, tourisme, artisan` — 12 en comptant bien, hors `blog`/`email`), pas 9. Chacun a déjà son `intention`, ses `faq_themes` et son item déclarés dans le noyau : **le contenu sectoriel de la landing peut être généré depuis `sectors.py` plutôt que réécrit à la main** — une seule source, des références, comme partout ailleurs.

**Recommandation C2 — la plus importante de cet audit** : le plan liste des capacités **opérationnelles** (« réservations de table avec confirmation », « commandes en ligne », « check-in digital », « paiements », « gestion des retours ») comme si Mia les exécutait. **Aucune n'est branchée.** Le chatbot actuel capture des leads, répond à des FAQ sectorielles (les `faq_themes` du noyau : réservation, allergies, annulation, livraison…), qualifie des prospects et escalade vers l'humain. Il ne prend pas une réservation, ne prend pas une commande et ne fait pas de check-in.

Vendre ces capacités telles quelles sur la landing serait **vendre ce qui n'existe pas** — exactement le défaut que la page cookies avait (annoncer une suppression qui n'existait pas), en pire parce que c'est commercial. **Recommandation : structurer toute la communication en deux niveaux explicites** :

- **« Mia répond »** (disponible aujourd'hui, vérifiable) : FAQ sectorielle depuis les `faq_themes`, qualification de leads, prise de contact, capture de prospects, recommandation de contenu du site, escalade humaine.
- **« Mia exécute »** (roadmap, par intégration) : réservation réelle (agenda), commande réelle (e-commerce), paiement — chacune exige une intégration tierce ou un module backend. La landing le dit comme tel : « Mia s'apprête à… » ou un badge « bientôt », jamais une promesse sans support.

C'est aussi ce qui protège Ballo : un client qui achète « Mia prend les réservations » et découvre qu'elle ne fait que proposer un appel aura été trompé ; un client qui achète « Mia répond à vos clients 24h/24 et vous envoie les demandes de réservation » reçoit exactement ce qu'on lui a vendu.

---

## 3. Les écrans de l'app : le plan est bon, quatre écrans manquent, deux se recouvrent

Le plan liste 10 écrans. Mesuré contre ce que le backend expose déjà :

**Ce que le backend a déjà** (l'app peut le consommer dès la v1) :
- `ChatbotSite` : `system_prompt`, `welcome_message`, `theme_config`, `features_enabled`, **`allowed_intents`**, `rate_limit_messages_per_minute`, `rate_limit_conversations_per_day`, `notification_telegram_enabled`, `notification_email_enabled`, **`notification_recipients`** — **c'est exactement l'écran 7 (Configuration)**, et il existe déjà côté données.
- `GET /api/chatbot/analytics/{site_id}` — l'écran 6 (Analytics) a sa source.
- Conversations et leads portent `site_id` — les écrans 3, 4, 9 ont leurs données.
- `verify_role` accepte déjà le rôle **`client`** — le mécanisme d'autorisation l'attend.

**Ce que le backend n'a pas** (ma contribution, listée pour le plan) :
- Le **provisionnement** : aucun lien user ↔ site, aucun compte propriétaire créé à la livraison, aucun flux « premier connexion → changement de mot de passe ». L'écran 1 du plan repose sur un système qui n'existe pas encore.
- Les **routes client scopées** : les routes de gestion exigent `require_admin`. Il faut un périmètre `require_site_owner` (rôles Admin/Opérateur/Lecteur du plan, scopés à leur `site_id`).
- Le **canal de notification push** : `notification_recipients` gère Telegram/Email ; le push navigateur existe (`push_subscriptions` porte déjà `site_id`) — il manque le déclencheur métier.

**Quatre écrans que le plan oublie, et qui sont les plus vendus dans les apps SaaS concurrentes :**

| # | Écran manquant | Pourquoi il est essentiel |
|---|---|---|
| 11 | **« Mia en direct » (test)** | Le premier réflexe d'un propriétaire après avoir changé la configuration est de **tester**. Sans écran de test intégré, il retourne sur son site et recharge l'iframe — et ne comprend pas les délais. Un onglet « Essayer Mia » (conversation brouillon, non enregistrée) est le wow moment de la configuration. |
| 12 | **« Compétences de Mia »** | `allowed_intents` existe côté données. Montrer ce que le chatbot sait faire **de son site** (les thèmes FAQ de SON secteur) est ce qui rend Mia concrète et non générique — et c'est l'écran qui matérialise « chaque backend est contextuel ». |
| 13 | **« Horaires et disponibilités »** | Pour restauration, beauté, santé (3 secteurs sur 12), c'est LA donnée que le chatbot a besoin de connaître et que le propriétaire change le plus souvent. Sans cet écran, le client écrit un e-mail de support pour changer ses horaires. |
| 14 | **Onboarding guidé (première connexion)** | Le flux 2.3 du plan s'arrête à la connexion. Un propriétaire qui ouvre l'app pour la première fois a besoin d'un parcours en 3 étapes (voici Mia → voici ce qu'elle dit de vous → voici où vous la réglez) sinon il voit 10 onglets et n'en utilise que 2. |

**Deux recouvrements à arbitrer :**
- **Écran 2 (Accueil) vs 6 (Analytics)** : si les deux montrent des graphiques, l'un est inutile. Recommandation : Accueil = **état vivant et actions du jour** (Mia en ligne ? nouveaux messages non lus, leads du jour, dernière escalade), Analytics = **historique et tendances**. C'est la distinction SaaS classique « ce qui demande mon attention » vs « comment ça a évolué ».
- **Écran 8 (Commandes) et 9 (Prospects)** : conditionnels au secteur, donc **masqués** quand le secteur ne les justifie pas — le sélecteur de secteur du site entraîne le masquage. Un propriétaire de salon qui voit un onglet « Commandes » vide conclut que l'app est bâclée.

**Fonctionnalités transverses (2.2) — audit point par point** :

| Élément du plan | Verdict | Détail |
|---|---|---|
| Multi-sites | ✅ pertinent | `site_id` est partout ; la bascule est un sélecteur qui recharge le scope |
| Rôles Admin/Opérateur/Lecteur | ✅ mais **à créer** | `verify_role` a le rôle `client` mais pas la granularité par site — à faire au provisionnement |
| Notifications push | ✅ | l'infrastructure push existe (`push_subscriptions.site_id`) ; il manque le déclencheur métier (nouveau lead, escalade) — c'est déjà au registre |
| Mode hors ligne | ⚠️ avec réserve | conversations récentes en cache = données personnelles **stockées sur l'appareil**. Exigence : cache chiffré + purge à la déconnexion. À mentionner dans la politique de confidentialité |
| Export CSV/PDF | ✅ | et c'est aussi une **obligation RGPD** (droit de rétractation/portabilité du client final) — double raison |
| Recherche globale, notes, tags, réponses rapides, transfert | ✅ | le transfert = l'escalade humaine qui existe déjà (`human_active`) — bien |
| Historique client fiche 360° | ⚠️ v2 | les conversations portent le `session_id` visiteur, pas une identité client ; la fiche 360° suppose un croisement leads ↔ conversations qui n'existe pas encore. À ne pas promettre en v1 |
| Biométrie | ✅ | recommandé en **passkeys/WebAuthn** (standard, pas de biométrie seule) |
| Mode sombre | ✅ | les jetons clair/sombre existent déjà partout (empreinte vérifiée en 6.9) |
| **2FA** | ✅ ajouté | absent du plan. Minimum : TOTP pour le rôle Admin d'un site client. Un chatbot a accès aux conversations des clients finaux — c'est une donnée à protéger |
| **RGPD / conformité** | 🔴 **oubli majeur** | voir §5 |
| **i18n** | ⚠️ v2 | le noyau a `i18n_config.json` et les sites sont en français ; une app EN coûte plus qu'elle ne rapporte en v1. Prévoir l'architecture (chaînes externalisées) mais livrer FR |
| Widget iOS/Android natif | ⚠️ v2 | la PWA installable existe (Lighthouse 100) ; le natif attend les comptes stores (déjà au registre) |

---

## 4. La landing page : structure saine, quatre corrections

La structure en 8 sections est la bonne. Les problèmes mesurés :

1. **Le sélecteur de secteur (S1) et les cartes secteur (S2) font le même travail.** Deux interfaces pour une même action diluent chacune. Recommandation : le sélecteur de secteur devient **l'élément structurant de toute la page** (il adapte le hero, les capacités affichées ET la démo), et la S2 disparaît au profit de la S2 réécrite « Ce que Mia sait faire **dans votre métier** », alimentée par `sectors.py`.
2. **« Voir une démo live » (S1) et la démo interactive (S4) sont le même engagement.** Deux CTA différents pour la même action = un CTA à moitié ignoré. Recommandation : S1 double CTA = **[Installer Mia] [Voir Mia en action]** où le second scrolle vers la démo interactive S4 — un seul engagement, deux points d'entrée.
3. **Preuves sociales (S6) : Ballo a raison, et je précise la règle.** Aucun témoignage n'existe aujourd'hui — en inventer serait pire qu'un chiffre fantaisiste (c'est une mise en cause légale). **En l'absence de clients réels, la S6 ne ment pas : elle prouve autrement** — le banc des 14 secteurs (publiable : « un moteur, 14 métiers, vérifié par 11 contrôles automatiques »), les mesures de performance réelles, la vidéo de démo brute non montée. Les témoignages s'ajoutent quand il y a des clients, pas avant.
4. **Vidéos : 4 vidéos avec voix n'ont pas encore de chaîne de production.** C'est un vrai blocage à déclarer, pas une ligne de planning : il faut un outil (génération voix + montage) ou un repli. **Recommandation : ne pas bloquer la landing dessus** — la démo interactive (S4) EST la démonstration, les vidéos arrivent en amélioration continue. Le repli honnête : captures animées (script de capture existant, 112 maquettes reproductibles) + texte, sans voix.

**Positionnement « hyper performance »** : le plan demande un positionnement au-dessus de la marque. C'est cohérent avec la preuve disponible (les mesures réelles du produit : temps de réponse, disponibilité, 14 secteurs). La landing peut mesurer et afficher des chiffres **réels** du backend — c'est le seul tableau de preuve honnête qui existe aujourd'hui.

---

## 5. Ce à quoi personne n'a pensé — et qui est obligatoire

1. **RGPD / protection des données : l'oubli majeur du plan.** L'app donne à un tiers (le propriétaire du site) l'accès aux conversations de ses visiteurs. Trois obligations découlent de ça, à traiter **dans la conception, pas après** :
   - la **politique de confidentialité du site client** doit mentionner que les conversations sont traitées par ePerformance (le sous-traitant) — sinon le propriétaire est en infraction dès le premier message ;
   - le **droit d'accès/suppression du visiteur final** doit pouvoir être exercé par le propriétaire depuis l'app (export + suppression par conversation) — c'est un écran/réglage à prévoir, pas une option ;
   - la **rétention** : la purge 12 mois existe côté serveur (contrat de conformité), le client doit pouvoir la voir et, idéalement, la raccourcir pour son site.
2. **Sécurité : 2FA obligatoire pour le rôle Admin d'un site** (absent du plan). Les conversations contiennent des données personnelles de visiteurs ; un compte client compromis les expose. TOTP suffit en v1.
3. **Session persistante (flux 2.3) : à qualifier.** « Reste connecté » sur un appareil mobile partagé est une fuite. Recommandation : session 30 jours + ré-authentification biométrique/passkey à la reprise après inactivité > 15 min.
4. **La performance de l'app SE MESURE contre celle qu'on a déjà** : le produit est à Lighthouse 97-100 (PWA, a11y, SEO) sur les pages publiques. La cible 95+ du plan est cohérente, mais **le standard réel du projet est plus haut** — et un SaaS de gestion a peu de SEO à faire : c'est l'accessibilité et la performance mobile réelle qui comptent.
5. **Intégrations tierces (calendriers, CRM, paiement)** : c'est le pont vers les capacités « Mia exécute » (C2). À cadrer en v2, mais **l'architecture des événements** (le déclencheur métier des notifications) doit être posée en v1 pour ne pas refondre : un événement « demande de réservation » peut aujourd'hui notifier le propriétaire, demain créer l'agenda.
6. **L'identité « Mia » ne change pas** : les 27 agents internes restent invisibles ; dans l'app client, on parle de **compétences de Mia** (les `faq_themes` du secteur), jamais d'agents, de modèles ni de compteurs d'agents. Règle produit stricte, déjà appliquée au widget et à la console — elle vaut pour l'app et la landing.

---

## 6. Ce que le plan sous-estime : le travail backend (ma part)

La consigne dit « ta contribution : capacités sectorielles + logique backend + notifications ». Mesurée, elle vaut **quatre chantiers** sans lesquels l'app n'a pas de quoi vivre :

| # | Chantier | Détail |
|---|---|---|
| 1 | **Provisionnement client** | création du compte propriétaire à la livraison (mot de passe temporaire, première connexion, changement forcé), lien user ↔ `site_id` |
| 2 | **Rôles et routes scopées** | `Admin/Opérateur/Lecteur` par site ; routes lecture/écriture sous `require_site_owner` — la surface admin existante n'est PAS exposée |
| 3 | **API client v1** | exposer proprement ce qui existe déjà (conversations, leads, analytics, config du site) sous le périmètre client, + horaires (nouveau champ `ChatbotSite`) |
| 4 | **Déclencheurs de notification** | nouveau visiteur / nouveau lead / escalade → push (l'infrastructure `push_subscriptions.site_id` l'attend) |

Sans ces quatre chantiers, la consigne SITE porterait sur des écrans sans données. Ils sont planifiés dans `PLAN-COMPLET.md` **avant** l'UI.

---

## 7. Synthèse des recommandations

| # | Recommandation | Priorité |
|---|---|---|
| C1 | 12 secteurs clients (les 14 du noyau moins `blog` et `email`) — contenu de la landing **généré depuis `sectors.py`** | haute |
| C2 | Deux niveaux partout : « Mia répond » (aujourd'hui) / « Mia exécute » (roadmap) — **ne jamais vendre ce qui n'est pas branché** | **haute, bloquante pour la landing** |
| C3 | +4 écrans (Mia en direct, Compétences, Horaires, Onboarding) ; arbitrer Accueil/Analytics ; masquer les écrans sectoriels hors sujet | haute |
| C4 | RGPD dans la conception : mention sous-traitant, droit d'accès/suppression du visiteur final, rétention visible | **haute, bloquante** |
| C5 | 2FA TOTP pour le rôle Admin du site client | haute |
| C6 | Preuves sociales sans témoignage : banc 14 secteurs + mesures réelles ; les témoignages quand il y aura des clients | haute |
| C7 | Vidéos : ne pas bloquer la landing — démo interactive d'abord, captures animées en repli, la chaîne voix/montage est une décision à prendre | moyenne |
| C8 | Backend d'abord : provisionnement, rôles, API client, déclencheurs — sinon les écrans n'ont pas de données | **haute** |
| C9 | i18n FR en v1 (chaînes externalisées), EN en v2 ; passkeys plutôt que « biométrie » ; widget natif v2 | moyenne |
| C10 | Fiche 360° client : v2 (l'identité visiteur n'est pas modélisée) | moyenne |

**Le plan est validé sous ces corrections.** La logique produit (app de gestion multi-tenant, landing sectorielle, délégation UI à SITE) est la bonne ; les corrections ci-dessus le mettent en accord avec ce qui existe réellement — et surtout, elles l'empêchent de promettre ce qui n'est pas branché.

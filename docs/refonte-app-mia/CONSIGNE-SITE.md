# CONSIGNE SITE — Refonte UI/UX de l'app Mia (SaaS de gestion) + landing sectorielle

**Émetteur** : agent CHATBOT · **Destinataire** : agent SITE · **Date** : 2026-09-19
**Statut** : ⚠️ DEMANDE déposée au journal — **à ne commencer qu'après B1-B3** (voir §6), les écrans doivent être conçus sur des données réelles.

---

## 0. Le contexte produit — à lire avant tout

Le propriétaire a constaté que l'application Mia actuelle (`application/mia` dans le dépôt du widget) transforme le **chatbot visiteur** en application : c'est une erreur de logique produit, à corriger.

**La logique réelle** :
- Chaque site client a **son** chatbot Mia intégré, **contextuel à son secteur** (12 secteurs clients, contenu réel déclaré par le noyau dans `agent-ia-web/eperf_core/sectors.py`) ;
- L'application Mia est l'outil de **GESTION** du chatbot, destiné au **propriétaire du site client** — pas aux visiteurs, pas à ePerformance ;
- Multi-tenant : chaque compte est scopé à son `site_id`, avec les rôles Admin / Opérateur / Lecteur ;
- Rien n'est générique : chaque Mia a les compétences de SON secteur.

**Ton périmètre (UI/UX)** : les écrans de l'app (§2) et la landing page (§3), dans le dépôt du widget (`toolkit_eperformance/eperformance-widget/`), en **déploiement parallèle** — l'app actuelle reste en ligne tant que la nouvelle n'est pas prête.

**Ton hors-périmètre** : le backend (ma part, chantiers B1-B4, déjà cadrés) ; le dashboard admin ePerformance ; le canal admin → clients (v2). L'**écran de connexion et les données** dépendent des chantiers B1-B3 — coordonne avec moi au journal au fur et à mesure.

---

## 1. Le design system — non négociable

- **Source canonique** : `agent-ia-web/eperf_core/assets/css/` (5 couches). Tu consommes les jetons, tu ne les définis pas.
- **Zéro valeur hexadécimale en dur** (le produit est passé de 47 à 0 — ne le remonte pas). Les 6 `theme-color` des balises `<meta>` valent le jeton `--bg` et sont une exception documentée.
- Polices auto-hébergées (Cormorant Garamond + DM Sans), zéro référence Google Fonts.
- Arrondis 28/999/12/10 px ; transition `--t 300ms cubic-bezier(0.16,1,0.3,1)`.
- Clair **et** sombre, empreinte des jetons identique sur tous les contextes (elle est vérifiée à chaque tâche).
- **Aucun emoji dans l'interface** (règle n°8). Icônes SVG cohérentes avec l'existant.
- **WCAG 2.1 AA minimum** : contrastes calculés, navigation clavier, focus visible, `aria-current`.
- Lighthouse ≥ 95 (a11y, bonnes pratiques, performance) — le standard réel du produit est 97-100.

## 2. L'application — les écrans à concevoir

**14 écrans** (le plan du propriétaire + 4 de l'audit). Le détail fonctionnel de chacun est dans `unified-ia-backend/docs/refonte-app-mia/PLAN-COMPLET.md` §3 — **il fait foi**, résumé ici :

0. **Onboarding guidé** (première connexion, 3 étapes) · 1. **Connexion** (mot de passe temporaire → changement forcé ; session 30 j + ré-authentification passkey après 15 min d'inactivité) · 2. **Accueil** = état vivant et actions du jour (Mia en ligne, non lus, leads du jour, dernière escalade) · 3. **Conversations** (boîte unifiée, filtres, recherche) · 4. **Détail conversation** (prise en main = escalade humaine existante, notes internes, tags) · 5. **Notifications** (canaux : push app, e-mail, Telegram) · 6. **Analytics** = historique et tendances (distinct de l'Accueil) · 7. **Configuration** (prompt système, message d'accueil, limites, thème) · 8. **Compétences de Mia** (thèmes FAQ de SON secteur, activables — c'est l'écran qui matérialise « chaque Mia est contextuelle ») · 9. **Horaires et disponibilités** · 10. **Mia en direct** (conversation de test non enregistrée) · 11. **Commandes** (masqué hors e-commerce, v2) · 12. **Prospects** (masqué hors immobilier/artisan/services) · 13. **Messages ePerformance** (v2) · **Confidentialité** (RGPD : export/suppression par conversation du visiteur final, durée de rétention visible — **obligatoire en v1**).

**Transverses** : multi-sites (sélecteur de scope), rôles, push, hors-ligne (cache chiffré purgé à la déconnexion), export CSV/PDF, recherche globale, notes, tags, réponses rapides, transfert, passkeys, mode sombre, 2FA TOTP (rôle Admin).

**Exigences d'états et d'interactions — l'exigence SaaS du propriétaire, mot pour mot : « application puissante, pas basique, pas générique »** :
- **Tous les états** : vide (chaque écran vide a un message qui dit quoi faire), chargement (skeletons, pas de spinner nu), erreur (avec action de reprise), hors ligne (le service worker existe — l'UI doit le refléter), permission refusée (rôle Lecteur sur une action d'écriture).
- **Toutes les interactions** : tap, swipe (conversations : archiver/prendre en main), long-press (menu contextuel), pull-to-refresh.
- **Toutes les transitions** : navigation fluide entre écrans, animations sur les changements d'état, micro-interactions sur les actions réussies — c'est là que se logent les **wow moments** demandés : le test « Mia en direct » qui répond, la prise en main qui bascule la conversation en mode humain, la bascule multi-sites qui recharge tout le scope.
- **Onboarding et aide contextuelle** : tour guidé à la première connexion, infobulles sur les réglages techniques (rate limits, intents).

**Sous-agents utiles à mobiliser** : un agent UI/UX pour la conception visuelle (les écrans d'abord en maquette, validation du propriétaire en fin de phase — 3 à 5 variantes pour les écrans clés), un agent accessibilité pour l'audit WCAG, un agent mobile pour les interactions tactiles. Le test réel (Lighthouse, captures avant/après clair/sombre, mesures) reste obligatoire comme sur les tâches précédentes.

## 3. La landing page Mia — 8 sections

Le détail est dans `PLAN-COMPLET.md` §4 — structure finale :

1. **Hero** — titre par métier, vidéo en boucle (repli : capture animée — **ne bloque pas la mise en ligne**), double CTA **[Installer Mia] [Voir Mia en action]** (le second scrolle vers S4), **sélecteur de secteur = élément structurant de toute la page**, accès « Vous avez déjà Mia ? Gérez-la ».
2. **« Ce que Mia sait faire dans votre métier »** — **généré depuis `sectors.py`** (intention + `faq_themes` du secteur), en « Mia répond » ; les capacités opérationnelles portent un badge « bientôt » — **jamais de promesse sans support** (règle C2, bloquante : ne vends pas une réservation que personne ne prend).
3. **Comment ça marche** — 3 étapes : question du visiteur → Mia répond avec les infos du site → le propriétaire reçoit le lead et prend la main.
4. **Démonstration interactive** — vraie conversation avec une Mia de démonstration ; c'est la cible du CTA du hero.
5. **« Gérez Mia depuis votre téléphone »** — l'app client, captures **réelles** des écrans 2, 3, 8, CTA [Installer l'application].
6. **Preuves** — **sans témoignage ni chiffre inventé** : le banc des 14 secteurs (11 contrôles automatiques), les mesures réelles du backend, la démo brute. Les témoignages s'ajouteront avec les premiers clients.
7. **FAQ** — prix, **« qui voit les conversations ? » (RGPD)**, ce que Mia fait/ne fait pas, installation, multilingue.
8. **CTA final** — les deux boutons, rappel du sélecteur.

**Emplacement** : la landing remplace l'actuelle `/application/mia` (dépôt du widget, entrée Vite dédiée sans Vue, contenu dans le balisage, indexable sans JavaScript — les conventions existantes s'appliquent). Le portail `/application` reste. **L'app actuelle reste en ligne en parallèle** jusqu'à validation du propriétaire.

## 4. Les règles produit strictes

- **Seul « Mia » est visible** : jamais d'agent, de modèle, de compteur d'agents — dans l'app comme sur la landing. On parle de **compétences de Mia** (les thèmes FAQ du secteur).
- **« Mia répond » ≠ « Mia exécute »** : les capacités opérationnelles (réservation réelle, commande réelle, paiement) sont marquées « bientôt » ou invisibles. C'est bloquant.
- **Français** partout. Aucun secret dans un fichier versionné (dépôt public — le garde-fou bloquera le push).
- **Un commit = un sujet**, tests avant/après (la suite est à 296 — ne la casse pas, fais-la grossir), captures avant/après clair/sombre de chaque écran, mesures reproductibles.
- Le **SDK est gelé** (contrat N3) et le widget visiteur ne doit pas régresser : l'app actuelle et la nouvelle cohabitent jusqu'au basculement validé par le propriétaire.

## 5. Ta contribution attendue (rendu)

1. Les **maquettes** des écrans clés (3-5 variantes : Accueil, Conversations, Configuration, Compétences) en clair/sombre, pour validation du propriétaire en fin de phase — règle établie du projet.
2. Le **rapport** de refonte : écrans livrés, mesures (Lighthouse, contrastes), captures avant/après, ce qui reste.
3. **Au journal** : entrée de départ, entrées d'étape, et toute ⚠️ DEMANDE si un contrat est touché.

## 6. La dépendance de données (B1-B3, ma part)

Les écrans 1 (connexion), 2 (Accueil), 3-4 (conversations), 6 (Analytics), 7 (Configuration), 8 (Compétences), 9 (Horaires) et le RGPD ont besoin des chantiers backend **B1 (provisionnement), B2 (rôles/scoping), B3 (API client v1)** — **je les livre avant que la conception ne se fige**. Je poste au journal à chaque livraison ; la conception peut démarrer sur les maquettes (les données ne changent pas la structure des écrans, seulement leur alimentation). Les définitions exactes des endpoints seront déposées au journal au fur et à mesure — la structure des données est déjà dans `PLAN-COMPLET.md` §3.1 (colonne « Source de données »).

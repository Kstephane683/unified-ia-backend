"""
Modèles SQLAlchemy pour le système Chatbot ePerformance
Phase 1-S1.4 : 5 tables (sites, conversations, messages, leads, analytics)
"""
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, TIMESTAMP, Enum, JSON, DECIMAL,
    ForeignKey, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.core.database import Base


class ChatbotSite(Base):
    """
    Configuration multi-tenant : chaque site_id a son propre chatbot personnalisé
    Sites : eperformance_vitrine, espace_client, boutique_client_xxx
    """
    __tablename__ = "chatbot_sites"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(String(100), nullable=False, unique=True, index=True, 
                     comment='Identifiant unique du site')
    site_name = Column(String(200), nullable=False, comment='Nom affiché du site')
    site_url = Column(String(500), nullable=True, comment='URL du site')
    
    # Configuration chatbot
    system_prompt = Column(Text, nullable=True, 
                          comment='System prompt personnalisé (override le prompt par défaut)')
    welcome_message = Column(Text, nullable=True, 
                            comment='Message de bienvenue personnalisé')
    theme_config = Column(JSON, nullable=True, 
                         comment='Configuration thème (couleurs, logo, position)')
    
    # Fonctionnalités activées
    features_enabled = Column(JSON, nullable=True, 
                             comment='{"diagnostic": true, "order_capture": true, "support": true}')
    allowed_intents = Column(JSON, nullable=True, 
                            comment='Liste des intents autorisés (null = tous)')
    
    # Rate limiting
    rate_limit_messages_per_minute = Column(Integer, default=20, 
                                           comment='Limite messages par minute par visiteur')
    rate_limit_conversations_per_day = Column(Integer, default=100, 
                                             comment='Limite conversations par jour par IP')
    
    # Notifications
    notification_telegram_enabled = Column(Boolean, default=True,
                                          comment='Activer notifications Telegram pour leads')
    notification_email_enabled = Column(Boolean, default=True,
                                       comment='Activer notifications Email pour leads')
    notification_recipients = Column(JSON, nullable=True,
                                    comment='Liste des destinataires pour ce site')

    # --- Refonte app Mia (B3/B4, 2026-09-19) — colonnes créées par la
    # migration au boot (backend/core/migrations_boot.py) : create_all ne les
    # aurait PAS ajoutées à la table existante de production.
    sector = Column(String(50), nullable=True,
                    comment='Secteur du site (slug du noyau eperf_core, ex. '
                            '"restauration") — détermine les compétences de '
                            'Mia affichées au client')
    horaires = Column(JSON, nullable=True,
                      comment='Horaires et disponibilités (écran 9 de l\'app '
                              'Mia) — structure libre JSON, documentée dans '
                              'API-CLIENT-V1.md §8')
    notification_settings = Column(JSON, nullable=True,
                                   comment='Réglages de notification PAR TYPE '
                                           '(B4) : {"nouveau_lead": {"push": '
                                           'true, "email": false, '
                                           '"telegram": true}, "escalade": '
                                           '{...}, "nouveau_visiteur": {...}}')

    # Métadonnées
    is_active = Column(Boolean, default=True, index=True, comment='Site actif')
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), 
                       onupdate=func.current_timestamp())
    
    def __repr__(self):
        return f"<ChatbotSite(site_id={self.site_id}, name={self.site_name})>"


class ChatbotConversation(Base):
    """
    Sessions de conversation avec les visiteurs
    Tracking complet : visiteur, statut, métriques, lead capturé
    """
    __tablename__ = "chatbot_conversations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(100), nullable=False, unique=True, index=True, 
                            comment='UUID unique de la conversation')
    site_id = Column(String(100), nullable=False, index=True, 
                    comment='Site où la conversation a lieu')
    
    # Identification visiteur
    user_id = Column(Integer, nullable=True, index=True, 
                    comment='ID candidat/client si connecté (FK candidats.id)')
    visitor_name = Column(String(200), nullable=True, comment='Nom du visiteur (si fourni)')
    visitor_email = Column(String(200), nullable=True, comment='Email du visiteur (si fourni)')
    visitor_phone = Column(String(50), nullable=True, comment='Téléphone du visiteur (si fourni)')
    visitor_ip = Column(String(100), nullable=True, index=True, 
                       comment='IP du visiteur (rate limiting)')
    visitor_info = Column(JSON, nullable=True, 
                         comment='Infos navigateur, device, location')
    
    # État conversation
    status = Column(Enum('active', 'resolved', 'escalated', 'abandoned', name='conversation_status'), 
                   default='active', index=True, comment='État de la conversation')
    started_at = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True, 
                       comment='Début de la conversation')
    last_message_at = Column(TIMESTAMP, server_default=func.current_timestamp(), 
                            comment='Dernier message')
    ended_at = Column(TIMESTAMP, nullable=True, comment='Fin de la conversation')
    
    # Métriques
    message_count = Column(Integer, default=0, comment='Nombre de messages dans la conversation')
    lead_captured = Column(Boolean, default=False, index=True, 
                          comment='Lead capturé pendant cette conversation')
    satisfaction_rating = Column(Integer, nullable=True, 
                                comment='Note satisfaction (1-5) si demandée')
    
    # Métadonnées
    conversation_metadata = Column('metadata', JSON, nullable=True, 
                                   comment='Données additionnelles (utm_source, referrer, etc.)')
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), 
                       onupdate=func.current_timestamp())
    
    def __repr__(self):
        return f"<ChatbotConversation(id={self.conversation_id}, site={self.site_id}, status={self.status})>"


class ChatbotMessage(Base):
    """
    Messages individuels dans les conversations (user + assistant)
    Tracking : intent, agent utilisé, actions, métriques LLM
    """
    __tablename__ = "chatbot_messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(100), 
                            ForeignKey('chatbot_conversations.conversation_id', ondelete='CASCADE'), 
                            nullable=False, index=True, 
                            comment='ID de la conversation parent')
    
    # Message
    role = Column(Enum('user', 'assistant', 'system', name='message_role'), 
                 nullable=False, index=True, comment='Émetteur du message')
    content = Column(Text, nullable=False, comment='Contenu du message')
    
    # Traitement IA (seulement pour messages user)
    intent = Column(String(100), nullable=True, index=True, 
                   comment='Intent détecté (diagnostic_request, order_intent, etc.)')
    intent_confidence = Column(DECIMAL(5, 4), nullable=True, 
                              comment='Confiance de détection (0.0000-1.0000)')
    agent_used = Column(String(100), nullable=True, index=True, 
                       comment='Agent IA utilisé pour générer la réponse')
    
    # Actions exécutées
    actions_executed = Column(JSON, nullable=True, 
                             comment='Actions exécutées (lead_capture, diagnostic_create, etc.)')
    
    # Contexte utilisé
    context_data = Column(JSON, nullable=True, 
                         comment='Contexte utilisé pour générer la réponse')
    
    # Suggestions (quick replies)
    suggestions = Column(JSON, nullable=True, comment='Boutons de suggestion affichés')
    
    # Métriques
    processing_time_ms = Column(Integer, nullable=True, 
                               comment='Temps de traitement en millisecondes')
    llm_provider = Column(String(50), nullable=True, 
                         comment='Provider LLM utilisé (deepseek, claude)')
    llm_tokens_used = Column(Integer, nullable=True, 
                            comment='Tokens utilisés pour cette réponse')
    
    # Métadonnées
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)
    
    def __repr__(self):
        return f"<ChatbotMessage(id={self.id}, role={self.role}, intent={self.intent})>"


class ChatbotLead(Base):
    """
    Leads capturés pendant les conversations
    → Notifications équipe via système communication Phase 1-S1.3

    NB: aligné sur le schéma RÉEL de la table (inspecté via
    /api/chatbot/admin/debug/schema — l'ancien modèle référencait des
    colonnes visitor_* inexistantes → toute requête ORM plantait).
    """
    __tablename__ = "chatbot_leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(100), nullable=False, index=True, comment='Conversation source')
    site_id = Column(String(100), nullable=False, index=True, comment='Site source')

    # Contact
    name = Column(String(200), nullable=True, comment='Nom du lead')
    email = Column(String(200), nullable=True, index=True, comment='Email du lead')
    phone = Column(String(50), nullable=True, comment='Téléphone du lead')
    company = Column(String(200), nullable=True, comment='Entreprise')

    # Qualification
    lead_type = Column(Enum('hot', 'warm', 'cold', 'information', name='lead_type'),
                       nullable=True, comment='Température du lead')
    intent = Column(String(100), nullable=True, comment='Intent à la capture')
    message = Column(Text, nullable=True, comment='Message du lead')
    interested_products = Column(JSON, nullable=True, comment='Produits/services d\'intérêt')
    budget_range = Column(String(50), nullable=True, comment='Fourchette de budget')
    urgency = Column(String(50), nullable=True, comment='Urgence')

    # Suivi commercial
    status = Column(Enum('new', 'contacted', 'qualified', 'converted', 'lost', name='lead_status'),
                    nullable=True, comment='Statut commercial')
    assigned_to = Column(String(200), nullable=True, comment='Assigné à')
    notification_sent = Column(Boolean, nullable=True, comment='Notification équipe envoyée')
    notification_ids = Column(JSON, nullable=True, comment='IDs des notifications envoyées')
    first_contact_at = Column(TIMESTAMP, nullable=True, comment='Premier contact')
    converted_at = Column(TIMESTAMP, nullable=True, comment='Date de conversion')
    conversion_value = Column(DECIMAL(12, 2), nullable=True, comment='Valeur de conversion')

    # Contexte
    source_url = Column(String(500), nullable=True, comment='URL source')
    utm_data = Column(JSON, nullable=True, comment='Données UTM')
    lead_metadata = Column('metadata', JSON, nullable=True, comment='Données additionnelles')

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp())

    def __repr__(self):
        return f"<ChatbotLead(id={self.id}, name={self.name})>"


class ChatbotAnalytics(Base):
    """
    Events tracking pour analytics et optimisation
    Types d'events : conversation_start, message_sent, lead_captured, error, etc.
    """
    __tablename__ = "chatbot_analytics"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(String(100), nullable=False, index=True, comment='Site source')
    conversation_id = Column(String(100), nullable=True, index=True, 
                            comment='Conversation associée (si applicable)')
    
    # Event
    event_type = Column(String(100), nullable=False, index=True, 
                       comment='Type d\'event (conversation_start, message_sent, lead_captured, etc.)')
    event_category = Column(String(50), nullable=True, index=True, 
                           comment='Catégorie (engagement, conversion, error, performance)')
    
    # Données event
    event_data = Column(JSON, nullable=True, comment='Données spécifiques à l\'event')
    
    # Contexte
    visitor_ip = Column(String(100), nullable=True, comment='IP du visiteur')
    user_agent = Column(Text, nullable=True, comment='User agent')
    referrer = Column(String(500), nullable=True, comment='Referrer')
    
    # Timing
    timestamp = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True, 
                      comment='Moment de l\'event')
    
    def __repr__(self):
        return f"<ChatbotAnalytics(id={self.id}, type={self.event_type}, site={self.site_id})>"


class ChatbotPushSubscription(Base):
    """
    Abonnement au push navigateur — tâche 6.5.

    Un abonnement est créé par le navigateur (celui du visiteur ou du
    propriétaire, via le service worker du widget) et stocké ici pour être
    réutilisé à chaque envoi. Les trois premiers champs sont ceux de la norme
    Web Push : `endpoint` est l'URL du service de push du navigateur,
    `cle_p256dh` et `cle_auth` sont les deux clés produites par le navigateur —
    sans elles, le message ne peut pas être chiffré et le service de push le
    refuse.

    Aucune donnée personnelle n'est stockée : ni nom, ni e-mail, ni numéro.
    L'identité d'un abonnement est son `endpoint`, lisible seulement par le
    service de push du navigateur concerné.
    """
    __tablename__ = "chatbot_push_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    endpoint = Column(Text, nullable=False, unique=True,
                      comment='URL du service de push (identifie l\'abonnement)')
    cle_p256dh = Column(Text, nullable=False, comment='Clé publique p256dh du navigateur')
    cle_auth = Column(Text, nullable=False, comment='Secret d\'authentification du navigateur')

    # Contexte (facultatif, pour le diagnostic et le ciblage)
    site_id = Column(String(100), nullable=True, index=True, comment='Site concerné')
    libelle = Column(String(200), nullable=True,
                     comment='Libellé lisible (ex. « Chrome bureau ») — jamais un nom de personne')
    user_agent = Column(Text, nullable=True, comment='User agent au moment de l\'abonnement')

    # Cycle de vie
    est_actif = Column(Boolean, default=True, index=True,
                       comment='Désactivé si le service de push renvoie 404/410 (abonnement expiré)')
    derniere_reussite = Column(TIMESTAMP, nullable=True, comment='Dernier envoi réussi')
    dernier_echec = Column(TIMESTAMP, nullable=True, comment='Dernier échec d\'envoi')
    dernier_message_erreur = Column(Text, nullable=True, comment='Motif du dernier échec')

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(),
                        onupdate=func.current_timestamp())

    def __repr__(self):
        return f"<ChatbotPushSubscription(id={self.id}, actif={self.est_actif})>"


class PushSubscription(Base):
    """
    Abonnement au push navigateur créé par le WIDGET (interface publique).

    POURQUOI UNE SECONDE TABLE D'ABONNEMENTS, ET PAS UNE COLONNE DE PLUS
    -------------------------------------------------------------------
    La table `chatbot_push_subscriptions` (tâche 6.5) existe déjà en
    production et porte les abonnements enregistrés par la route
    d'administration. `init_db()` appelle `Base.metadata.create_all()`, qui
    crée les tables ABSENTES et **n'ajoute jamais une colonne** à une table
    existante : ajouter `conversation_id` ou `date_derniere_utilisation` au
    modèle de 6.5 aurait donc produit, en production, un modèle annonçant des
    colonnes que la base n'a pas — et toute lecture de la table serait tombée
    en erreur. Une table nouvelle, à l'inverse, est créée proprement au boot.

    Les deux tables coexistent : l'ancienne garde les abonnements créés par la
    route d'administration (rien n'est perdu, rien n'est renommé), la
    présente porte ceux créés par le widget. L'envoi lit LES DEUX et dédoublonne
    sur `endpoint` — voir `backend/chatbot/push_abonnements.py`.

    Aucune donnée personnelle n'est stockée ici : ni nom, ni e-mail, ni numéro,
    ni adresse IP. Un abonnement n'a qu'une identité, son `endpoint`, lisible
    seulement par le service de push du navigateur concerné. Les deux clés
    (`keys_p256dh`, `keys_auth`) sont des secrets de chiffrement produits par le
    navigateur : elles ne sont ni journalisées, ni renvoyées par l'API.
    """
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    #: URL du service de push du navigateur. C'est l'IDENTITÉ de l'abonnement :
    #: unique en base, c'est la clé de rapprochement du réabonnement (un même
    #: navigateur réabonné met à jour sa ligne au lieu d'en créer une seconde).
    endpoint = Column(Text, nullable=False, unique=True,
                      comment='URL du service de push (identifie l\'abonnement)')
    #: Les deux clés produites par le navigateur (norme Web Push, RFC 8291).
    #: Sans elles, le message ne peut pas être chiffré et le service de push le
    #: refuse. Stockées telles quelles, en base64url.
    keys_p256dh = Column(Text, nullable=False,
                         comment='Clé publique p256dh du navigateur')
    keys_auth = Column(Text, nullable=False,
                       comment='Secret d\'authentification du navigateur')

    #: Contexte, pour le diagnostic et le ciblage. AUCUNE clé étrangère : un
    #: abonnement ne dépend d'aucune conversation et doit survivre à la purge
    #: automatique des conversations (12 mois) — une contrainte de clé
    #: étrangère ferait échouer la purge ou emporterait l'abonnement.
    conversation_id = Column(String(100), nullable=True, index=True,
                             comment='Conversation au moment de l\'abonnement')
    site_id = Column(String(100), nullable=True, index=True, comment='Site concerné')
    user_agent = Column(Text, nullable=True,
                        comment='User agent au moment de l\'abonnement')

    #: Désabonnement : la ligne passe à faux, elle n'est JAMAIS supprimée. La
    #: trace est ce qui permet de diagnostiquer après coup (« ce navigateur
    #: s'était abonné le 18/09 puis s'est désabonné le 20/09 »), et le
    #: réabonnement du même endpoint remet simplement ce booléen à vrai.
    actif = Column(Boolean, default=True, nullable=False, index=True,
                   comment='Faux après désabonnement — la ligne est conservée')

    date_creation = Column(TIMESTAMP, server_default=func.current_timestamp(),
                           comment='Premier abonnement (inchangé au réabonnement)')
    date_derniere_utilisation = Column(
        TIMESTAMP, nullable=True,
        comment='Dernière tentative d\'envoi ayant abouti au moins une fois')

    def __repr__(self):
        return f"<PushSubscription(id={self.id}, actif={self.actif})>"


class ClientNotification(Base):
    """
    Notification in-app du propriétaire (refonte app Mia, B4).

    POURQUOI CETTE TABLE ET PAS SEULEMENT LES CANAUX
    ------------------------------------------------
    Les canaux existants (webpush, e-mail, Telegram) dépendent de
    configurations externes : clés VAPID absentes, IP refusée par Brevo,
    chat_id mal renseigné. La notification in-app, elle, ne dépend d'AUCUNE
    clé : elle est écrite EN MÊME TEMPS que l'événement métier (nouveau lead,
    escalade, nouveau visiteur), avant même les envois — le propriétaire voit
    toujours son événement dans l'app, même quand tous les canaux sont mal
    configurés. C'est le filet de sécurité produit du chantier B4.

    Contenu borné : titre + corps courts, rédigés par le backend. Jamais le
    contenu intégral d'une conversation ; le corps pointe vers elle via
    `conversation_id` (facultatif, sert au lien de l'écran Notifications).
    """
    __tablename__ = "client_notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(String(100), nullable=False, index=True,
                     comment='Site destinataire (isolation multi-tenant)')
    type = Column(String(50), nullable=False, index=True,
                  comment='nouveau_lead | escalade | nouveau_visiteur')
    titre = Column(String(200), nullable=False, comment='Titre court affiché')
    corps = Column(Text, nullable=True, comment='Corps du message in-app')
    conversation_id = Column(String(100), nullable=True, index=True,
                             comment='Conversation liée, pour le lien in-app')

    lu = Column(Boolean, default=False, nullable=False, index=True,
                comment='Marquée lue par POST /notifications/read')
    date_creation = Column(TIMESTAMP, server_default=func.current_timestamp(),
                           index=True, comment='Moment de l\'événement')

    def __repr__(self):
        return f"<ClientNotification(id={self.id}, site={self.site_id}, type={self.type})>"


class ChatbotNotificationLog(Base):
    """
    Trace d'un envoi de notification — tâche 6.5.

    POURQUOI CETTE TABLE EXISTE. Sans elle, un envoi qui ne part pas ne laisse
    aucune trace : l'appelant reçoit une erreur, la relit une fois, et il ne
    reste rien. Le propriétaire ne peut alors ni constater le problème, ni
    savoir combien d'envois ont échoué, ni pourquoi.

    Une ligne est écrite DANS TOUS LES CAS, y compris quand le canal n'est pas
    configuré : c'est le cas le plus important à pouvoir constater après coup.

    Contenu volontairement borné : le corps du message est tronqué
    (`NOTIF_TRACE_CORPS`). La trace dit ce qui a été envoyé et s'il est parti ;
    elle n'est pas une archive de contenu.
    """
    __tablename__ = "chatbot_notification_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    canal = Column(String(30), nullable=False, index=True,
                   comment='telegram | email | webpush | whatsapp')
    #: « non_configure » n'est PAS un échec d'envoi : c'est un envoi qui n'a
    #: jamais été tenté faute de configuration. La distinction est essentielle
    #: au diagnostic — les deux ne se réparent pas de la même façon.
    statut = Column(String(20), nullable=False, index=True,
                    comment='envoye | echec | non_configure')
    succes = Column(Boolean, nullable=False, index=True, comment='Vrai si l\'envoi a abouti')

    destinataire = Column(String(500), nullable=True,
                          comment='Destinataire (chat_id, e-mail, ou nombre d\'abonnements)')
    sujet = Column(String(200), nullable=True, comment='Sujet de la notification')
    corps = Column(Text, nullable=True, comment='Corps envoyé, tronqué (traçabilité)')

    code_erreur = Column(String(100), nullable=True, comment='Code HTTP ou type d\'exception')
    erreur = Column(Text, nullable=True, comment='Motif lisible de l\'échec')
    identifiant_fournisseur = Column(String(200), nullable=True,
                                     comment='Identifiant du message chez le fournisseur')

    auteur = Column(String(200), nullable=True, comment='Compte admin ayant déclenché l\'envoi')
    duree_ms = Column(Integer, nullable=True, comment='Durée de l\'appel au fournisseur')

    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True,
                        comment='Moment de la tentative')
    envoye_le = Column(TIMESTAMP, nullable=True, comment='Moment de l\'envoi effectif')

    def __repr__(self):
        return f"<ChatbotNotificationLog(id={self.id}, canal={self.canal}, statut={self.statut})>"


class Fonctionnalite(Base):
    """
    Feature flag du produit (fondations d'extensibilité, Mission 1).

    UNE LIGNE PAR FONCTIONNALITÉ, seedée au boot de façon IDEMPOTENTE
    (backend/core/fonctionnalites.py::seed_fonctionnalites) : une ligne
    absente est créée, une ligne présente n'est JAMAIS écrasée — l'activation
    (`active`) et le plan requis (`plan_minimum`) sont des décisions de
    gestion qui doivent survivre aux redéploiements.

    Les canaux WhatsApp / RCS et l'abonnement Jeko sont créés INACTIFS : leur
    route est pré-implémentée, leur activation est une décision du
    propriétaire (poser les clés, basculer le flag — aucun changement de
    code, cf. docs/refonte-app-mia/EXTENSIBILITE.md).
    """
    __tablename__ = "fonctionnalites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cle = Column(String(50), nullable=False, unique=True, index=True,
                 comment='Clé du flag (notifications_push, rcs_messages, …) — '
                         'identité stable, consommée par l\'app via /me')
    plan_minimum = Column(String(20), nullable=False, default='free',
                          comment='Plan minimum requis : free | premium | pro '
                                  '(VARCHAR validé applicativement, comme '
                                  'role_client)')
    active = Column(Boolean, nullable=False, default=True,
                    comment='Interrupteur : faux = toute route marquée '
                            'exiger_fonctionnalite(cle) répond 403 explicite')
    description = Column(Text, nullable=True,
                         comment='Description lisible, renvoyée par GET /plans')

    def __repr__(self):
        return f"<Fonctionnalite(cle={self.cle}, active={self.active}, plan={self.plan_minimum})>"


class Abonnement(Base):
    """
    Intention / état d'abonnement d'un compte (fournisseur Jeko, Mission 1).

    POURQUOI CETTE TABLE EXISTE MÊME SANS FOURNISSEUR BRANCHÉ
    ---------------------------------------------------------
    POST /api/client/v1/subscribe, sans clés JEKO_*, répond un état explicite
    `non_configure` ET enregistre l'INTENTION ici : aucune demande du
    propriétaire n'est perdue, la souscription sera traitée dès l'activation
    du fournisseur. Avec clés (sandbox), la ligne porte la référence du
    fournisseur et le webhook signé POST /api/webhooks/jeko met le statut à
    jour ; statut `actif` élève le plan du compte (user.plan).

    Aucun montant : la tarification n'est pas décidée (décision du
    propriétaire — cf. EXTENSIBILITE.md §décisions).
    """
    __tablename__ = "abonnements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True,
                     comment='Compte qui demande / porte l\'abonnement')
    plan = Column(String(20), nullable=False,
                  comment='Plan demandé : premium | pro (free n\'est pas '
                          'souscriptible — refus explicite)')
    statut = Column(String(30), nullable=False, index=True,
                    comment='intention (enregistrée sans fournisseur) | '
                            'en_attente (fournisseur appelé, webhook attendu) '
                            '| actif | annule | echec_fournisseur')
    fournisseur = Column(String(30), nullable=False, default='jeko',
                         comment='Fournisseur d\'abonnement (un seul aujourd\'hui)')
    reference_fournisseur = Column(String(200), nullable=True, index=True,
                                   comment='Identifiant de l\'abonnement chez le '
                                           'fournisseur — clé de rapprochement '
                                           'du webhook')
    donnees = Column('metadata', JSON, nullable=True,
                     comment='Données additionnelles du fournisseur (jamais de '
                             'secret, jamais de moyen de paiement)')

    date_creation = Column(TIMESTAMP, server_default=func.current_timestamp(),
                           comment='Création de l\'intention / de la souscription')
    date_mise_a_jour = Column(TIMESTAMP, server_default=func.current_timestamp(),
                              onupdate=func.current_timestamp(),
                              comment='Dernier changement de statut')

    def __repr__(self):
        return f"<Abonnement(id={self.id}, user={self.user_id}, plan={self.plan}, statut={self.statut})>"


class AppAnalytics(Base):
    """
    Tracking APPLICATIF (usage de l'app Mia, Mission 2) — PAS le tracking des
    conversations visiteurs (celui-là vit dans `chatbot_analytics`).

    Ce que la table enregistre : l'usage de l'APP par ses installations —
    installation, ouverture, sessions, écrans vus, intention d'upgrade,
    trace de consentement. CE QU'ELLE N'ENREGISTRE PAS : aucune donnée
    personnelle du visiteur final du site client, aucune conversation (RGPD :
    le champ `metadata` est borné et l'app n'y met pas d'identité de visiteur).

    LOCAL-FIRST : `date_evenement` est l'horodatage du CLIENT (l'événement est
    daté au moment où il se produit, même hors ligne) ; `date_reception` est
    l'horodatage SERVEUR (borne de confiance pour les périodes d'agrégation).
    La déduplication repose sur `event_id` (UUID fourni par l'app, UNIQUE) :
    rejouer un batch au retour du réseau n'écrit RIEN de plus.
    """
    __tablename__ = "app_analytics"

    id = Column(Integer, primary_key=True, autoincrement=True)

    #: UUID produit PAR L'APP (client) : c'est l'identité de l'événement, la
    #: clé de déduplication. Un rejeu exact est ignoré silencieusement (200).
    event_id = Column(String(64), nullable=False, unique=True, index=True,
                      comment='UUID fourni par l\'app — déduplication')
    installation_id = Column(String(64), nullable=False, index=True,
                             comment='Identifiant d\'installation (avant '
                                     'connexion, sans aucune identité '
                                     'personnelle)')
    user_id = Column(Integer, nullable=True, index=True,
                     comment='Compte Mia, quand l\'événement est envoyé '
                             'authentifié (null avant connexion)')
    site_id = Column(String(100), nullable=True, index=True,
                     comment='Site de l\'app, renseigné par l\'app ou déduit '
                             'du compte authentifié')

    event_type = Column(String(50), nullable=False, index=True,
                        comment='install | app_open | session_start | '
                                'session_end | screen_view | feature_use | '
                                'notification_open | upgrade_intent | consent '
                                '(énumération applicative extensible — cf. '
                                'EXTENSIBILITE.md)')
    donnees = Column('metadata', JSON, nullable=True,
                     comment='Métadonnées de l\'événement (écran vu, '
                             'fonctionnalité utilisée…). Borne : 4 Ko par '
                             'événement. AUCUNE donnée personnelle de '
                             'visiteur final')

    date_evenement = Column(TIMESTAMP, nullable=False,
                            comment='Horodatage CLIENT (local-first : l\'event '
                                    'est daté quand il se produit, hors ligne '
                                    'compris)')
    date_reception = Column(TIMESTAMP, server_default=func.current_timestamp(),
                            index=True,
                            comment='Horodatage SERVEUR (borne de confiance '
                                    'des périodes d\'agrégation)')

    def __repr__(self):
        return (f"<AppAnalytics(event_id={self.event_id}, type={self.event_type}, "
                f"installation={self.installation_id})>")


class ConnaissanceProprietaire(Base):
    """
    Mode apprentissage (chantier F du lot du 24/09) : le propriétaire du site
    ENTRAÎNE son chatbot depuis le dashboard admin — questions/réponses
    fréquentes et documents texte. Ces données sont LES SIENNES : elles ont
    priorité sur les pages du site et le blog dans la composition du contexte
    (service.py — étape 3ter).
    """
    __tablename__ = "connaissances_proprietaire"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(String(100), nullable=False, index=True,
                     comment='Tenant propriétaire de la connaissance')
    # 'qr' : question + réponse explicite ; 'texte' : document libre (note,
    # URL annotée, extrait). Énumération fermée, validée à la route.
    type = Column(String(10), nullable=False,
                  comment="'qr' (question/réponse) | 'texte' (document libre)")
    question = Column(Text, nullable=True, comment="Question d'entraînement (type 'qr')")
    reponse = Column(Text, nullable=True, comment="Réponse à servir (type 'qr')")
    contenu = Column(Text, nullable=True, comment='Corps du document (type texte)')
    source_url = Column(String(500), nullable=True, comment="Origine du document, si URL")
    actif = Column(Boolean, nullable=False, default=True,
                   comment='False = archivé sans destruction (traçabilité)')
    cree_par = Column(String(200), nullable=True, comment='Identifiant admin créateur')
    cree_le = Column(TIMESTAMP, server_default=func.current_timestamp())
    maj_le = Column(TIMESTAMP, server_default=func.current_timestamp(),
                    onupdate=func.current_timestamp())

    def __repr__(self):
        return (f"<ConnaissanceProprietaire(id={self.id}, site={self.site_id}, "
                f"type={self.type})>")


# Indexes composés pour optimisation des requêtes
Index('idx_conversations_site_status', ChatbotConversation.site_id, ChatbotConversation.status)
Index('idx_conversations_site_started', ChatbotConversation.site_id, ChatbotConversation.started_at)
Index('idx_messages_conversation_created', ChatbotMessage.conversation_id, ChatbotMessage.created_at)
Index('idx_leads_site_created', ChatbotLead.site_id, ChatbotLead.created_at)
Index('idx_analytics_site_type_timestamp', ChatbotAnalytics.site_id, ChatbotAnalytics.event_type, ChatbotAnalytics.timestamp)
Index('idx_notifications_canal_created', ChatbotNotificationLog.canal, ChatbotNotificationLog.created_at)
Index('idx_notifications_statut_created', ChatbotNotificationLog.statut, ChatbotNotificationLog.created_at)
# L'envoi webpush ne demande qu'une chose : les abonnements ACTIFS, par site.
Index('idx_push_subscriptions_actif_site', PushSubscription.actif, PushSubscription.site_id)
# Boîte de réception in-app du propriétaire : les non lues d'abord.
Index('idx_client_notifications_site_lu', ClientNotification.site_id, ClientNotification.lu)
Index('idx_client_notifications_site_date', ClientNotification.site_id, ClientNotification.date_creation)

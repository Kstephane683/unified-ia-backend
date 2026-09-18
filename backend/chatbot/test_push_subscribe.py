#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests de l'interface publique d'abonnement au push navigateur (P3-PUSH).

LES SIX CAS EXIGÉS SONT COUVERTS EXPLICITEMENT :
  1. abonnement valide            — 200, ligne créée en base, aucun jeton requis ;
  2. corps invalide               — 422 (endpoint vide, clés absentes ou vides,
                                    schéma non https, domaine inconnu), jamais 500 ;
  3. réabonnement du même endpoint — AUCUN doublon : une seule ligne, mise à jour ;
  4. désabonnement                — la ligne passe `actif = faux`, elle est conservée ;
  5. envoi sans VAPID configuré   — état « non configuré », aucune exception ;
  6. abonnement enregistré mais clés absentes — dégradation propre, l'abonnement
                                    reste en base et l'envoi dit pourquoi il ne part pas.

Deux pièges connus du projet sont vérifiés ici plutôt que supposés :
  · les colonnes JSON (SQLAlchemy n'écrit pas une mutation en place sans
    `flag_modified()`) — la table n'en a AUCUNE, c'est vérifié ;
  · `= ANY(:liste)` sous psycopg2 — aucun SQL brut n'est employé, on le vérifie
    en exécutant réellement les requêtes.

Aucun réseau réel n'est utilisé : l'envoi vers un vrai service de push est
remplacé par un serveur local, et il n'est tenté que si la bibliothèque
`pywebpush` est réellement installée (sinon le test se saute, comme il doit).

Exécution :
    cd /home/ballo/OX6A/unified-ia-backend
    python3 -m pytest backend/chatbot/test_push_subscribe.py -q
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))

from backend.chatbot import notifications, push_abonnements  # noqa: E402
from backend.chatbot.models import (  # noqa: E402
    ChatbotNotificationLog,
    ChatbotPushSubscription,
    PushSubscription,
)
from backend.core.database import Base  # noqa: E402

# Import nécessaire au bon fonctionnement de `create_all` dans la suite
# complète : `backend/core/models` déclare la table `users`, cible d'une clé
# étrangère d'une table legacy. C'est aussi l'ordre du démarrage réel.
import backend.core.models  # noqa: E402,F401

#: Variables lues par le module d'envoi — neutralisées entre les tests.
VARIABLES_NOTIFICATION = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ADMIN_CHAT_ID",
    "BREVO_API_KEY",
    "BREVO_SENDER_EMAIL",
    "BREVO_SENDER_NAME",
    "VAPID_PUBLIC_KEY",
    "VAPID_PRIVATE_KEY",
    "VAPID_CONTACT",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
)

#: Endpoint d'apparence réelle : c'est le domaine qui compte, pas le jeton.
ENDPOINT_VALIDE = "https://fcm.googleapis.com/fcm/send/exemple-de-jeton-non-reel"
P256DH_VALIDE = "B" * 87
AUTH_VALIDE = "C" * 22


def charge(**remplacements) -> dict:
    """Corps d'abonnement valide, avec remplacements ciblés."""
    corps = {
        "endpoint": ENDPOINT_VALIDE,
        "keys": {"p256dh": P256DH_VALIDE, "auth": AUTH_VALIDE},
        "conversation_id": "conv-0001",
        "site_id": "eperformance_vitrine",
    }
    for cle, valeur in remplacements.items():
        if cle in ("p256dh", "auth"):
            corps["keys"][cle] = valeur
        else:
            corps[cle] = valeur
    return corps


@pytest.fixture
def sans_cles(monkeypatch):
    """Aucune clé de notification : le monde réel d'aujourd'hui."""
    for nom in VARIABLES_NOTIFICATION:
        monkeypatch.delenv(nom, raising=False)


@pytest.fixture
def base():
    """Base SQLite en mémoire, avec toutes les tables du chatbot."""
    moteur = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=moteur)
    Session = sessionmaker(bind=moteur)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        moteur.dispose()


@pytest.fixture(autouse=True)
def sans_limiteur_de_debit():
    """Le limiteur de l'application compte par IP : tous les tests partagent la
    même. Sans cette remise à zéro, les tests d'abonnement finiraient en 429."""
    from backend.api import app as app_module

    app_module._rate_bucket.clear()
    yield
    app_module._rate_bucket.clear()


@pytest.fixture
def client(base):
    """Client de test, base SQLite injectée, jetons admin et client."""
    from fastapi.testclient import TestClient

    from backend.api.app import app
    from backend.core.auth import create_access_token
    from backend.core.database import get_db

    def _db():
        try:
            yield base
        finally:
            pass

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as c:
        c.jeton_admin = create_access_token({"sub": "admin@eperformance.pro", "role": "admin"})
        yield c
    app.dependency_overrides.pop(get_db, None)


def abonner(client, **remplacements):
    """Appel réel de la route publique — sans aucun en-tête d'authentification."""
    return client.post("/api/chatbot/push/subscribe", json=charge(**remplacements))


# ============================================================
# 0. LA TABLE — DÉCLARATION, COLONNES, PIÈGES
# ============================================================


class TestTable:
    def test_la_table_est_declaree_pour_init_db(self):
        """`init_db()` ne crée que ce que `Base.metadata` connaît."""
        assert "push_subscriptions" in set(Base.metadata.tables)

    def test_la_table_se_cree_reellement(self, base):
        noms = set(inspect(base.get_bind()).get_table_names())
        assert "push_subscriptions" in noms

    def test_les_colonnes_demandees_existent(self, base):
        colonnes = {
            c["name"]
            for c in inspect(base.get_bind()).get_columns("push_subscriptions")
        }
        for attendue in (
            "endpoint",
            "keys_p256dh",
            "keys_auth",
            "conversation_id",
            "site_id",
            "date_creation",
            "date_derniere_utilisation",
            "user_agent",
            "actif",
        ):
            assert attendue in colonnes, attendue

    def test_l_endpoint_est_unique(self, base):
        inspecteur = inspect(base.get_bind())
        uniques = {
            tuple(c["column_names"])
            for c in inspecteur.get_indexes("push_subscriptions")
            if c.get("unique")
        }
        uniques |= {
            tuple(u["column_names"])
            for u in inspecteur.get_unique_constraints("push_subscriptions")
        }
        assert ("endpoint",) in uniques

    def test_aucune_colonne_json_donc_aucun_flag_modified_a_poser(self, base):
        """Le piège connu du projet est écarté par conception, pas contourné."""
        types = {
            c["name"]: str(c["type"]).upper()
            for c in inspect(base.get_bind()).get_columns("push_subscriptions")
        }
        assert not [nom for nom, type_ in types.items() if "JSON" in type_]

    def test_aucune_donnee_personnelle_dans_la_table(self, base):
        colonnes = {
            c["name"]
            for c in inspect(base.get_bind()).get_columns("push_subscriptions")
        }
        for interdit in ("nom", "email", "telephone", "prenom", "adresse", "visitor_ip"):
            assert interdit not in colonnes, interdit

    def test_aucune_cle_etrangere_vers_les_conversations(self, base):
        """L'abonnement doit survivre à la purge des conversations (12 mois)."""
        assert inspect(base.get_bind()).get_foreign_keys("push_subscriptions") == []

    def test_la_table_existante_de_la_tache_6_5_est_intacte(self, base):
        """Ajout seul : la table d'abonnements livrée par 6.5 est toujours là."""
        colonnes = {
            c["name"]
            for c in inspect(base.get_bind()).get_columns("chatbot_push_subscriptions")
        }
        for attendue in ("endpoint", "cle_p256dh", "cle_auth", "est_actif"):
            assert attendue in colonnes


# ============================================================
# 1. ABONNEMENT — 200 ET LIGNE CRÉÉE (PUBLIC)
# ============================================================


class TestAbonnement:
    def test_abonnement_valide_repond_200_et_cree_la_ligne(self, client, base, sans_cles):
        reponse = abonner(client)

        assert reponse.status_code == 200
        corps = reponse.json()
        assert corps["abonnement"]["cree"] is True
        assert corps["abonnement"]["actif"] is True

        ligne = base.query(PushSubscription).one()
        assert ligne.endpoint == ENDPOINT_VALIDE
        assert ligne.keys_p256dh == P256DH_VALIDE
        assert ligne.keys_auth == AUTH_VALIDE
        assert ligne.conversation_id == "conv-0001"
        assert ligne.site_id == "eperformance_vitrine"
        assert ligne.actif is True
        assert ligne.date_creation is not None

    def test_le_visiteur_s_abonne_SANS_JETON(self, client, base, sans_cles):
        """Un visiteur n'a pas de compte : exiger un jeton tuerait la fonction."""
        reponse = client.post(
            "/api/chatbot/push/subscribe", json=charge(), headers={}
        )
        assert reponse.status_code == 200
        assert base.query(PushSubscription).count() == 1

    def test_l_abonnement_ne_depend_PAS_des_cles_vapid(self, client, base, sans_cles):
        """Point dur : zéro variable de notification, l'abonnement s'enregistre."""
        reponse = abonner(client)
        assert reponse.status_code == 200
        assert reponse.json()["canal"]["configure"] is False
        assert base.query(PushSubscription).count() == 1

    def test_le_user_agent_est_conserve_pour_le_diagnostic(self, client, base, sans_cles):
        client.post(
            "/api/chatbot/push/subscribe",
            json=charge(),
            headers={"user-agent": "NavigateurDeTest/1.0"},
        )
        assert base.query(PushSubscription).one().user_agent == "NavigateurDeTest/1.0"

    def test_les_cles_ne_sont_jamais_renvoyees(self, client, sans_cles):
        corps = abonner(client).json()
        texte = json.dumps(corps)
        assert P256DH_VALIDE not in texte
        assert AUTH_VALIDE not in texte
        assert "keys" not in json.dumps(corps["abonnement"])

    def test_l_endpoint_complet_n_est_pas_renvoye(self, client, sans_cles):
        """Un endpoint est une capacité : on n'en renvoie qu'une forme courte."""
        corps = abonner(client).json()
        assert corps["abonnement"]["endpoint_tronque"] != ENDPOINT_VALIDE
        assert ENDPOINT_VALIDE not in json.dumps(corps)


# ============================================================
# 2. CORPS INVALIDE — 422, JAMAIS 500
# ============================================================


class TestCorpsInvalide:
    @pytest.mark.parametrize(
        "nom, corps",
        [
            ("endpoint vide", charge(endpoint="")),
            ("endpoint absent", {"keys": {"p256dh": P256DH_VALIDE, "auth": AUTH_VALIDE}}),
            ("cles absentes", {"endpoint": ENDPOINT_VALIDE}),
            ("p256dh vide", charge(p256dh="")),
            ("auth vide", charge(auth="")),
            ("p256dh absent", {"endpoint": ENDPOINT_VALIDE, "keys": {"auth": AUTH_VALIDE}}),
            ("auth absent", {"endpoint": ENDPOINT_VALIDE, "keys": {"p256dh": P256DH_VALIDE}}),
            ("p256dh trop court", charge(p256dh="B" * 10)),
            ("cles hors base64url", charge(p256dh="B" * 60 + "!!!!")),
            ("endpoint non https", charge(endpoint="http://fcm.googleapis.com/fcm/send/x")),
            ("endpoint sans domaine", charge(endpoint="https:///fcm/send")),
            ("corps vide", {}),
        ],
    )
    def test_corps_invalide_repond_422(self, client, base, sans_cles, nom, corps):
        reponse = client.post("/api/chatbot/push/subscribe", json=corps)
        assert reponse.status_code == 422, f"{nom} → {reponse.status_code}"
        assert base.query(PushSubscription).count() == 0

    def test_endpoint_d_un_domaine_inconnu_repond_422(self, client, base, sans_cles):
        reponse = abonner(client, endpoint="https://exemple.test/push/abc")
        assert reponse.status_code == 422
        assert "domaine non autorisé" in reponse.text
        assert base.query(PushSubscription).count() == 0

    @pytest.mark.parametrize(
        "endpoint",
        [
            "https://127.0.0.1/push/abc",                    # adresse littérale
            "https://localhost/push/abc",                    # boucle locale
            "https://169.254.169.254/latest/meta-data/",     # métadonnées d'hébergeur
            "https://10.0.0.5/push/abc",                     # réseau privé
        ],
    )
    def test_un_endpoint_interne_est_refuse(self, client, base, sans_cles, endpoint):
        """Sans ce filtre, l'abonnement public serait un relais vers le réseau
        interne : c'est le risque propre à une route d'écriture ouverte."""
        reponse = abonner(client, endpoint=endpoint)
        assert reponse.status_code == 422
        assert base.query(PushSubscription).count() == 0

    @pytest.mark.parametrize(
        "endpoint",
        [
            "https://evilfcm.googleapis.com/fcm/send/x",
            "https://fcm.googleapis.com.attaquant.test/fcm/send/x",
            "https://xfcm.googleapis.com/fcm/send/x",
        ],
    )
    def test_un_domaine_qui_imite_un_fournisseur_est_refuse(
        self, client, base, sans_cles, endpoint
    ):
        """La comparaison exige une frontière sur un point."""
        assert abonner(client, endpoint=endpoint).status_code == 422

    def test_endpoint_trop_long_repond_422(self, client, base, sans_cles):
        trop_long = "https://fcm.googleapis.com/fcm/send/" + "a" * 3000
        assert abonner(client, endpoint=trop_long).status_code == 422
        assert base.query(PushSubscription).count() == 0

    def test_les_trois_fournisseurs_reels_sont_acceptes(self, client, base, sans_cles):
        for endpoint in (
            "https://fcm.googleapis.com/fcm/send/jeton",
            "https://updates.push.services.mozilla.com/wpush/v2/jeton",
            "https://web.push.apple.com/jeton",
            "https://wns2-bl2p.notify.windows.com/w/?token=jeton",
        ):
            reponse = abonner(client, endpoint=endpoint)
            assert reponse.status_code == 200, f"{endpoint} → {reponse.status_code}"

    def test_un_fournisseur_peut_etre_ajoute_par_variable_d_environnement(
        self, client, base, sans_cles, monkeypatch
    ):
        endpoint = "https://push.mon-auto-hebergement.test/wpush/x"
        assert abonner(client, endpoint=endpoint).status_code == 422

        monkeypatch.setenv("PUSH_ENDPOINTS_AUTORISES", "mon-auto-hebergement.test")
        assert abonner(client, endpoint=endpoint).status_code == 200


# ============================================================
# 3. RÉABONNEMENT — AUCUN DOUBLON
# ============================================================


class TestReabonnement:
    def test_meme_endpoint_ne_cree_pas_de_doublon(self, client, base, sans_cles):
        premier = abonner(client)
        assert premier.json()["abonnement"]["cree"] is True

        second = abonner(client, p256dh="D" * 87, auth="E" * 22)
        assert second.status_code == 200
        assert second.json()["abonnement"]["cree"] is False

        assert base.query(PushSubscription).count() == 1
        ligne = base.query(PushSubscription).one()
        assert ligne.keys_p256dh == "D" * 87
        assert ligne.keys_auth == "E" * 22

    def test_le_reabonnement_apres_desabonnement_reactive(self, client, base, sans_cles):
        abonner(client)
        client.delete(
            "/api/chatbot/push/unsubscribe", params={"endpoint": ENDPOINT_VALIDE}
        )
        assert base.query(PushSubscription).one().actif is False

        reponse = abonner(client)
        assert reponse.status_code == 200
        assert reponse.json()["abonnement"]["actif"] is True
        assert base.query(PushSubscription).count() == 1
        assert base.query(PushSubscription).one().actif is True

    def test_la_date_de_creation_est_conservee(self, client, base, sans_cles):
        """`date_creation` date le PREMIER abonnement, pas le dernier."""
        abonner(client)
        ancienne = datetime(2020, 1, 1, 12, 0, 0)
        ligne = base.query(PushSubscription).one()
        ligne.date_creation = ancienne
        base.commit()

        abonner(client, p256dh="F" * 87)
        assert base.query(PushSubscription).one().date_creation == ancienne

    def test_le_contexte_est_conserve_quand_il_n_est_pas_fourni(self, client, base, sans_cles):
        """Un réabonnement sans conversation ne doit pas effacer la précédente."""
        abonner(client, conversation_id="conv-42", site_id="mon_site")
        abonner(client, conversation_id=None, site_id=None)

        ligne = base.query(PushSubscription).one()
        assert ligne.conversation_id == "conv-42"
        assert ligne.site_id == "mon_site"

    def test_le_contexte_est_mis_a_jour_quand_il_change(self, client, base, sans_cles):
        abonner(client, conversation_id="conv-1")
        abonner(client, conversation_id="conv-2", site_id="autre_site")

        ligne = base.query(PushSubscription).one()
        assert ligne.conversation_id == "conv-2"
        assert ligne.site_id == "autre_site"

    def test_un_endpoint_different_cree_une_seconde_ligne(self, client, base, sans_cles):
        abonner(client)
        abonner(client, endpoint="https://updates.push.services.mozilla.com/wpush/v2/x")
        assert base.query(PushSubscription).count() == 2

    def test_un_reabonnement_laisse_l_autre_abonnement_intact(self, client, base, sans_cles):
        """L'endpoint est unique : on ne peut pas écraser la ligne d'un autre."""
        abonner(client, endpoint="https://fcm.googleapis.com/fcm/send/visiteur-1")
        abonner(client, endpoint="https://fcm.googleapis.com/fcm/send/visiteur-2")

        premier = (
            base.query(PushSubscription)
            .filter(PushSubscription.endpoint == "https://fcm.googleapis.com/fcm/send/visiteur-1")
            .one()
        )
        assert premier.keys_p256dh == P256DH_VALIDE
        assert premier.actif is True


# ============================================================
# 4. DÉSABONNEMENT — LA LIGNE EST CONSERVÉE
# ============================================================


class TestDesabonnement:
    def test_le_desabonnement_passe_la_ligne_a_inactif(self, client, base, sans_cles):
        abonner(client)
        reponse = client.delete(
            "/api/chatbot/push/unsubscribe", params={"endpoint": ENDPOINT_VALIDE}
        )

        assert reponse.status_code == 200
        corps = reponse.json()
        assert corps["abonnements_desactives"] == 1
        assert corps["detail"] == {"public": 1, "admin": 0}

        ligne = base.query(PushSubscription).one()
        assert ligne.actif is False
        assert ligne.endpoint == ENDPOINT_VALIDE

    def test_le_desabonnement_ne_supprime_rien(self, client, base, sans_cles):
        """La trace sert au diagnostic : la ligne doit survivre."""
        abonner(client)
        client.delete("/api/chatbot/push/unsubscribe", params={"endpoint": ENDPOINT_VALIDE})
        assert base.query(PushSubscription).count() == 1

    def test_le_desabonnement_est_idempotent(self, client, sans_cles):
        abonner(client)
        premier = client.delete(
            "/api/chatbot/push/unsubscribe", params={"endpoint": ENDPOINT_VALIDE}
        )
        second = client.delete(
            "/api/chatbot/push/unsubscribe", params={"endpoint": ENDPOINT_VALIDE}
        )
        assert premier.json()["abonnements_desactives"] == 1
        assert second.status_code == 200
        assert second.json()["abonnements_desactives"] == 0
        assert "aucun abonnement actif" in second.json()["message"]

    def test_un_endpoint_inconnu_ne_produit_ni_erreur_ni_ecriture(
        self, client, base, sans_cles
    ):
        abonner(client)
        reponse = client.delete(
            "/api/chatbot/push/unsubscribe",
            params={"endpoint": "https://fcm.googleapis.com/fcm/send/jamais-vu"},
        )
        assert reponse.status_code == 200
        assert reponse.json()["abonnements_desactives"] == 0
        assert base.query(PushSubscription).one().actif is True

    def test_endpoint_manquant_repond_422(self, client, sans_cles):
        assert client.delete("/api/chatbot/push/unsubscribe").status_code == 422
        assert client.delete("/api/chatbot/push/unsubscribe?endpoint=").status_code == 422

    def test_on_ne_desabonne_pas_le_navigateur_d_un_autre(self, client, base, sans_cles):
        """L'endpoint exact est exigé : c'est lui qui tient lieu d'autorisation."""
        abonner(client, endpoint="https://fcm.googleapis.com/fcm/send/visiteur-1")
        abonner(client, endpoint="https://fcm.googleapis.com/fcm/send/visiteur-2")

        client.delete(
            "/api/chatbot/push/unsubscribe",
            params={"endpoint": "https://fcm.googleapis.com/fcm/send/visiteur-1"},
        )

        restant = (
            base.query(PushSubscription)
            .filter(PushSubscription.endpoint == "https://fcm.googleapis.com/fcm/send/visiteur-2")
            .one()
        )
        assert restant.actif is True

    def test_une_conversation_qui_ne_correspond_pas_ne_desabonne_pas(
        self, client, base, sans_cles
    ):
        abonner(client, conversation_id="conv-1")
        reponse = client.delete(
            "/api/chatbot/push/unsubscribe",
            params={"endpoint": ENDPOINT_VALIDE, "conversation_id": "conv-autre"},
        )
        assert reponse.json()["abonnements_desactives"] == 0
        assert base.query(PushSubscription).one().actif is True

    def test_le_desabonnement_touche_aussi_la_ligne_de_la_tache_6_5(
        self, client, base, sans_cles
    ):
        """Même navigateur inscrit des deux côtés : se désabonner doit vraiment
        l'arrêter, sinon le visiteur reçoit encore ce qu'il a demandé d'arrêter."""
        base.add(
            ChatbotPushSubscription(
                endpoint=ENDPOINT_VALIDE,
                cle_p256dh=P256DH_VALIDE,
                cle_auth=AUTH_VALIDE,
                est_actif=True,
            )
        )
        base.commit()

        abonner(client)
        reponse = client.delete(
            "/api/chatbot/push/unsubscribe", params={"endpoint": ENDPOINT_VALIDE}
        )

        assert reponse.json()["detail"] == {"public": 1, "admin": 1}
        assert base.query(ChatbotPushSubscription).one().est_actif is False


# ============================================================
# 5. ENVOI SANS CONFIGURATION — ÉTAT EXPLICITE, JAMAIS D'EXCEPTION
# ============================================================


class TestEnvoiDegrade:
    def test_envoi_sans_vapid_est_non_configure_et_ne_leve_pas(self, sans_cles, monkeypatch):
        def interdit(*args, **kwargs):
            raise AssertionError("aucun appel réseau ne doit être tenté")

        monkeypatch.setattr("requests.post", interdit)
        resultat = notifications.envoyer(
            "webpush", "", "Sujet", "Message", abonnements=[]
        )
        assert resultat.succes is False
        assert resultat.statut == "non_configure"
        assert "VAPID" in resultat.erreur

    def test_abonnement_enregistre_mais_cles_absentes_degrade_proprement(
        self, client, base, sans_cles
    ):
        """Le cas 6 exigé : l'abonnement existe, les clés non. L'envoi doit dire
        pourquoi il ne part pas — et l'abonnement doit rester en base."""
        abonner(client)

        reponse = client.post(
            "/api/chatbot/admin/notify",
            json={"canal": "webpush", "sujet": "Test", "message": "Bonjour"},
            headers={"Authorization": f"Bearer {client.jeton_admin}"},
        )

        assert reponse.status_code == 503
        corps = reponse.json()
        assert corps["resultat"]["statut"] == "non_configure"
        assert corps["resultat"]["succes"] is False
        assert "VAPID" in corps["resultat"]["erreur"]

        trace = base.query(ChatbotNotificationLog).one()
        assert trace.statut == "non_configure"
        assert base.query(PushSubscription).one().actif is True

    def test_l_abonnement_du_widget_est_bien_transmis_a_l_envoi(
        self, client, base, sans_cles, monkeypatch
    ):
        """Le maillon manquant : ce que le widget enregistre doit atteindre
        l'envoi de la tâche 6.5, sans quoi rien ne partirait jamais."""
        abonner(client)
        capture = {}

        def faux_envoi(canal, destinataire, sujet, message, abonnements=None):
            capture["abonnements"] = list(abonnements or [])
            return notifications.ResultatEnvoi(
                canal=canal, succes=True, statut="envoye", destinataire="1 abonnement",
                messages_envoyes=1,
            )

        monkeypatch.setattr(notifications, "envoyer", faux_envoi)
        reponse = client.post(
            "/api/chatbot/admin/notify",
            json={"canal": "webpush", "sujet": "Test", "message": "Bonjour"},
            headers={"Authorization": f"Bearer {client.jeton_admin}"},
        )

        assert reponse.status_code == 200
        endpoints = {a.endpoint for a in capture["abonnements"]}
        assert ENDPOINT_VALIDE in endpoints
        assert {a.source for a in capture["abonnements"]} == {"public"}

    def test_les_deux_tables_sont_lues_et_dedoublonnees(self, base, sans_cles):
        """Un même navigateur inscrit des deux côtés ne doit recevoir qu'un envoi."""
        base.add(
            ChatbotPushSubscription(
                endpoint="https://fcm.googleapis.com/fcm/send/double",
                cle_p256dh=P256DH_VALIDE,
                cle_auth=AUTH_VALIDE,
                est_actif=True,
            )
        )
        base.add(
            PushSubscription(
                endpoint="https://fcm.googleapis.com/fcm/send/double",
                keys_p256dh="D" * 87,
                keys_auth="E" * 22,
                actif=True,
            )
        )
        base.add(
            PushSubscription(
                endpoint="https://fcm.googleapis.com/fcm/send/public-seul",
                keys_p256dh=P256DH_VALIDE,
                keys_auth=AUTH_VALIDE,
                actif=True,
            )
        )
        base.commit()

        abonnements = push_abonnements.abonnements_actifs(base)
        endpoints = [a.endpoint for a in abonnements]

        assert len(endpoints) == 2
        assert endpoints.count("https://fcm.googleapis.com/fcm/send/double") == 1
        double = [a for a in abonnements if a.endpoint.endswith("double")][0]
        assert double.source == "public"
        assert double.cle_p256dh == "D" * 87

    def test_un_abonnement_desactive_n_est_pas_transmis(self, base, sans_cles):
        base.add(
            PushSubscription(
                endpoint=ENDPOINT_VALIDE,
                keys_p256dh=P256DH_VALIDE,
                keys_auth=AUTH_VALIDE,
                actif=False,
            )
        )
        base.commit()
        assert push_abonnements.abonnements_actifs(base) == []

    def test_l_horodatage_d_utilisation_est_ecrit_apres_un_envoi_reussi(
        self, client, base, sans_cles, monkeypatch
    ):
        abonner(client)
        assert base.query(PushSubscription).one().date_derniere_utilisation is None

        monkeypatch.setattr(
            notifications,
            "envoyer",
            lambda canal, destinataire, sujet, message, abonnements=None: (
                notifications.ResultatEnvoi(
                    canal=canal, succes=True, statut="envoye",
                    destinataire="1 abonnement", messages_envoyes=1,
                )
            ),
        )
        client.post(
            "/api/chatbot/admin/notify",
            json={"canal": "webpush", "sujet": "Test", "message": "Bonjour"},
            headers={"Authorization": f"Bearer {client.jeton_admin}"},
        )

        assert base.query(PushSubscription).one().date_derniere_utilisation is not None

    def test_pas_d_horodatage_quand_l_envoi_echoue(self, client, base, sans_cles, monkeypatch):
        abonner(client)
        monkeypatch.setattr(
            notifications,
            "envoyer",
            lambda canal, destinataire, sujet, message, abonnements=None: (
                notifications.ResultatEnvoi(
                    canal=canal, succes=False, statut="echec",
                    destinataire="", erreur="refus du service de push",
                )
            ),
        )
        client.post(
            "/api/chatbot/admin/notify",
            json={"canal": "webpush", "sujet": "Test", "message": "Bonjour"},
            headers={"Authorization": f"Bearer {client.jeton_admin}"},
        )
        assert base.query(PushSubscription).one().date_derniere_utilisation is None

    def test_le_module_d_envoi_reste_sans_import_de_pywebpush(self):
        """L'import paresseux est la règle qui évite la panne de démarrage."""
        assert "pywebpush" not in sys.modules

    def test_le_listage_admin_montre_les_deux_sources_sans_les_cles(
        self, client, base, sans_cles
    ):
        abonner(client)
        reponse = client.get(
            "/api/chatbot/admin/push/subscriptions",
            headers={"Authorization": f"Bearer {client.jeton_admin}"},
        )
        assert reponse.status_code == 200
        corps = reponse.json()
        assert corps["resume"]["widget"]["actifs"] == 1
        assert corps["abonnements"][0]["source"] == "widget"
        assert P256DH_VALIDE not in reponse.text
        assert ENDPOINT_VALIDE not in reponse.text

    def test_le_listage_admin_exige_un_administrateur(self, client, sans_cles):
        assert client.get("/api/chatbot/admin/push/subscriptions").status_code == 401


# ============================================================
# 6. ENVOI RÉEL AVEC LA BIBLIOTHÈQUE (serveur local, aucune sortie réseau)
# ============================================================
#
# Ce test s'exécute DANS UN SOUS-PROCESSUS, pour deux raisons :
#   · la bibliothèque `pywebpush` ne doit pas être importée dans le processus de
#     la suite (un autre test vérifie qu'elle ne l'est pas au chargement) ;
#   · il prouve ce que les tests de la tâche 6.5 ne pouvaient pas prouver : que
#     l'envoi produit un VRAI message chiffré et signé avec la vraie
#     bibliothèque, et non avec une doublure.
# Il se saute proprement si `pywebpush` n'est pas installée — c'est le cas d'un
# environnement qui n'a pas encore installé les dépendances à jour.

SCRIPT_ENVOI_REEL = r'''
import base64, json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer

RACINE = sys.argv[1]
recu = {}

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        longueur = int(self.headers.get("content-length") or 0)
        recu["corps"] = self.rfile.read(longueur)
        recu["entetes"] = {k.lower(): v for k, v in self.headers.items()}
        self.send_response(201)
        self.end_headers()

    def log_message(self, *args):
        pass

serveur = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=serveur.handle_request, daemon=True).start()

from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric import ec

def b64url(octets):
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode()

# Clés VAPID générées à la volée : jamais écrites sur disque, jamais versionnées.
privee = ec.generate_private_key(ec.SECP256R1())
os.environ["VAPID_PUBLIC_KEY"] = b64url(
    privee.public_key().public_bytes(ser.Encoding.X962, ser.PublicFormat.UncompressedPoint)
)
os.environ["VAPID_PRIVATE_KEY"] = b64url(
    privee.private_bytes(ser.Encoding.DER, ser.PrivateFormat.PKCS8, ser.NoEncryption())
)
os.environ["VAPID_CONTACT"] = "notifications@exemple.test"

sys.path.insert(0, RACINE)
from backend.chatbot import notifications
from backend.chatbot.push_abonnements import AbonnementPush

# Abonnement synthétique, construit EXACTEMENT comme un navigateur le produit :
# point P-256 non compressé pour p256dh, 16 octets aléatoires pour auth.
navigateur = ec.generate_private_key(ec.SECP256R1())
abonnement = AbonnementPush(
    endpoint="http://127.0.0.1:%d/push/exemple" % serveur.server_address[1],
    cle_p256dh=b64url(navigateur.public_key().public_bytes(
        ser.Encoding.X962, ser.PublicFormat.UncompressedPoint)),
    cle_auth=b64url(os.urandom(16)),
    source="public",
    identifiant=1,
)

resultat = notifications.envoyer(
    "webpush", "", "Nouveau lead", "Un visiteur demande un devis.",
    abonnements=[abonnement],
)
time.sleep(0.4)

corps = recu.get("corps", b"")
lisible = False
try:
    json.loads(corps.decode("utf-8"))
    lisible = True
except Exception:
    lisible = False

# DÉCHIFFREMENT RÉEL du message, avec la clé privée du navigateur : c'est la
# seule façon de prouver que le contenu reçu est bien celui attendu — et
# qu'aucun nom interne ne s'y trouve. Le message est chiffré pour le
# navigateur ; le serveur local joue ici le rôle du navigateur.
dechiffre = ""
try:
    import http_ece

    dechiffre = http_ece.decrypt(
        corps,
        private_key=navigateur,
        auth_secret=base64.urlsafe_b64decode(abonnement.cle_auth + "=="),
        version="aes128gcm",
    ).decode("utf-8")
except Exception as exc:
    dechiffre = "ECHEC_DECHIFFREMENT: %s: %s" % (type(exc).__name__, exc)

# Le JETON VAPID est un JWT : on en lit la charge utile, sans cle, pour verifier
# que l'audience vise bien le service de push et que le contact est celui attendu.
autorisation = recu.get("entetes", {}).get("authorization", "")
charge_jeton = {}
try:
    jeton = autorisation.split("t=", 1)[1].split(",")[0]
    partie = jeton.split(".")[1]
    partie += "=" * (-len(partie) % 4)
    charge_jeton = json.loads(base64.urlsafe_b64decode(partie).decode("utf-8"))
except Exception:
    charge_jeton = {}

print(json.dumps({
    "statut": resultat.statut,
    "succes": resultat.succes,
    "erreur": resultat.erreur,
    "messages_envoyes": resultat.messages_envoyes,
    "endpoint": abonnement.endpoint,
    "requete_recue": bool(recu),
    "entete_autorisation": autorisation,
    "entete_chiffrement": recu.get("entetes", {}).get("content-encoding", ""),
    "type_contenu": recu.get("entetes", {}).get("content-type", ""),
    "taille_corps": len(corps),
    "corps_lisible_en_clair": lisible,
    "contenu_dechiffre": dechiffre,
    "motif_agent_dans_le_corps": "agent" in corps.decode("utf-8", "ignore").lower(),
    "jeton_audience": charge_jeton.get("aud"),
    "jeton_contact": charge_jeton.get("sub"),
    "jeton_expiration": charge_jeton.get("exp"),
}, ensure_ascii=False))
'''


@pytest.fixture
def pywebpush_installe():
    """Saute le test si la bibliothèque n'est pas installée dans cet environnement."""
    import importlib.util

    if importlib.util.find_spec("pywebpush") is None:
        pytest.skip("pywebpush non installé dans cet environnement")
    if importlib.util.find_spec("cryptography") is None:
        pytest.skip("cryptography non installée dans cet environnement")


class TestEnvoiReel:
    def test_un_vrai_message_chiffre_et_signe_est_produit(self, pywebpush_installe):
        resultat = subprocess.run(
            [sys.executable, "-c", SCRIPT_ENVOI_REEL, str(RACINE)],
            cwd=str(RACINE),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert resultat.returncode == 0, resultat.stderr
        rapport = json.loads(resultat.stdout.strip().splitlines()[-1])

        assert rapport["succes"] is True, rapport
        assert rapport["statut"] == "envoye"
        assert rapport["messages_envoyes"] == 1
        assert rapport["requete_recue"] is True

        # Signature VAPID présente et bien formée (« vapid t=<jwt>,k=<clé> »).
        assert rapport["entete_autorisation"].startswith("vapid t=")
        assert ",k=" in rapport["entete_autorisation"]

        # Le jeton vise bien le service de push appelé, et porte le contact
        # configuré : la clé VAPID est utilisée, pas seulement présente.
        assert rapport["jeton_audience"] == rapport["endpoint"].rsplit("/push/", 1)[0]
        assert rapport["jeton_contact"] == "mailto:notifications@exemple.test"
        assert rapport["jeton_expiration"] > 0

        # Le corps est CHIFFRÉ : illisible en clair, donc aucune fuite de contenu.
        assert rapport["corps_lisible_en_clair"] is False
        assert rapport["taille_corps"] > 100

        # ...et il se déchiffre avec la clé du navigateur, qui est le seul à
        # pouvoir le lire. C'est la preuve que le message est bien formé.
        contenu = json.loads(rapport["contenu_dechiffre"])
        assert contenu["title"] == "Nouveau lead"
        assert contenu["body"] == "Un visiteur demande un devis."

        # Aucun terme interne ne figure dans ce qui part au navigateur. Le
        # contrôle porte sur les termes d'architecture (agent, persona,
        # routage), pas sur une liste de noms qui n'a rien à faire ici.
        texte_dechiffre = rapport["contenu_dechiffre"].lower()
        for interdit in ("agent", "persona", "router", "prompt"):
            assert interdit not in texte_dechiffre, interdit

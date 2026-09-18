#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests de la tâche 6.5 — notifications.

LES TROIS CAS EXIGÉS SONT COUVERTS EXPLICITEMENT :
  1. NON CONFIGURÉ     — clés absentes : état explicite, aucun envoi tenté,
                         aucune exception, trace écrite quand même ;
  2. CONFIGURÉ, ÉCHEC  — le fournisseur refuse (401) : échec tracé, jamais fatal ;
  3. SUCCÈS            — le fournisseur accepte : succès tracé avec son identifiant.

Est aussi vérifié le point dur de la tâche : le module s'importe et fonctionne
SANS aucune clé, dans un interpréteur neuf — c'est l'import manquant qui avait
provoqué une panne de production, on ne le reproduit pas.

Aucun réseau réel : `requests.post` est remplacé. Aucune base externe :
SQLite en mémoire.

Exécution :
    cd /home/ballo/OX6A/unified-ia-backend
    python3 -m pytest backend/chatbot/test_tache_6_5_notifications.py -q
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))

from backend.chatbot import notifications  # noqa: E402
from backend.chatbot.models import (  # noqa: E402
    ChatbotNotificationLog,
    ChatbotPushSubscription,
)
from backend.core.database import Base  # noqa: E402

# Import NÉCESSAIRE au bon fonctionnement de `create_all` dans les tests.
# Le module legacy `backend/communication/core/models.py` déclare une table
# `notifications` portant une clé étrangère vers `users` : quand la suite
# complète tourne, cette table est enregistrée sur la même `Base` que la nôtre,
# et `create_all` échoue si la table `users` n'est pas connue au même moment
# (« could not find table 'users' »). Importer `backend.core.models` garantit
# que la cible de la clé étrangère est déclarée.
# C'est aussi ce que fait le démarrage réel : `app.py` importe les routes, qui
# importent `backend.core.models`, AVANT d'appeler `init_db()`.
import backend.core.models  # noqa: E402,F401

# Variables d'environnement lues par le module — neutralisées entre les tests.
VARIABLES = (
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


@pytest.fixture
def sans_cles(monkeypatch):
    """Aucune clé de notification : le monde réel d'aujourd'hui."""
    for nom in VARIABLES:
        monkeypatch.delenv(nom, raising=False)


@pytest.fixture
def base():
    """Base SQLite en mémoire, avec les tables du chatbot."""
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


class FausseReponse:
    """Réponse HTTP simulée — imite ce que renvoient `requests` et le réseau."""

    def __init__(self, status_code, payload=None, texte=""):
        self.status_code = status_code
        self._payload = payload
        self.text = texte or str(payload or "")

    def json(self):
        if self._payload is None:
            raise ValueError("pas de JSON")
        return self._payload


# ============================================================
# 0. DÉMARRAGE — LE POINT DUR
# ============================================================


class TestDemarrage:
    def test_le_module_s_importe_dans_un_interpreteur_sans_aucune_cle(self):
        """L'import ne doit dépendre d'aucune clé ni d'aucune bibliothèque."""
        environnement = {
            k: v for k, v in os.environ.items() if k not in VARIABLES
        }
        resultat = subprocess.run(
            [
                sys.executable,
                "-c",
                "import backend.chatbot.notifications as n; "
                "print('import ok', len(n.etat_canaux()))",
            ],
            cwd=str(RACINE),
            env=environnement,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert resultat.returncode == 0, resultat.stderr
        assert "import ok" in resultat.stdout

    def test_pywebpush_n_est_pas_importe_au_chargement(self):
        """La bibliothèque optionnelle ne doit pas être importée par le module."""
        assert "pywebpush" not in sys.modules

    def test_les_deux_tables_sont_declarees_pour_init_db(self):
        """`init_db()` ne crée que ce que `Base.metadata` connaît."""
        noms = set(Base.metadata.tables)
        assert "chatbot_notification_logs" in noms
        assert "chatbot_push_subscriptions" in noms

    def test_les_tables_existantes_ne_sont_pas_modifiees(self):
        """Ajout seul : les tables du chatbot d'origine sont toujours là."""
        noms = set(Base.metadata.tables)
        for attendue in (
            "chatbot_sites",
            "chatbot_conversations",
            "chatbot_messages",
            "chatbot_leads",
            "chatbot_analytics",
        ):
            assert attendue in noms

    def test_les_tables_nouvelles_se_creent_reellement(self, base):
        inspecteur = inspect(base.get_bind())
        noms = set(inspecteur.get_table_names())
        assert "chatbot_notification_logs" in noms
        assert "chatbot_push_subscriptions" in noms


# ============================================================
# 1. CAS « NON CONFIGURÉ »
# ============================================================


class TestNonConfigure:
    def test_etats_explicites_sans_aucune_cle(self, sans_cles):
        etats = {etat.canal: etat for etat in notifications.etat_canaux()}
        assert set(etats) == set(notifications.CANAUX)
        for etat in etats.values():
            assert etat.configure is False
            assert "non configuré" in etat.raison

    def test_l_etat_dit_quelle_variable_manque(self, sans_cles):
        etat = notifications.etat_canal("telegram")
        assert "TELEGRAM_BOT_TOKEN" in etat.raison
        assert "TELEGRAM_ADMIN_CHAT_ID" in etat.raison

    @pytest.mark.parametrize("canal", ["telegram", "email", "webpush", "whatsapp"])
    def test_aucun_envoi_n_est_tente_et_rien_ne_leve(self, sans_cles, monkeypatch, canal):
        """Le cas central : pas de clé → pas d'appel réseau, état explicite."""

        def interdit(*args, **kwargs):
            raise AssertionError("aucun appel réseau ne doit être tenté")

        monkeypatch.setattr("requests.post", interdit)
        resultat = notifications.envoyer(canal, "destinataire", "sujet", "message")

        assert resultat.succes is False
        assert resultat.statut == "non_configure"
        assert resultat.erreur
        assert resultat.messages_envoyes == 0

    def test_le_push_dit_que_les_cles_vapid_manquent(self, sans_cles):
        resultat = notifications.envoyer("webpush", "", "sujet", "message")
        assert resultat.statut == "non_configure"
        assert "VAPID" in resultat.erreur

    def test_le_push_dit_que_la_bibliotheque_manque_si_les_cles_existent(
        self, monkeypatch
    ):
        """Clés présentes mais bibliothèque absente : l'état doit le dire."""
        monkeypatch.setenv("VAPID_PUBLIC_KEY", "cle-publique-de-test")
        monkeypatch.setenv("VAPID_PRIVATE_KEY", "cle-privee-de-test")
        etat = notifications.etat_canal("webpush")
        if "pywebpush" in sys.modules or __import__("importlib.util", fromlist=["x"]).find_spec("pywebpush"):
            pytest.skip("pywebpush installé : ce test ne s'applique pas")
        assert etat.configure is False
        assert "pywebpush" in etat.raison

    def test_canal_inconnu_est_refuse_proprement(self, sans_cles):
        resultat = notifications.envoyer("pigeon-voyageur", "x", "sujet", "message")
        assert resultat.succes is False
        assert resultat.statut == "non_configure"
        assert "canal inconnu" in resultat.erreur

    def test_la_tentative_non_configuree_est_tracee(self, sans_cles, base):
        """C'est LE cas qu'on veut pouvoir constater après coup."""
        resultat = notifications.envoyer("telegram", "", "Rapport", "3 nouveaux leads")
        ligne = notifications.tracer(base, resultat, sujet="Rapport", message="3 nouveaux leads")

        assert ligne is not None
        assert ligne.statut == "non_configure"
        assert ligne.succes is False
        assert ligne.canal == "telegram"
        assert "TELEGRAM_BOT_TOKEN" in ligne.erreur
        assert base.query(ChatbotNotificationLog).count() == 1


# ============================================================
# 2. CAS « CONFIGURÉ MAIS L'ENVOI ÉCHOUE »
# ============================================================


@pytest.fixture
def telegram_configure(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:jeton-de-test")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "987654321")


class TestEchecDEnvoi:
    def test_refus_401_est_trace_sans_lever(self, telegram_configure, monkeypatch, base):
        monkeypatch.setattr(
            "requests.post",
            lambda *a, **k: FausseReponse(
                401, {"ok": False, "description": "Unauthorized"}
            ),
        )
        resultat = notifications.envoyer("telegram", "", "Alerte", "Message")

        assert resultat.succes is False
        assert resultat.statut == "echec"
        assert resultat.code_erreur == "401"
        assert "Unauthorized" in resultat.erreur

        ligne = notifications.tracer(base, resultat, sujet="Alerte", message="Message")
        assert ligne.statut == "echec"
        assert ligne.code_erreur == "401"

    def test_ip_non_autorisee_brevo_est_remontee_tel_quelle(self, monkeypatch, base):
        """Le cas réel mesuré : Brevo refuse l'adresse IP émettrice."""
        monkeypatch.setenv("BREVO_API_KEY", "xkeysib-de-test")
        monkeypatch.setenv("BREVO_SENDER_EMAIL", "notifications@eperformance.pro")
        monkeypatch.setattr(
            "requests.post",
            lambda *a, **k: FausseReponse(
                401,
                {
                    "message": "We have detected you are using an unrecognised IP address",
                    "code": "unauthorized",
                },
            ),
        )
        resultat = notifications.envoyer("email", "quelquun@exemple.test", "Sujet", "Message")

        assert resultat.succes is False
        assert resultat.statut == "echec"
        assert "unrecognised IP" in resultat.erreur
        notifications.tracer(base, resultat, sujet="Sujet", message="Message")
        assert base.query(ChatbotNotificationLog).filter_by(statut="echec").count() == 1

    def test_erreur_reseau_est_absorbee(self, telegram_configure, monkeypatch):
        """Une exception de la bibliothèque HTTP ne doit pas remonter."""

        def explose(*args, **kwargs):
            raise ConnectionError("réseau indisponible")

        monkeypatch.setattr("requests.post", explose)
        resultat = notifications.envoyer("telegram", "", "Sujet", "Message")

        assert resultat.succes is False
        assert resultat.statut == "echec"
        assert resultat.code_erreur == "ConnectionError"

    def test_timeout_est_absorbé(self, telegram_configure, monkeypatch):
        def explose(*args, **kwargs):
            raise TimeoutError("délai dépassé")

        monkeypatch.setattr("requests.post", explose)
        resultat = notifications.envoyer("telegram", "", "Sujet", "Message")
        assert resultat.succes is False
        assert resultat.statut == "echec"


# ============================================================
# 3. CAS « SUCCÈS »
# ============================================================


class TestSucces:
    def test_telegram_envoye_et_identifiant_conserve(self, telegram_configure, monkeypatch, base):
        monkeypatch.setattr(
            "requests.post",
            lambda *a, **k: FausseReponse(
                200, {"ok": True, "result": {"message_id": 4242}}
            ),
        )
        resultat = notifications.envoyer("telegram", "", "Nouveau lead", "Un visiteur demande un devis.")

        assert resultat.succes is True
        assert resultat.statut == "envoye"
        assert resultat.messages_envoyes == 1
        assert resultat.identifiant_fournisseur == "4242"
        assert resultat.duree_ms >= 0

        ligne = notifications.tracer(
            base, resultat, sujet="Nouveau lead", message="Un visiteur demande un devis."
        )
        assert ligne.statut == "envoye"
        assert ligne.identifiant_fournisseur == "4242"
        assert ligne.envoye_le is not None

    def test_email_envoye(self, monkeypatch, base):
        monkeypatch.setenv("BREVO_API_KEY", "xkeysib-de-test")
        monkeypatch.setenv("BREVO_SENDER_EMAIL", "notifications@eperformance.pro")
        monkeypatch.setattr(
            "requests.post",
            lambda *a, **k: FausseReponse(201, {"messageId": "<abc@brevo>"}),
        )
        resultat = notifications.envoyer("email", "destinataire@exemple.test", "Sujet", "Message")

        assert resultat.succes is True
        assert resultat.identifiant_fournisseur == "<abc@brevo>"
        assert resultat.destinataire == "destinataire@exemple.test"

    def test_le_destinataire_par_defaut_de_telegram_est_utilise(
        self, telegram_configure, monkeypatch
    ):
        capture = {}

        def capture_post(url, **kwargs):
            capture["url"] = url
            capture["json"] = kwargs.get("json")
            return FausseReponse(200, {"ok": True, "result": {"message_id": 1}})

        monkeypatch.setattr("requests.post", capture_post)
        notifications.envoyer("telegram", "", "Sujet", "Message")

        assert capture["json"]["chat_id"] == "987654321"
        assert "123456:jeton-de-test" in capture["url"]

    def test_le_sujet_et_le_message_sont_transmis(self, telegram_configure, monkeypatch):
        capture = {}

        def capture_post(url, **kwargs):
            capture["json"] = kwargs.get("json")
            return FausseReponse(200, {"ok": True, "result": {"message_id": 1}})

        monkeypatch.setattr("requests.post", capture_post)
        notifications.envoyer("telegram", "", "Nouveau lead", "Un visiteur demande un devis.")

        assert "Nouveau lead" in capture["json"]["text"]
        assert "Un visiteur demande un devis." in capture["json"]["text"]


# ============================================================
# 4. PUSH — STRUCTURE D'ABONNEMENTS
# ============================================================


class TestPush:
    def test_abonnement_enregistre_en_base(self, base):
        abonnement = ChatbotPushSubscription(
            endpoint="https://push.exemple.test/abc",
            cle_p256dh="cle-publique",
            cle_auth="secret-auth",
            libelle="Chrome bureau",
            est_actif=True,
        )
        base.add(abonnement)
        base.commit()

        assert base.query(ChatbotPushSubscription).count() == 1
        assert abonnement.id is not None

    def test_aucun_abonnement_actif_dit_pourquoi_l_envoi_echoue(self, monkeypatch):
        monkeypatch.setenv("VAPID_PUBLIC_KEY", "cle-publique-de-test")
        monkeypatch.setenv("VAPID_PRIVATE_KEY", "cle-privee-de-test")
        if __import__("importlib.util", fromlist=["x"]).find_spec("pywebpush") is None:
            resultat = notifications.envoyer("webpush", "", "Sujet", "Message", abonnements=[])
            assert resultat.succes is False
            assert resultat.statut == "non_configure"
        else:
            pytest.skip("pywebpush installé : chemin différent")

    def test_le_push_ne_stocke_aucune_donnee_personnelle(self, base):
        """Les colonnes de la table ne doivent pas pouvoir porter d'identité."""
        colonnes = {c["name"] for c in inspect(base.get_bind()).get_columns(
            "chatbot_push_subscriptions"
        )}
        for interdit in ("nom", "email", "telephone", "telephone_numero", "prenom"):
            assert interdit not in colonnes


# ============================================================
# 5. ENDPOINTS — AUTHENTIFICATION ET ÉTATS
# ============================================================


@pytest.fixture
def client(base, monkeypatch):
    """Client de test avec la base SQLite injectée et un jeton admin."""
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
        c.jeton_client = create_access_token({"sub": "client@exemple.test", "role": "client"})
        yield c
    app.dependency_overrides.pop(get_db, None)


class TestEndpoints:
    def test_notify_sans_jeton_refuse(self, client):
        reponse = client.post("/api/chatbot/admin/notify", json={"canal": "telegram", "message": "x"})
        assert reponse.status_code == 401

    def test_notify_avec_jeton_non_admin_refuse(self, client):
        reponse = client.post(
            "/api/chatbot/admin/notify",
            json={"canal": "telegram", "message": "x"},
            headers={"Authorization": f"Bearer {client.jeton_client}"},
        )
        assert reponse.status_code == 403

    def test_notifications_sans_jeton_refuse(self, client):
        assert client.get("/api/chatbot/notifications").status_code == 401

    def test_notifications_avec_jeton_non_admin_refuse(self, client):
        reponse = client.get(
            "/api/chatbot/notifications",
            headers={"Authorization": f"Bearer {client.jeton_client}"},
        )
        assert reponse.status_code == 403

    def test_notifications_liste_les_canaux_et_la_trace(self, client, sans_cles):
        reponse = client.get(
            "/api/chatbot/notifications",
            headers={"Authorization": f"Bearer {client.jeton_admin}"},
        )
        assert reponse.status_code == 200
        corps = reponse.json()
        assert {c["canal"] for c in corps["canaux"]} == set(notifications.CANAUX)
        assert all(c["configure"] is False for c in corps["canaux"])
        assert corps["notifications"] == []
        assert corps["resume"] == {"envoye": 0, "echec": 0, "non_configure": 0}

    def test_notify_non_configure_repond_503_avec_l_etat(self, client, sans_cles):
        """503 + état explicite : ni 500, ni 200 trompeur."""
        reponse = client.post(
            "/api/chatbot/admin/notify",
            json={"canal": "telegram", "sujet": "Test", "message": "Bonjour"},
            headers={"Authorization": f"Bearer {client.jeton_admin}"},
        )
        assert reponse.status_code == 503
        corps = reponse.json()
        assert corps["resultat"]["statut"] == "non_configure"
        assert corps["resultat"]["succes"] is False
        assert corps["canaux"]

    def test_notify_non_configure_laisse_une_trace(self, client, base, sans_cles):
        client.post(
            "/api/chatbot/admin/notify",
            json={"canal": "email", "sujet": "Test", "message": "Bonjour"},
            headers={"Authorization": f"Bearer {client.jeton_admin}"},
        )
        ligne = base.query(ChatbotNotificationLog).one()
        assert ligne.statut == "non_configure"
        assert ligne.auteur == "admin@eperformance.pro"

    def test_notify_echec_fournisseur_repond_502_et_trace(
        self, client, base, telegram_configure, monkeypatch
    ):
        monkeypatch.setattr(
            "requests.post",
            lambda *a, **k: FausseReponse(401, {"ok": False, "description": "Unauthorized"}),
        )
        reponse = client.post(
            "/api/chatbot/admin/notify",
            json={"canal": "telegram", "sujet": "Test", "message": "Bonjour"},
            headers={"Authorization": f"Bearer {client.jeton_admin}"},
        )
        assert reponse.status_code == 502
        assert reponse.json()["resultat"]["statut"] == "echec"
        assert base.query(ChatbotNotificationLog).filter_by(statut="echec").count() == 1

    def test_notify_succes_repond_200_et_trace(
        self, client, base, telegram_configure, monkeypatch
    ):
        monkeypatch.setattr(
            "requests.post",
            lambda *a, **k: FausseReponse(200, {"ok": True, "result": {"message_id": 7}}),
        )
        reponse = client.post(
            "/api/chatbot/admin/notify",
            json={"canal": "telegram", "sujet": "Nouveau lead", "message": "Un visiteur."},
            headers={"Authorization": f"Bearer {client.jeton_admin}"},
        )
        assert reponse.status_code == 200
        corps = reponse.json()
        assert corps["resultat"]["succes"] is True
        assert corps["resultat"]["identifiant_fournisseur"] == "7"

        ligne = base.query(ChatbotNotificationLog).one()
        assert ligne.statut == "envoye"
        assert ligne.sujet == "Nouveau lead"

    def test_abonnement_push_refuse_tant_que_non_configure(self, client, sans_cles):
        reponse = client.post(
            "/api/chatbot/admin/push/subscriptions",
            json={
                "endpoint": "https://push.exemple.test/abc",
                "cle_p256dh": "cle-publique-de-test",
                "cle_auth": "secret-de-test",
            },
            headers={"Authorization": f"Bearer {client.jeton_admin}"},
        )
        assert reponse.status_code == 503
        assert reponse.json()["canal"]["configure"] is False
        assert "pywebpush" in reponse.json()["message"]

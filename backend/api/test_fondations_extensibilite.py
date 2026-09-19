#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests des fondations d'extensibilité de l'app Mia (Missions 1 à 4).

CE QUE CETTE SUITE PROUVE
-------------------------
M1 — Feature flags + abonnements : seed IDEMPOTENTE du catalogue ; /me expose
     plan + fonctionnalites_actives + fonctionnalites_verrouillees ; /plans
     répond un « catalogue de démonstration » explicite ; /subscribe sans
     clés Jeko répond `non_configure` ET enregistre l'intention ; le webhook
     Jeko refuse un appel non signé (400), refuse une mauvaise signature
     (400), et un appel signé met à jour l'abonnement ET élève le plan.
     Le verrou exiger_fonctionnalite est prouvé END-TO-END via la route
     export (flag inactif → 403 explicite, plan insuffisant → 403 explicite).
M2 — Tracking applicatif : batch public accepté, DÉDUPLICATION par event_id
     (rejeu ignoré silencieusement), enrichissement authentifié, types
     inconnus refusés 422, agrégats SCOPÉS au site du compte (les événements
     d'un autre site ne fuient pas), admin sans site_id → 400.
M3 — WhatsApp inactif par défaut : sans WHATSAPP_ENABLED, l'état du canal est
     « désactivé », tout envoi répond `non_configure` SANS AUCUN appel
     réseau ; activé, les templates structurés (nouveau_lead, escalade)
     produisent le payload Meta attendu ; webhook : GET hub.challenge +
     POST statuts avec signature X-Hub-Signature-256 (403 si invalide) et
     trace écrite.
M4 — RCS inactif par défaut : canal présent dans CANAUX, état « désactivé »,
     envoi `non_configure` sans appel réseau ; activé sans clés → « non
     configuré » nommant les variables manquantes ; structure texte + cartes
     déclarative ; fallback SMS DÉCLARATIF (jamais une réussite annoncée).

MÉTHODE : la VRAIE application FastAPI (backend.api.app) avec `get_db`
redirigé vers une base SQLite en mémoire — même méthode que
test_refonte_app_mia.py. Aucun réseau : tout appel sortant est INTERDIT par
un double du module `requests` qui échoue le test.

Exécution :
    cd /home/ballo/OX6A/unified-ia-backend
    python3 -m pytest backend/api/test_fondations_extensibilite.py -q
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

# Toutes les tables déclarées pour create_all (clé étrangère vers `users`
# déclarée sur la même Base — même raisonnement que les tests 6.5 et B1-B3).
import backend.core.models  # noqa: E402,F401
import backend.core.audit  # noqa: E402,F401 (déclare audit_log)
from backend.chatbot import notifications  # noqa: E402
from backend.chatbot.models import (  # noqa: E402
    Abonnement,
    AppAnalytics,
    ChatbotNotificationLog,
    ChatbotSite,
    Fonctionnalite,
)
from backend.core.database import Base, get_db  # noqa: E402
from backend.core.auth import (  # noqa: E402
    chiffrer_secret_totp,
    get_password_hash,
)
from backend.core.fonctionnalites import (  # noqa: E402
    FONCTIONNALITES_DEPART,
    seed_fonctionnalites,
)
from backend.core.models import User  # noqa: E402
from backend.api import app as app_module  # noqa: E402
from backend.api.app import app  # noqa: E402

# ============================================================
# Fixtures
# ============================================================

MDP = "mot-de-passe-tests-1"
SITE_A = "site_fondations_a"
SITE_B = "site_fondations_b"
INSTALLATION = "install-abc-123"

# Secret TOTP du propriétaire (client_admin : 2FA obligatoire, porte levée
# avec un code VALIDE — le secret est stocké chiffré, comme en production).
import pyotp  # jamais importé par le code de prod au chargement (règle)

SECRET_TOTP = pyotp.random_base32()


@pytest.fixture(autouse=True)
def sac_rate_limit_vierge():
    """Vide le sac in-memory du middleware entre les tests (isolement)."""
    app_module._rate_bucket.clear()
    yield
    app_module._rate_bucket.clear()


@pytest.fixture(autouse=True)
def env_purge(monkeypatch):
    """AUCUNE clé fournisseur dans l'environnement des tests : les états
    calculés ne doivent rien devoir à une variable résiduelle du poste."""
    for nom in (
        "JEKO_API_URL", "JEKO_API_KEY", "JEKO_WEBHOOK_SECRET",
        "WHATSAPP_ENABLED", "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_NOTIF_DESTINATAIRE",
        "WHATSAPP_APP_SECRET", "WHATSAPP_WEBHOOK_VERIFY_TOKEN",
        "RCS_ENABLED", "RCS_AGENT_ID", "RCS_API_URL", "RCS_API_KEY",
        "RCS_FALLBACK_SMS",
    ):
        monkeypatch.delenv(nom, raising=False)
    yield


@pytest.fixture
def base():
    """Base SQLite en mémoire avec TOUTES les tables (modèles + audit)."""
    moteur = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=moteur)
    Fabrique = sessionmaker(bind=moteur)
    session = Fabrique()
    try:
        yield session
    finally:
        session.close()
        moteur.dispose()


@pytest.fixture
def donnees(base):
    """Un monde minimal : 2 sites, un admin, un propriétaire (2FA active),
    le catalogue des fonctionnalités seedé."""
    base.add_all([
        ChatbotSite(site_id=SITE_A, site_name="Bistrot Fondations",
                    site_url="https://fondations-a.example",
                    sector="restauration", is_active=True),
        ChatbotSite(site_id=SITE_B, site_name="Boulangerie Voisine",
                    site_url="https://fondations-b.example",
                    sector="vitrine", is_active=True),
    ])
    base.add(User(
        email="admin@fondations-tests.fr",
        password_hash=get_password_hash(MDP),
        role="admin",
        is_active=True,
    ))
    base.add(User(
        email="proprio@fondations-tests.fr",
        password_hash=get_password_hash(MDP),
        role="client",
        role_client="client_admin",
        site_id=SITE_A,
        nom="Propriétaire Fondations",
        must_change_password=False,
        totp_secret=chiffrer_secret_totp(SECRET_TOTP),
        totp_enabled=True,  # la porte 2FA du rôle client_admin est levée
        is_active=True,
    ))
    base.commit()
    seed_fonctionnalites(base)
    return base


@pytest.fixture
def client_http(donnees):
    """TestClient branché sur la base de test (get_db redirigé)."""
    app.dependency_overrides[get_db] = lambda: donnees
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _jeton(client_http, email, mot_de_passe=MDP):
    form = {"username": email, "password": mot_de_passe}
    if email == "proprio@fondations-tests.fr":  # client_admin : 2FA active
        form["totp_code"] = pyotp.TOTP(SECRET_TOTP).now()
    reponse = client_http.post("/api/auth/login", data=form)
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


def _entetes(client_http, email="proprio@fondations-tests.fr"):
    jeton = _jeton(client_http, email)
    return {"Authorization": f"Bearer {jeton['access_token']}"}


def _signe(secret: str, corps: bytes) -> str:
    """Signature de contrat : HMAC-SHA256 hexadécimal du corps brut."""
    return hmac.new(secret.encode(), corps, hashlib.sha256).hexdigest()


# ============================================================
# Mission 1 — feature flags : seed, /me, /plans, verrou
# ============================================================


class TestSeedEtCatalogue:
    def test_la_seed_est_idempotente(self, donnees):
        seed_fonctionnalites(donnees)
        seed_fonctionnalites(donnees)
        cles = {f.cle for f in donnees.query(Fonctionnalite).all()}
        assert cles == {spec["cle"] for spec in FONCTIONNALITES_DEPART}
        assert len(cles) == 6

    def test_les_canaux_premium_sont_crees_inactifs(self, donnees):
        inactifs = {
            f.cle: f
            for f in donnees.query(Fonctionnalite).all()
            if not f.active
        }
        assert {"whatsapp_notifications", "rcs_messages", "abonnement_jeko"} <= set(inactifs)
        assert all(f.plan_minimum == "premium" for f in inactifs.values())

    def test_me_expose_plan_et_fonctionnalites(self, client_http):
        reponse = client_http.get("/api/client/v1/me", headers=_entetes(client_http))
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["plan"] == "free"
        assert "notifications_push" in corps["fonctionnalites_actives"]
        assert "analytics_export" in corps["fonctionnalites_actives"]
        assert "ia_en_direct" in corps["fonctionnalites_actives"]
        verrouillees = {v["cle"]: v for v in corps["fonctionnalites_verrouillees"]}
        assert set(verrouillees) == {
            "whatsapp_notifications", "rcs_messages", "abonnement_jeko",
        }
        # chaque verrouillée porte son plan requis — le contrat de l'app
        assert all(v["plan_requis"] == "premium" for v in verrouillees.values())

    def test_me_reflete_le_plan_du_compte(self, client_http, donnees):
        proprio = donnees.query(User).filter(
            User.email == "proprio@fondations-tests.fr").first()
        proprio.plan = "premium"
        donnees.commit()
        corps = client_http.get(
            "/api/client/v1/me", headers=_entetes(client_http)
        ).json()
        assert corps["plan"] == "premium"
        verrouillees = {v["cle"] for v in corps["fonctionnalites_verrouillees"]}
        # Le plan couvre premium, mais les canaux restent INACTIFS :
        # verrouillés pour une AUTRE raison, jamais prêts à tort.
        assert verrouillees == {"whatsapp_notifications", "rcs_messages",
                                "abonnement_jeko"}
        assert all("inactive" in v["raison"] for v in
                   corps["fonctionnalites_verrouillees"])

    def test_plans_catalogue_de_demonstration_explicite(self, client_http):
        reponse = client_http.get(
            "/api/client/v1/plans", headers=_entetes(client_http)
        )
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["catalogue"] == "démonstration"
        assert "tarification" in corps["note"].lower() or "décision" in corps["note"]
        assert [p["plan"] for p in corps["plans"]] == ["free", "premium", "pro"]
        par_plan = {p["plan"]: p for p in corps["plans"]}
        cles_free = {f["cle"] for f in par_plan["free"]["fonctionnalites"]}
        assert "notifications_push" in cles_free
        assert "whatsapp_notifications" not in cles_free
        cles_premium = {f["cle"] for f in par_plan["premium"]["fonctionnalites"]}
        assert {"whatsapp_notifications", "rcs_messages"} <= cles_premium

    def test_plans_exige_un_jeton(self, client_http):
        assert client_http.get("/api/client/v1/plans").status_code == 401


class TestVerrou:
    """Le verrou par fonctionnalité, prouvé END-TO-END via la route export."""

    def test_export_passe_quand_le_flag_est_actif_et_le_plan_suffisant(
        self, client_http
    ):
        reponse = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/analytics/export",
            headers=_entetes(client_http),
        )
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["export"] is True
        assert corps["fonctionnalite"] == "analytics_export"
        assert "donnees" in corps

    def test_flag_inactif_403_explicite(self, client_http, donnees):
        ligne = donnees.query(Fonctionnalite).filter(
            Fonctionnalite.cle == "analytics_export").first()
        ligne.active = False
        donnees.commit()
        reponse = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/analytics/export",
            headers=_entetes(client_http),
        )
        assert reponse.status_code == 403, reponse.text
        corps = reponse.json()
        assert corps["detail"] == "fonctionnalité verrouillée"
        assert corps["fonctionnalite"] == "analytics_export"
        assert corps["plan_requis"] == "free"
        assert corps["plan_actuel"] == "free"
        assert "inactive" in corps["raison"]

    def test_plan_insuffisant_403_explicite_avec_plan_requis(
        self, client_http, donnees
    ):
        ligne = donnees.query(Fonctionnalite).filter(
            Fonctionnalite.cle == "analytics_export").first()
        ligne.plan_minimum = "premium"
        donnees.commit()
        reponse = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/analytics/export",
            headers=_entetes(client_http),
        )
        assert reponse.status_code == 403, reponse.text
        corps = reponse.json()
        assert corps["detail"] == "fonctionnalité verrouillée"
        assert corps["plan_requis"] == "premium"
        assert corps["plan_actuel"] == "free"

    def test_l_isolation_passe_avant_le_verrou(self, client_http, donnees):
        """Un compte qui demande un site ÉTRANGER reçoit 404, JAMAIS la
        raison du verrou (ordre du contrat)."""
        ligne = donnees.query(Fonctionnalite).filter(
            Fonctionnalite.cle == "analytics_export").first()
        ligne.active = False
        ligne.plan_minimum = "pro"
        donnees.commit()
        reponse = client_http.get(
            f"/api/client/v1/sites/{SITE_B}/analytics/export",
            headers=_entetes(client_http),
        )
        assert reponse.status_code == 404, reponse.text
        assert reponse.json()["detail"] == "Site non trouvé"


# ============================================================
# Mission 1 — abonnement Jeko : /subscribe + webhook signé
# ============================================================


class TestAbonnementJeko:
    def test_subscribe_sans_cles_repond_non_configure_et_enregistre_l_intention(
        self, client_http, donnees
    ):
        reponse = client_http.post(
            "/api/client/v1/subscribe", headers=_entetes(client_http),
            json={"plan": "premium"},
        )
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["statut"] == "non_configure"
        assert "JEKO_API_URL" in corps["raison"]
        ligne = donnees.query(Abonnement).filter(
            Abonnement.id == corps["abonnement_id"]).first()
        assert ligne is not None
        assert ligne.statut == "intention"
        assert ligne.plan == "premium"
        assert ligne.user_id is not None

    def test_subscribe_plan_free_refuse_explicitement(self, client_http):
        reponse = client_http.post(
            "/api/client/v1/subscribe", headers=_entetes(client_http),
            json={"plan": "free"},
        )
        assert reponse.status_code == 400
        assert "gratuit" in reponse.json()["detail"]

    def test_subscribe_plan_inconnu_400(self, client_http):
        reponse = client_http.post(
            "/api/client/v1/subscribe", headers=_entetes(client_http),
            json={"plan": "illimité"},
        )
        assert reponse.status_code == 400
        assert "premium" in reponse.json()["detail"]

    def test_webhook_jeko_sans_secret_400(self, client_http):
        reponse = client_http.post(
            "/api/webhooks/jeko", json={"reference": "ref-1", "statut": "actif"}
        )
        assert reponse.status_code == 400, reponse.text
        assert "JEKO_WEBHOOK_SECRET" in reponse.json()["detail"]

    def test_webhook_jeko_non_signe_400(self, client_http, monkeypatch):
        monkeypatch.setenv("JEKO_WEBHOOK_SECRET", "secret-tests-1")
        reponse = client_http.post(
            "/api/webhooks/jeko", json={"reference": "ref-1", "statut": "actif"}
        )
        assert reponse.status_code == 400
        assert reponse.json()["detail"] == "signature webhook invalide"

    def test_webhook_jeko_signature_invalide_400(self, client_http, monkeypatch):
        monkeypatch.setenv("JEKO_WEBHOOK_SECRET", "secret-tests-1")
        reponse = client_http.post(
            "/api/webhooks/jeko",
            content=json.dumps({"reference": "ref-1", "statut": "actif"}).encode(),
            headers={"X-Jeko-Signature": "sha256=" + "0" * 64},
        )
        assert reponse.status_code == 400

    def test_webhook_jeko_statut_inconnu_422(self, client_http, monkeypatch):
        monkeypatch.setenv("JEKO_WEBHOOK_SECRET", "secret-tests-1")
        corps = json.dumps({"reference": "ref-1", "statut": "mystere"}).encode()
        reponse = client_http.post(
            "/api/webhooks/jeko", content=corps,
            headers={"X-Jeko-Signature": _signe("secret-tests-1", corps)},
        )
        assert reponse.status_code == 422

    def test_webhook_jeko_signe_active_abonnement_et_eleve_le_plan(
        self, client_http, donnees, monkeypatch
    ):
        monkeypatch.setenv("JEKO_WEBHOOK_SECRET", "secret-tests-1")
        proprio = donnees.query(User).filter(
            User.email == "proprio@fondations-tests.fr").first()
        abonnement = Abonnement(
            user_id=proprio.id, plan="premium", statut="en_attente",
            fournisseur="jeko", reference_fournisseur="ref-jeko-77",
        )
        donnees.add(abonnement)
        donnees.commit()

        corps = json.dumps({"reference": "ref-jeko-77", "statut": "actif"}).encode()
        reponse = client_http.post(
            "/api/webhooks/jeko", content=corps,
            headers={"X-Jeko-Signature": "sha256=" + _signe("secret-tests-1", corps)},
        )
        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["ok"] is True

        donnees.refresh(abonnement)
        assert abonnement.statut == "actif"
        donnees.refresh(proprio)
        # SEUL endroit où un plan s'élève : le webhook signé.
        assert proprio.plan == "premium"

    def test_webhook_jeko_reference_inconnue_tracée_et_200(
        self, client_http, monkeypatch
    ):
        monkeypatch.setenv("JEKO_WEBHOOK_SECRET", "secret-tests-1")
        corps = json.dumps({"reference": "inconnu-42", "statut": "actif"}).encode()
        reponse = client_http.post(
            "/api/webhooks/jeko", content=corps,
            headers={"X-Jeko-Signature": _signe("secret-tests-1", corps)},
        )
        assert reponse.status_code == 200
        assert reponse.json()["ok"] is False
        assert "inconnue" in reponse.json()["raison"]

    def test_webhook_jeko_annule_et_ne_descend_pas_le_plan_lui_meme(
        self, client_http, donnees, monkeypatch
    ):
        """L'annulation met le statut de l'abonnement à jour ; la politique de
        rétention/churn n'est pas décidée (EXTENSIBILITE.md) : le plan du
        compte n'est PAS modifié par l'annulation."""
        monkeypatch.setenv("JEKO_WEBHOOK_SECRET", "secret-tests-1")
        proprio = donnees.query(User).filter(
            User.email == "proprio@fondations-tests.fr").first()
        proprio.plan = "premium"
        abonnement = Abonnement(
            user_id=proprio.id, plan="premium", statut="actif",
            fournisseur="jeko", reference_fournisseur="ref-jeko-88",
        )
        donnees.add(abonnement)
        donnees.commit()

        corps = json.dumps({"reference": "ref-jeko-88", "statut": "annule"}).encode()
        reponse = client_http.post(
            "/api/webhooks/jeko", content=corps,
            headers={"X-Jeko-Signature": "sha256=" + _signe("secret-tests-1", corps)},
        )
        assert reponse.status_code == 200
        donnees.refresh(abonnement)
        assert abonnement.statut == "annule"
        donnees.refresh(proprio)
        assert proprio.plan == "premium"  # décision de churn non tranchée


# ============================================================
# Mission 2 — tracking applicatif
# ============================================================


def _batch(evenements, installation=INSTALLATION):
    return {"installation_id": installation, "evenements": evenements}


def _event(type_evt, **surcharge):
    evenement = {
        "event_id": str(uuid.uuid4()),
        "type": type_evt,
        "date_evenement": "2026-09-19T10:30:00",
    }
    evenement.update(surcharge)
    return evenement


class TestTracking:
    def test_batch_public_accepte_sans_authentification(self, client_http, donnees):
        reponse = client_http.post(
            "/api/client/v1/analytics/event",
            json=_batch([_event("install"), _event("app_open")]),
        )
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["recus"] == 2
        assert corps["acceptes"] == 2
        assert corps["doublons_ignores"] == 0
        lignes = donnees.query(AppAnalytics).all()
        assert len(lignes) == 2
        assert all(l.user_id is None for l in lignes)  # public : aucun compte
        assert all(l.installation_id == INSTALLATION for l in lignes)

    def test_dedup_le_rejeu_du_batch_est_ignore_silencieusement(
        self, client_http, donnees
    ):
        batch = _batch([_event("install"), _event("app_open"),
                        _event("screen_view", metadata={"ecran": "accueil"})])
        premiere = client_http.post("/api/client/v1/analytics/event", json=batch)
        assert premiere.status_code == 200
        seconde = client_http.post("/api/client/v1/analytics/event", json=batch)
        assert seconde.status_code == 200, seconde.text
        corps = seconde.json()
        assert corps["acceptes"] == 0
        assert corps["doublons_ignores"] == 3
        assert donnees.query(AppAnalytics).count() == 3  # rien de plus

    def test_batch_partiellement_dedoublonne(self, client_http, donnees):
        ancien = _event("app_open")
        client_http.post("/api/client/v1/analytics/event", json=_batch([ancien]))
        reponse = client_http.post(
            "/api/client/v1/analytics/event",
            json=_batch([ancien, _event("app_open")]),
        )
        corps = reponse.json()
        assert corps["acceptes"] == 1
        assert corps["doublons_ignores"] == 1

    def test_envoi_authentifie_enrichit_user_et_site(self, client_http, donnees):
        reponse = client_http.post(
            "/api/client/v1/analytics/event",
            headers=_entetes(client_http),
            json=_batch([_event("app_open")]),  # PAS de site_id fourni
        )
        assert reponse.status_code == 200
        ligne = donnees.query(AppAnalytics).first()
        proprio = donnees.query(User).filter(
            User.email == "proprio@fondations-tests.fr").first()
        assert ligne.user_id == proprio.id
        assert ligne.site_id == SITE_A  # déduit du compte

    def test_type_inconnu_422_avec_la_liste(self, client_http):
        reponse = client_http.post(
            "/api/client/v1/analytics/event",
            json=_batch([_event("evenement_fantome")]),
        )
        assert reponse.status_code == 422
        assert "install" in reponse.json()["detail"]

    def test_metadata_bornees_422(self, client_http):
        reponse = client_http.post(
            "/api/client/v1/analytics/event",
            json=_batch([_event("screen_view", metadata={"blob": "x" * 5000})]),
        )
        assert reponse.status_code == 422
        assert "4 Ko" in reponse.json()["detail"]

    def test_batch_vide_422(self, client_http):
        reponse = client_http.post(
            "/api/client/v1/analytics/event", json=_batch([])
        )
        assert reponse.status_code == 422

    def test_agregats_sont_scopes_au_site_du_compte(self, client_http, donnees):
        # Installation A : 1 install + 2 app_open + 3 screen_view accueil,
        # 1 session_start — envoyée AUTHENTIFIÉE (site A déduit).
        client_http.post(
            "/api/client/v1/analytics/event", headers=_entetes(client_http),
            json=_batch([
                _event("install"), _event("app_open"), _event("app_open"),
                _event("session_start"),
                _event("screen_view", metadata={"ecran": "accueil"}),
                _event("screen_view", metadata={"ecran": "accueil"}),
                _event("screen_view", metadata={"ecran": "conversations"}),
            ]),
        )
        # Installation B : événements du site B (envoyés PUBLICS avec
        # site_id explicite) — NE DOIVENT PAS fuir dans les agrégats de A.
        client_http.post(
            "/api/client/v1/analytics/event",
            json=_batch([
                {**_event("install"), "site_id": SITE_B},
                {**_event("app_open"), "site_id": SITE_B},
                {**_event("screen_view", metadata={"ecran": "secret-b"}),
                 "site_id": SITE_B},
            ], installation="install-site-b"),
        )
        reponse = client_http.get(
            "/api/client/v1/analytics/app?period_days=30",
            headers=_entetes(client_http),
        )
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["site_id"] == SITE_A
        assert corps["installations"]["total"] == 1  # B n'existe pas ici
        assert corps["taux_ouverture"] == 1.0
        assert corps["sessions_moyennes_par_installation"] == 1.0
        ecrans = {e["ecran"] for e in corps["ecrans_plus_vus"]}
        assert "secret-b" not in ecrans
        assert {"accueil", "conversations"} <= ecrans
        assert corps["evenements_par_type"]["install"] == 1

    def test_site_etranger_404_pas_403(self, client_http):
        reponse = client_http.get(
            f"/api/client/v1/analytics/app?site_id={SITE_B}",
            headers=_entetes(client_http),
        )
        assert reponse.status_code == 404  # contrat d'isolation

    def test_admin_sans_site_id_400(self, client_http):
        reponse = client_http.get(
            "/api/client/v1/analytics/app",
            headers=_entetes(client_http, "admin@fondations-tests.fr"),
        )
        assert reponse.status_code == 400
        assert "site_id" in reponse.json()["detail"]

    def test_admin_lit_le_site_demande(self, client_http, donnees):
        client_http.post(
            "/api/client/v1/analytics/event",
            json={**_batch([_event("install")]),
                  "evenements": [{**_event("install"), "site_id": SITE_B}]},
        )
        reponse = client_http.get(
            f"/api/client/v1/analytics/app?site_id={SITE_B}",
            headers=_entetes(client_http, "admin@fondations-tests.fr"),
        )
        assert reponse.status_code == 200
        assert reponse.json()["installations"]["total"] == 1


# ============================================================
# Mission 3 — WhatsApp : inactif par défaut, templates, webhook
# ============================================================


class TestWhatsApp:
    def test_canal_desactive_par_defaut_sans_appel_reseau(
        self, client_http, monkeypatch
    ):
        # Clés PRÉSENTES mais flag absent : l'état reste « désactivé ».
        monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "jeton-tests")
        monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123456789")

        def _interdit(*args, **kwargs):  # tout appel réseau ÉCHOUE au test
            raise AssertionError("appel réseau interdit : canal désactivé")

        monkeypatch.setattr("requests.post", _interdit)

        etat = notifications.etat_canal("whatsapp")
        assert etat.configure is False
        assert "désactivé" in etat.raison.lower()
        assert "WHATSAPP_ENABLED" in etat.raison

        resultat = notifications.envoyer("whatsapp", "+22507000000", "sujet", "message")
        assert resultat.succes is False
        assert resultat.statut == "non_configure"
        assert "désactivé" in resultat.erreur.lower()

    def test_active_sans_cles_etat_nomme_les_variables(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_ENABLED", "true")
        etat = notifications.etat_canal("whatsapp")
        assert etat.configure is False
        assert "WHATSAPP_ACCESS_TOKEN" in etat.raison

    def test_active_avec_cles_envoi_texte(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_ENABLED", "true")
        monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "jeton-tests")
        monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123456789")
        monkeypatch.setenv("WHATSAPP_NOTIF_DESTINATAIRE", "+22507000000")
        capturé = {}

        def _faux_post(url, **kwargs):
            capturé["url"] = url
            capturé["charge"] = json.loads(kwargs["data"])
            class _R:
                status_code = 200
                def json(self):
                    return {"messages": [{"id": "wamid-1"}]}
            return _R()

        monkeypatch.setattr("requests.post", _faux_post)
        resultat = notifications.envoyer(
            "whatsapp", "", "Nouveau lead", "Un visiteur a laissé ses coordonnées."
        )
        assert resultat.succes is True
        assert resultat.statut == "envoye"
        assert resultat.identifiant_fournisseur == "wamid-1"
        assert capturé["charge"]["to"] == "+22507000000"  # défaut NOTIF_DEST
        assert capturé["charge"]["type"] == "text"

    def test_template_nouveau_lead_produit_le_payload_meta(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_ENABLED", "true")
        monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "jeton-tests")
        monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123456789")
        capturé = {}

        def _faux_post(url, **kwargs):
            capturé["charge"] = json.loads(kwargs["data"])
            class _R:
                status_code = 200
                def json(self):
                    return {"messages": [{"id": "wamid-2"}]}
            return _R()

        monkeypatch.setattr("requests.post", _faux_post)
        template = notifications.template_whatsapp(
            "nouveau_lead", ["Fatou", "Bistrot Fondations", "réservation groupe"]
        )
        assert template["nom"] == "mia_nouveau_lead"
        resultat = notifications.envoyer(
            "whatsapp", "+22507000000", "", "", template=template
        )
        assert resultat.statut == "envoye"
        charge = capturé["charge"]
        assert charge["type"] == "template"
        assert charge["template"]["name"] == "mia_nouveau_lead"
        assert charge["template"]["language"]["code"] == "fr"
        parametres = charge["template"]["components"][0]["parameters"]
        assert [p["text"] for p in parametres] == [
            "Fatou", "Bistrot Fondations", "réservation groupe"
        ]

    def test_templates_structures_connus(self):
        assert {"nouveau_lead", "escalade"} <= set(notifications.TEMPLATES_WHATSAPP)
        with pytest.raises(ValueError):
            notifications.template_whatsapp("inconnu", [])

    def test_webhook_get_verification_hub_challenge(self, client_http, monkeypatch):
        monkeypatch.setenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "jeton-verif-tests")
        reponse = client_http.get(
            "/api/webhooks/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": "jeton-verif-tests",
                    "hub.challenge": "CHALLENGE-42"},
        )
        assert reponse.status_code == 200
        assert reponse.text == "CHALLENGE-42"
        # jeton incorrect → refus
        reprise = client_http.get(
            "/api/webhooks/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": "autre",
                    "hub.challenge": "CHALLENGE-42"},
        )
        assert reprise.status_code == 403

    def test_webhook_post_statuts_signe_et_trace(self, client_http, donnees,
                                                 monkeypatch):
        monkeypatch.setenv("WHATSAPP_APP_SECRET", "app-secret-tests")
        payload = {
            "entry": [{"changes": [{"value": {
                "contacts": [{"wa_id": "22507000000"}],
                "statuses": [{"id": "wamid-9", "status": "delivered"}],
            }}]}],
        }
        corps = json.dumps(payload).encode()
        reponse = client_http.post(
            "/api/webhooks/whatsapp", content=corps,
            headers={"X-Hub-Signature-256": "sha256=" + _signe("app-secret-tests", corps)},
        )
        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["statuts_recus"] == 1
        trace = donnees.query(ChatbotNotificationLog).filter(
            ChatbotNotificationLog.identifiant_fournisseur == "wamid-9").first()
        assert trace is not None
        assert trace.canal == "whatsapp"
        assert trace.succes is True
        assert "delivered" in trace.sujet

    def test_webhook_post_signature_invalide_403(self, client_http, donnees,
                                                  monkeypatch):
        monkeypatch.setenv("WHATSAPP_APP_SECRET", "app-secret-tests")
        reponse = client_http.post(
            "/api/webhooks/whatsapp",
            content=json.dumps({"entry": []}).encode(),
            headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
        )
        assert reponse.status_code == 403
        assert donnees.query(ChatbotNotificationLog).count() == 0

    def test_webhook_post_sans_secret_accepte_et_trace(self, client_http, donnees):
        """Sans WHATSAPP_APP_SECRET : la réception est acceptée ET tracée —
        le diagnostic reste possible après coup."""
        reponse = client_http.post(
            "/api/webhooks/whatsapp",
            content=json.dumps({"entry": [{"changes": [{"value": {
                "statuses": [{"id": "wamid-10", "status": "read"}]}}]}]}).encode(),
        )
        assert reponse.status_code == 200
        trace = donnees.query(ChatbotNotificationLog).filter(
            ChatbotNotificationLog.identifiant_fournisseur == "wamid-10").first()
        assert trace is not None and trace.succes is True


# ============================================================
# Mission 4 — RCS : inactif par défaut, structure déclarative
# ============================================================


class TestRCS:
    def test_canal_present_et_desactive_par_defaut(self, monkeypatch):
        assert "rcs" in notifications.CANAUX

        def _interdit(*args, **kwargs):
            raise AssertionError("appel réseau interdit : canal désactivé")

        monkeypatch.setattr("requests.post", _interdit)
        etat = notifications.etat_canal("rcs")
        assert etat.configure is False
        assert "désactivé" in etat.raison.lower()
        assert "RCS_ENABLED" in etat.raison

        resultat = notifications.envoyer("rcs", "+22507000000", "sujet", "message")
        assert resultat.statut == "non_configure"
        assert "désactivé" in resultat.erreur.lower()

    def test_active_sans_cles_nomme_les_variables(self, monkeypatch):
        monkeypatch.setenv("RCS_ENABLED", "true")
        etat = notifications.etat_canal("rcs")
        assert etat.configure is False
        for variable in ("RCS_AGENT_ID", "RCS_API_URL", "RCS_API_KEY"):
            assert variable in etat.raison

    def test_structure_texte_et_cartes_declarative(self, monkeypatch):
        monkeypatch.setenv("RCS_ENABLED", "true")
        monkeypatch.setenv("RCS_AGENT_ID", "agent-tests")
        monkeypatch.setenv("RCS_API_URL", "https://rcs.example-tests.fr/envoyer")
        monkeypatch.setenv("RCS_API_KEY", "cle-tests")
        capturé = {}

        def _faux_post(url, **kwargs):
            capturé["url"] = url
            capturé["charge"] = json.loads(kwargs["data"])
            class _R:
                status_code = 200
                def json(self):
                    return {"message_id": "rcs-1"}
            return _R()

        monkeypatch.setattr("requests.post", _faux_post)
        cartes = [{
            "titre": "Nouveau lead",
            "sous_titre": "Bistrot Fondations",
            "suggestions": [{"type": "reponse", "texte": "Ouvrir", "valeur": "ouvrir"}],
        }]
        resultat = notifications.envoyer(
            "rcs", "+22507000000", "Nouveau lead", "Un visiteur veut réserver.",
            cartes=cartes,
        )
        assert resultat.statut == "envoye"
        charge = capturé["charge"]
        # INTERFACE ABSTRAITE : texte + cartes en structure JSON déclarée
        assert charge["agent_id"] == "agent-tests"
        assert "réserver" in charge["message"]["texte"]
        assert charge["message"]["cartes"][0]["titre"] == "Nouveau lead"
        assert charge["message"]["cartes"][0]["suggestions"][0]["type"] == "reponse"

    def test_fallback_sms_declaratif_jamais_une_reussite(self, monkeypatch):
        monkeypatch.setenv("RCS_ENABLED", "true")
        monkeypatch.setenv("RCS_AGENT_ID", "agent-tests")
        monkeypatch.setenv("RCS_API_URL", "https://rcs.example-tests.fr/envoyer")
        monkeypatch.setenv("RCS_API_KEY", "cle-tests")
        monkeypatch.setenv("RCS_FALLBACK_SMS", "true")

        def _faux_post(url, **kwargs):
            class _R:
                status_code = 500
                def json(self):
                    return {"error": "boom"}
            return _R()

        monkeypatch.setattr("requests.post", _faux_post)
        resultat = notifications.envoyer("rcs", "+22507000000", "s", "m")
        assert resultat.statut == "echec"          # PAS "envoye"
        assert resultat.succes is False
        assert "DÉCLARÉ" in resultat.erreur
        assert "pas implémentée" in resultat.erreur


# ============================================================
# Migration au boot — la colonne plan répare une table existante
# ============================================================


class TestMigrationPlan:
    def test_la_migration_ajoute_plan_a_une_table_existante(self, base):
        """LE PIÈGE DU PROJET : create_all ne modifie JAMAIS une table
        existante. Une table `users` créée AVANT les fondations n'a pas de
        colonne plan : la migration au boot doit l'ajouter, et un second
        passage ne rien faire (idempotence)."""
        from sqlalchemy import inspect as _inspect, text as _text

        moteur = base.get_bind()
        with moteur.connect() as c:
            c.execute(_text("DROP TABLE IF EXISTS users"))
            c.execute(_text(
                "CREATE TABLE users ("
                " id INTEGER PRIMARY KEY,"
                " email VARCHAR(255),"
                " password_hash VARCHAR(255),"
                " role VARCHAR(20),"
                " is_active BOOLEAN,"
                " last_login TIMESTAMP,"
                " created_at TIMESTAMP)"
            ))
            c.commit()

        from backend.core import migrations_boot
        original = migrations_boot.engine
        migrations_boot.engine = moteur
        try:
            rapport = migrations_boot.appliquer_migrations()
            colonnes = {c2["name"] for c2 in _inspect(moteur).get_columns("users")}
            assert "plan" in colonnes, "colonne plan manquante après migration"
            assert "users.plan" in rapport["colonnes_ajoutees"]
            assert "idx_users_plan" in rapport["index_crees"]
            # Idempotence : un second passage n'ajoute RIEN.
            rapport2 = migrations_boot.appliquer_migrations()
            assert rapport2["colonnes_ajoutees"] == []
        finally:
            migrations_boot.engine = original

    def test_les_tables_nouvelles_sont_declarees_pour_create_all(self):
        noms = set(Base.metadata.tables)
        assert {"fonctionnalites", "abonnements", "app_analytics"} <= noms

    def test_les_tables_nouvelles_se_creent_reellement(self, base):
        noms = set(inspect(base.get_bind()).get_table_names())
        assert {"fonctionnalites", "abonnements", "app_analytics"} <= noms

"""
Tests des routes client Entraînement (F) et Secteur (G) — lot Phase 4 bis.

Le parcours testé est le parcours réel de première connexion d'un
propriétaire : provisionnement admin → changement de mot de passe forcé →
2FA (client_admin) → routes du site. L'isolation multi-tenant (404, jamais
403 distinctif) est vérifiée aussi bien que la fonctionnalité.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.api.app import app  # noqa: E402
from backend.api.app import get_db  # noqa: E402
from backend.core.database import Base  # noqa: E402
from backend.core.models import User  # noqa: E402
from backend.core.auth import get_password_hash  # noqa: E402
from backend.chatbot.models import ChatbotSite  # noqa: E402

SITE_A = "site_restaurant_efg"
SITE_B = "site_autre_efg"
MDP_ADMIN = "admin-mot-de-passe-test-1"
NOUVEAU_MDP = "nouveau-mdp-9"


@pytest.fixture(autouse=True)
def sac_rate_limit_vierge():
    """Vide le sac in-memory du middleware entre les tests (isolement) —
    le parcours provisionnement+2FA enchaîne plusieurs logins par IP de test."""
    from backend.api import app as app_module

    app_module._rate_bucket.clear()
    yield
    app_module._rate_bucket.clear()


@pytest.fixture
def base():
    moteur = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=moteur)
    Fabrique = sessionmaker(bind=moteur)
    session = Fabrique()
    session.add(
        ChatbotSite(
            site_id=SITE_A,
            site_name="Le Bistrot du Coin",
            site_url="https://bistrot.example",
            sector="restauration",
            is_active=True,
        )
    )
    session.add(
        ChatbotSite(
            site_id=SITE_B, site_name="Autre site", site_url="https://autre.example", is_active=True
        )
    )
    session.add(
        User(
            email="admin@eperformance-tests.fr",
            password_hash=get_password_hash(MDP_ADMIN),
            role="admin",
            is_active=True,
        )
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        moteur.dispose()


@pytest.fixture
def client_http(base):
    app.dependency_overrides[get_db] = lambda: base
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _entetes(jeton):
    return {"Authorization": f"Bearer {jeton['access_token']}"}


def _admin(client_http):
    r = client_http.post(
        "/api/auth/login",
        data={"username": "admin@eperformance-tests.fr", "password": MDP_ADMIN},
    )
    assert r.status_code == 200, r.text
    return _entetes(r.json())


def _creer_proprietaire(client_http, email, role_client="client_admin", site_id=SITE_A):
    """Provisionnement + changement de mot de passe forcé (parcours réel)."""
    r = client_http.post(
        "/api/chatbot/admin/clients",
        headers=_admin(client_http),
        json={"email": email, "nom": "Propriétaire de test", "site_id": site_id,
              "role_client": role_client},
    )
    assert r.status_code == 201, r.text
    mdp_temporaire = r.json()["mot_de_passe_temporaire"]
    premier = client_http.post(
        "/api/auth/login", data={"username": email, "password": mdp_temporaire}
    ).json()
    changement = client_http.post(
        "/api/client/v1/password", headers=_entetes(premier),
        json={"ancien_mot_de_passe": mdp_temporaire, "nouveau_mot_de_passe": NOUVEAU_MDP},
    )
    assert changement.status_code == 200, changement.text
    return _jeton(client_http, email, NOUVEAU_MDP), mdp_temporaire


def _jeton(client_http, email, mot_de_passe, **form):
    r = client_http.post(
        "/api/auth/login", data={"username": email, "password": mot_de_passe, **form}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _admin_2fa(client_http, email):
    """client_admin avec onboarding complet (mdp changé + 2FA activée)."""
    jeton, _ = _creer_proprietaire(client_http, email)
    entetes = _entetes(jeton)
    secret = client_http.post("/api/client/v1/2fa/setup", headers=entetes).json()["secret"]
    activation = client_http.post(
        "/api/client/v1/2fa/activate", headers=entetes,
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert activation.status_code == 200, activation.text
    return _jeton(client_http, email, NOUVEAU_MDP, totp_code=pyotp.TOTP(secret).now())


# ============================================================
# F — Entraînement côté client
# ============================================================


class TestConnaissancesClient:
    def test_liste_vide_pour_un_site_sans_connaissances(self, client_http):
        jeton = _admin_2fa(client_http, "proprio@client-tests.fr")
        r = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/connaissances", headers=_entetes(jeton)
        )
        assert r.status_code == 200
        assert r.json() == {"site_id": SITE_A, "total": 0, "items": []}

    def test_client_admin_cree_une_qr_et_la_relit(self, client_http, base):
        from backend.core.audit import AuditLog

        jeton = _admin_2fa(client_http, "proprio@client-tests.fr")
        r = client_http.post(
            f"/api/client/v1/sites/{SITE_A}/connaissances", headers=_entetes(jeton),
            json={"type": "qr", "question": "Livrez-vous à Abidjan ?",
                  "reponse": "Oui, sous 24 h."},
        )
        assert r.status_code == 201, r.text
        item = r.json()
        assert item["type"] == "qr" and item["actif"] is True

        relecture = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/connaissances", headers=_entetes(jeton)
        ).json()
        assert relecture["total"] == 1 and relecture["items"][0]["id"] == item["id"]

        lignes = base.query(AuditLog).filter_by(action="creation_connaissance_client").all()
        assert len(lignes) == 1 and lignes[0].site_id == SITE_A

    def test_l_effet_est_immediat_sur_le_moteur(self, client_http):
        from backend.chatbot import connaissances as moteur

        jeton = _admin_2fa(client_http, "proprio@client-tests.fr")
        client_http.post(
            f"/api/client/v1/sites/{SITE_A}/connaissances", headers=_entetes(jeton),
            json={"type": "qr", "question": "Quels sont vos horaires ?",
                  "reponse": "9h - 18h, du lundi au samedi."},
        )
        resultats = moteur.chercher(SITE_A, "vous êtes ouverts quels horaires ?")
        assert resultats and "18h" in resultats[0]["reponse"]

    def test_client_reader_ne_peut_pas_ecrire(self, client_http):
        jeton_reader, _ = _creer_proprietaire(
            client_http, "lecteur@client-tests.fr", role_client="client_reader"
        )
        r = client_http.post(
            f"/api/client/v1/sites/{SITE_A}/connaissances", headers=_entetes(jeton_reader),
            json={"type": "qr", "question": "Q", "reponse": "R"},
        )
        assert r.status_code == 403

    def test_reader_peut_lire(self, client_http):
        _admin_2fa(client_http, "proprio@client-tests.fr")
        jeton_reader, _ = _creer_proprietaire(
            client_http, "lecteur@client-tests.fr", role_client="client_reader"
        )
        r = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/connaissances", headers=_entetes(jeton_reader)
        )
        assert r.status_code == 200

    def test_qr_sans_reponse_et_texte_sans_contenu_sont_refuses(self, client_http):
        jeton = _admin_2fa(client_http, "proprio@client-tests.fr")
        assert client_http.post(
            f"/api/client/v1/sites/{SITE_A}/connaissances", headers=_entetes(jeton),
            json={"type": "qr", "question": "Q seulement"},
        ).status_code == 422
        assert client_http.post(
            f"/api/client/v1/sites/{SITE_A}/connaissances", headers=_entetes(jeton),
            json={"type": "texte"},
        ).status_code == 422

    def test_archivage_trace_et_hors_liste(self, client_http, base):
        from backend.core.audit import AuditLog

        jeton = _admin_2fa(client_http, "proprio@client-tests.fr")
        item = client_http.post(
            f"/api/client/v1/sites/{SITE_A}/connaissances", headers=_entetes(jeton),
            json={"type": "texte", "contenu": "Document interne du site."},
        ).json()
        r = client_http.delete(
            f"/api/client/v1/sites/{SITE_A}/connaissances/{item['id']}",
            headers=_entetes(jeton),
        )
        assert r.status_code == 200 and r.json()["actif"] is False
        assert client_http.get(
            f"/api/client/v1/sites/{SITE_A}/connaissances", headers=_entetes(jeton)
        ).json()["total"] == 0
        lignes = base.query(AuditLog).filter_by(action="archivage_connaissance_client").all()
        assert len(lignes) == 1

    def test_isolation_un_autre_site_est_un_404(self, client_http):
        jeton = _admin_2fa(client_http, "proprio@client-tests.fr")
        assert client_http.post(
            f"/api/client/v1/sites/{SITE_B}/connaissances", headers=_entetes(jeton),
            json={"type": "qr", "question": "Q", "reponse": "R"},
        ).status_code == 404
        assert client_http.get(
            f"/api/client/v1/sites/{SITE_B}/connaissances", headers=_entetes(jeton)
        ).status_code == 404

    def test_sans_compte_pas_d_acces(self, client_http):
        assert client_http.get(
            f"/api/client/v1/sites/{SITE_A}/connaissances"
        ).status_code in (401, 403)


# ============================================================
# G — Secteur côté client
# ============================================================


class TestSecteurClient:
    def test_lecture_secteur_null_et_12_disponibles(self, client_http, base):
        base.query(ChatbotSite).filter_by(site_id=SITE_A).update({"sector": None})
        base.commit()
        jeton = _admin_2fa(client_http, "proprio@client-tests.fr")
        r = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/secteur", headers=_entetes(jeton)
        )
        assert r.status_code == 200
        corps = r.json()
        assert corps["secteur"] is None and corps["bloc_instructions"] is None
        assert len(corps["secteurs_disponibles"]) == 12
        assert "blog" not in corps["secteurs_disponibles"]  # non client (19/09)

    def test_le_secteur_pose_produit_le_bloc_canonique(self, client_http):
        jeton = _admin_2fa(client_http, "proprio@client-tests.fr")
        r = client_http.put(
            f"/api/client/v1/sites/{SITE_A}/secteur", headers=_entetes(jeton),
            json={"secteur": "immobilier"},
        )
        assert r.status_code == 200, r.text
        bloc = r.json()["bloc_instructions"]
        assert bloc and "Immobilier" in bloc  # nom canonique du secteur
        # l'intention canonique du noyau (sectors.py), pas une invention
        assert "bénéficiaire" in bloc or "visite" in bloc or "estimation" in bloc

    def test_secteur_inconnu_400_avec_liste(self, client_http):
        jeton = _admin_2fa(client_http, "proprio@client-tests.fr")
        r = client_http.put(
            f"/api/client/v1/sites/{SITE_A}/secteur", headers=_entetes(jeton),
            json={"secteur": "astrologie"},
        )
        assert r.status_code == 400
        assert "Secteurs disponibles" in r.json()["detail"]

    def test_reader_ne_peut_pas_definir_le_secteur(self, client_http):
        jeton_reader, _ = _creer_proprietaire(
            client_http, "lecteur@client-tests.fr", role_client="client_reader"
        )
        assert client_http.put(
            f"/api/client/v1/sites/{SITE_A}/secteur", headers=_entetes(jeton_reader),
            json={"secteur": "vitrine"},
        ).status_code == 403

    def test_isolation_secteur_404(self, client_http):
        jeton, _ = _creer_proprietaire(client_http, "proprio@client-tests.fr")
        assert client_http.get(
            f"/api/client/v1/sites/{SITE_B}/secteur", headers=_entetes(jeton)
        ).status_code == 404

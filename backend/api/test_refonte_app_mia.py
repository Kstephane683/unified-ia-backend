#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests des chantiers B1-B3 — refonte app Mia (SaaS de gestion multi-tenant).

CE QUE CETTE SUITE PROUVE
-------------------------
B1 — Provisionnement : l'admin crée le compte propriétaire d'un site, le mot de
     passe temporaire sort UNE FOIS, le propriétaire se connecte, DOIT changer
     son mot de passe (routes refusées tant que ce n'est pas fait, 403 avec
     raison explicite), puis voit SES données. remember_me → jeton 30 jours.
B2 — Rôles scopés : hiérarchie admin > client_admin > client_operator >
     client_reader ; ISOLATION MULTI-TENANT (site A demande site B → 404, pas
     403) ; 2FA TOTP (setup/activate/disable, blocage login sans code, secret
     chiffré) ; journal d'audit écrit et lisible par l'admin.
B3 — API client v1 : chaque endpoint testé, y compris /orders (état explicite
     200, pas d'erreur) et le refus d'écriture du system_prompt.

MÉTHODE : la VRAIE application FastAPI (backend.api.app) avec `get_db`
redirigé vers une base SQLite en mémoire — on teste la vraie chaîne
login → JWT → get_current_user → dépendances de scope. Aucun réseau, aucune
base externe. Le middleware de rate limiting du vrai app est utilisé tel quel
(sac vidé entre les tests pour l'isolement).

Exécution :
    cd /home/ballo/OX6A/unified-ia-backend
    python3 -m pytest backend/api/test_refonte_app_mia.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

# Import NÉCESSAIRE pour que create_all connaisse TOUTES les tables (même
# raisonnement que le test 6.5 : la clé étrangère vers `users` doit être
# déclarée sur la même Base).
import backend.core.models  # noqa: E402,F401
import backend.core.audit  # noqa: E402,F401  (déclare audit_log)
from backend.chatbot.models import (  # noqa: E402
    ChatbotConversation,
    ChatbotLead,
    ChatbotMessage,
    ChatbotSite,
    PushSubscription,
)
from backend.core.database import Base, get_db  # noqa: E402
from backend.core.auth import get_password_hash  # noqa: E402
from backend.core.models import User  # noqa: E402

# Le VRAI app — importé une fois. Son init_db au niveau module est absorbé
# (try/except) : aucun appel vers une base réelle n'est exigé.
from backend.api import app as app_module  # noqa: E402
from backend.api.app import app  # noqa: E402

import pyotp  # tests 2FA uniquement — jamais importé par le code de prod au chargement

# ============================================================
# Fixtures
# ============================================================

MDP_ADMIN = "admin-mot-de-passe-test-1"
SITE_A = "site_restaurant_a"
SITE_B = "site_boulangerie_b"


@pytest.fixture(autouse=True)
def sac_rate_limit_vierge():
    """Vide le sac in-memory du middleware entre les tests (isolement)."""
    app_module._rate_bucket.clear()
    yield
    app_module._rate_bucket.clear()


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
    """Un monde minimal : 2 sites, un admin, des conversations de chaque côté."""
    site_a = ChatbotSite(
        site_id=SITE_A,
        site_name="Le Bistrot du Coin",
        site_url="https://bistrot.example",
        system_prompt="Tu es Mia, l'assistante du bistrot.",
        welcome_message="Bonjour !",
        sector="restauration",
        is_active=True,
    )
    site_b = ChatbotSite(
        site_id=SITE_B,
        site_name="Boulangerie Sanzot",
        site_url="https://sanzot.example",
        sector="vitrine",
        is_active=True,
    )
    base.add_all([site_a, site_b])

    base.add(
        User(
            email="admin@eperformance-tests.fr",
            password_hash=get_password_hash(MDP_ADMIN),
            role="admin",
            is_active=True,
        )
    )

    conv_a1 = ChatbotConversation(
        conversation_id="conv-a-1",
        site_id=SITE_A,
        status="active",
        visitor_name="Madame Michu",
        visitor_email="michu@exemple-tests.fr",
        lead_captured=False,
        message_count=2,
    )
    conv_a2 = ChatbotConversation(
        conversation_id="conv-a-2",
        site_id=SITE_A,
        status="escalated",
        visitor_name="Monsieur Seguin",
        lead_captured=True,
        message_count=1,
    )
    conv_b1 = ChatbotConversation(
        conversation_id="conv-b-1",
        site_id=SITE_B,
        status="active",
        visitor_name="Client d'ailleurs",
        message_count=1,
    )
    base.add_all([conv_a1, conv_a2, conv_b1])
    base.add_all([
        ChatbotMessage(
            conversation_id="conv-a-1", role="user", content="Vous êtes ouvert dimanche ?"
        ),
        ChatbotMessage(
            conversation_id="conv-a-1", role="assistant", content="Oui, de 9h à 14h."
        ),
        ChatbotMessage(
            conversation_id="conv-a-2", role="user",
            content="Je veux parler à un humain au sujet d'une réservation de groupe",
        ),
        ChatbotMessage(
            conversation_id="conv-b-1", role="user", content="Vos pains sont bios ?"
        ),
    ])
    base.add(
        ChatbotLead(
            conversation_id="conv-a-2",
            site_id=SITE_A,
            name="Monsieur Seguin",
            email="seguin@exemple-tests.fr",
            phone="+226 70 00 00 00",
            lead_type="hot",
            status="new",
        )
    )
    base.commit()

    base.add_all([
        User(
            email="proprio-a@client-tests.fr",
            password_hash=get_password_hash("ancien-mot-de-passe-1"),
            role="client",
            role_client="client_admin",
            site_id=SITE_A,
            nom="Propriétaire A",
            must_change_password=False,
            is_active=True,
        ),
        User(
            email="lecteur-a@client-tests.fr",
            password_hash=get_password_hash("ancien-mot-de-passe-2"),
            role="client",
            role_client="client_reader",
            site_id=SITE_A,
            nom="Lecteur A",
            must_change_password=False,
            is_active=True,
        ),
    ])
    base.commit()
    return base


@pytest.fixture
def client_http(donnees):
    """TestClient branché sur la base de test (get_db redirigé).

    SANS context manager : le lifespan (print + check_connection vers une
    base réelle) n'a rien à faire ici — les requêtes fonctionnent tel quel.
    """
    app.dependency_overrides[get_db] = lambda: donnees
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _jeton(client_http, email, mot_de_passe, **form):
    reponse = client_http.post(
        "/api/auth/login",
        data={"username": email, "password": mot_de_passe, **form},
    )
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


def _entetes(jeton):
    return {"Authorization": f"Bearer {jeton['access_token']}"}


def _admin(client_http):
    return _entetes(_jeton(client_http, "admin@eperformance-tests.fr", MDP_ADMIN))


NOUVEAU_MDP = "nouveau-mdp-9"


def _creer_proprietaire(client_http, email, role_client="client_admin", site_id=SITE_A):
    """Provisionne un compte propriétaire via la route B1 et TERMINE son
    changement de mot de passe (le parcours réel de livraison : le compte
    naît avec must_change_password=True, il est inutilisable avant). Renvoie
    (jeton opérationnel, mot de passe temporaire)."""
    reponse = client_http.post(
        "/api/chatbot/admin/clients",
        headers=_admin(client_http),
        json={"email": email, "nom": "Propriétaire de test", "site_id": site_id,
              "role_client": role_client},
    )
    assert reponse.status_code == 201, reponse.text
    corps = reponse.json()
    mdp_temporaire = corps["mot_de_passe_temporaire"]
    premier = _jeton(client_http, email, mdp_temporaire)
    changement = client_http.post(
        "/api/client/v1/password", headers=_entetes(premier),
        json={"ancien_mot_de_passe": mdp_temporaire,
              "nouveau_mot_de_passe": NOUVEAU_MDP},
    )
    assert changement.status_code == 200, changement.text
    return _jeton(client_http, email, NOUVEAU_MDP), mdp_temporaire


def _creer_admin_2fa(client_http, email, site_id=SITE_A):
    """Crée un client_admin AYANT terminé son onboarding complet : mot de passe
    temporaire changé (fait par _creer_proprietaire) + 2FA activée —
    obligatoire pour ce rôle. Renvoie le jeton prêt pour les routes du site.
    C'est le parcours réel de première connexion d'un propriétaire client_admin."""
    jeton, _ = _creer_proprietaire(client_http, email, site_id=site_id)
    entetes = _entetes(jeton)
    secret = client_http.post(
        "/api/client/v1/2fa/setup", headers=entetes
    ).json()["secret"]
    activation = client_http.post(
        "/api/client/v1/2fa/activate", headers=entetes,
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert activation.status_code == 200, activation.text
    # Preuve supplémentaire : sans le code, la reconnexion est refusée.
    sans_code = client_http.post(
        "/api/auth/login", data={"username": email, "password": NOUVEAU_MDP},
    )
    assert sans_code.status_code == 401
    assert sans_code.json()["detail"] == "2fa_requise"
    return _jeton(client_http, email, NOUVEAU_MDP,
                  totp_code=pyotp.TOTP(secret).now())


# ============================================================
# 0. Migrations et tables
# ============================================================


class TestSchema:
    def test_les_tables_nouvelles_sont_declarees_pour_create_all(self):
        noms = set(Base.metadata.tables)
        assert "audit_log" in noms
        assert "client_notifications" in noms

    def test_les_tables_nouvelles_se_creent_reellement(self, base):
        noms = set(inspect(base.get_bind()).get_table_names())
        assert "audit_log" in noms
        assert "client_notifications" in noms

    def test_la_migration_au_boot_repare_une_table_existante(self, base):
        """LE PIÈGE DU PROJET : create_all ne modifie JAMAIS une table
        existante. Une table `users` créée AVANT la refonte n'a ni site_id ni
        must_change_password : la migration au boot doit les ajouter, et un
        second passage ne rien faire (idempotence)."""
        from sqlalchemy import inspect as _inspect, text as _text

        moteur = base.get_bind()
        # 1. Une table users À L'ANCIENNE (sans les colonnes B1/B2).
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
            for attendue in ("nom", "site_id", "role_client",
                             "must_change_password", "totp_secret",
                             "totp_enabled"):
                assert attendue in colonnes, f"{attendue} manquant après migration"
            assert f"users.site_id" in rapport["colonnes_ajoutees"]

            # 2. Idempotence : un second passage n'ajoute RIEN.
            rapport2 = migrations_boot.appliquer_migrations()
            assert rapport2["colonnes_ajoutees"] == []
        finally:
            migrations_boot.engine = original

    def test_le_import_de_auth_n_importe_pas_pyotp(self):
        """Règle du projet : import paresseux d'une bibliothèque optionnelle."""
        import subprocess

        resultat = subprocess.run(
            [sys.executable, "-c",
             "import sys; import backend.core.auth; "
             "assert 'pyotp' not in sys.modules, 'pyotp importé au chargement !'; "
             "print('ok')"],
            cwd=str(RACINE), capture_output=True, text=True, timeout=60,
        )
        assert resultat.returncode == 0, resultat.stderr
        assert "ok" in resultat.stdout


# ============================================================
# B1 — Provisionnement des comptes propriétaires
# ============================================================


class TestProvisionnement:
    def test_l_admin_cree_le_compte_et_le_mdp_temporaire_sort_une_fois(
        self, client_http
    ):
        reponse = client_http.post(
            "/api/chatbot/admin/clients",
            headers=_admin(client_http),
            json={"email": "nouveau@client-tests.fr", "nom": "Nouveau proprio",
                  "site_id": SITE_A, "role_client": "client_admin"},
        )
        assert reponse.status_code == 201
        corps = reponse.json()
        assert corps["must_change_password"] is True
        assert corps["role_client"] == "client_admin"
        assert corps["site_id"] == SITE_A
        mot_de_passe = corps["mot_de_passe_temporaire"]
        # Robustesse du secret temporaire : 16+ caractères (token_urlsafe(12)+).
        assert len(mot_de_passe) >= 12

        compte = client_http.get(
            "/api/chatbot/admin/clients?site_id=" + SITE_A,
            headers=_admin(client_http),
        ).json()["clients"][0]
        assert compte["must_change_password"] is True
        # Le listing n'expose JAMAIS le mot de passe, même temporaire.
        assert "mot_de_passe" not in str(compte).lower() or \
            "mot_de_passe_temporaire" not in compte

    def test_le_provisionnement_est_trace_en_audit(self, client_http, donnees):
        from backend.core.audit import AuditLog

        client_http.post(
            "/api/chatbot/admin/clients",
            headers=_admin(client_http),
            json={"email": "audite@client-tests.fr", "nom": "Audité",
                  "site_id": SITE_A, "role_client": "client_operator"},
        )
        lignes = donnees.query(AuditLog).filter_by(action="creation_compte_client").all()
        assert len(lignes) == 1
        assert lignes[0].site_id == SITE_A
        str_details = str(lignes[0].details)
        assert "mot_de_passe" not in str_details

    def test_sans_le_role_admin_le_provisionnement_est_refuse(self, client_http):
        jeton, _ = _creer_proprietaire(client_http, "un-proprietaire@client-tests.fr")
        reponse = client_http.post(
            "/api/chatbot/admin/clients",
            headers=_entetes(jeton),
            json={"email": "autre@client-tests.fr", "nom": "Autre",
                  "site_id": SITE_A, "role_client": "client_admin"},
        )
        assert reponse.status_code == 403

    def test_site_inconnu_404_et_email_doublon_400(self, client_http):
        assert client_http.post(
            "/api/chatbot/admin/clients", headers=_admin(client_http),
            json={"email": "x@client-tests.fr", "nom": "X", "site_id": "inexistant"},
        ).status_code == 404
        _creer_proprietaire(client_http, "doublon@client-tests.fr")
        assert client_http.post(
            "/api/chatbot/admin/clients", headers=_admin(client_http),
            json={"email": "doublon@client-tests.fr", "nom": "Y", "site_id": SITE_A},
        ).status_code == 400

    def test_role_client_inconnu_422(self, client_http):
        reponse = client_http.post(
            "/api/chatbot/admin/clients", headers=_admin(client_http),
            json={"email": "z@client-tests.fr", "nom": "Z", "site_id": SITE_A,
                  "role_client": "superuser"},
        )
        assert reponse.status_code == 422

    def test_le_login_expose_must_change_password(self, client_http):
        brut = client_http.post(
            "/api/chatbot/admin/clients",
            headers=_admin(client_http),
            json={"email": "floride@client-tests.fr", "nom": "Floride",
                  "site_id": SITE_A, "role_client": "client_admin"},
        )
        assert brut.status_code == 201
        reponse = client_http.post(
            "/api/auth/login",
            data={"username": "floride@client-tests.fr",
                  "password": brut.json()["mot_de_passe_temporaire"]},
        )
        assert reponse.status_code == 200
        assert reponse.json()["must_change_password"] is True

    def test_routes_client_refusees_tant_que_le_mdp_n_est_pas_change(
        self, client_http
    ):
        """B1 : 403 avec raison explicite sur les routes client scopées."""
        brut = client_http.post(
            "/api/chatbot/admin/clients",
            headers=_admin(client_http),
            json={"email": "bloque@client-tests.fr", "nom": "Bloqué",
                  "site_id": SITE_A, "role_client": "client_operator"},
        )
        assert brut.status_code == 201
        jeton = _jeton(client_http, "bloque@client-tests.fr",
                       brut.json()["mot_de_passe_temporaire"])
        reponse = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/conversations", headers=_entetes(jeton)
        )
        assert reponse.status_code == 403
        assert "mot de passe" in reponse.json()["detail"].lower()

        # /me reste accessible (c'est elle qui pilote l'écran de changement).
        moi = client_http.get("/api/client/v1/me", headers=_entetes(jeton))
        assert moi.status_code == 200
        assert moi.json()["must_change_password"] is True

    def test_flux_complet_provisionnement_connexion_changement_acces(
        self, client_http
    ):
        """Test d'intégration B1 : admin crée → propriétaire se connecte →
        doit changer son mdp → voit SES données (avec l'étape 2FA du rôle
        client_admin). Ici le parcours est joué À LA MAIN, sans l'aide."""
        # Provisionnement brut : le compte naît bloqué.
        brut = client_http.post(
            "/api/chatbot/admin/clients",
            headers=_admin(client_http),
            json={"email": "parcours@client-tests.fr", "nom": "Parcours complet",
                  "site_id": SITE_A, "role_client": "client_admin"},
        )
        assert brut.status_code == 201
        mdp_temporaire = brut.json()["mot_de_passe_temporaire"]
        assert brut.json()["must_change_password"] is True

        # Première connexion : possible, mais les routes client refusent.
        jeton = _jeton(client_http, "parcours@client-tests.fr", mdp_temporaire)
        assert jeton["must_change_password"] is True
        refuse_route = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/conversations", headers=_entetes(jeton)
        )
        assert refuse_route.status_code == 403
        assert "mot de passe" in refuse_route.json()["detail"].lower()

        # Ancien mot de passe erroné → 400.
        refuse = client_http.post(
            "/api/client/v1/password",
            headers=_entetes(jeton),
            json={"ancien_mot_de_passe": "ce-n-est-pas-le-bon",
                  "nouveau_mot_de_passe": NOUVEAU_MDP},
        )
        assert refuse.status_code == 400

        # Changement correct.
        changement = client_http.post(
            "/api/client/v1/password",
            headers=_entetes(jeton),
            json={"ancien_mot_de_passe": mdp_temporaire,
                  "nouveau_mot_de_passe": NOUVEAU_MDP},
        )
        assert changement.status_code == 200
        assert changement.json()["must_change_password"] is False

        # Le mot de passe temporaire ne fonctionne PLUS.
        assert client_http.post(
            "/api/auth/login",
            data={"username": "parcours@client-tests.fr", "password": mdp_temporaire},
        ).status_code == 401

        # Le nouveau fonctionne ; l'accès aux données du site est ouvert
        # APRÈS la configuration 2FA (obligatoire pour client_admin — le
        # parcours de première connexion se termine là).
        jeton2 = _jeton(client_http, "parcours@client-tests.fr", NOUVEAU_MDP)
        assert jeton2["must_change_password"] is False
        bloque = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/conversations", headers=_entetes(jeton2)
        )
        assert bloque.status_code == 403
        assert "2FA" in bloque.json()["detail"]
        entetes2 = _entetes(jeton2)
        secret = client_http.post(
            "/api/client/v1/2fa/setup", headers=entetes2
        ).json()["secret"]
        assert client_http.post(
            "/api/client/v1/2fa/activate", headers=entetes2,
            json={"code": pyotp.TOTP(secret).now()},
        ).status_code == 200
        jeton3 = _jeton(client_http, "parcours@client-tests.fr", NOUVEAU_MDP,
                        totp_code=pyotp.TOTP(secret).now())
        conversations = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/conversations", headers=_entetes(jeton3)
        )
        assert conversations.status_code == 200
        assert conversations.json()["total"] == 2

    def test_remember_me_donne_un_jeton_de_30_jours(self, client_http):
        corps = _jeton(client_http, "admin@eperformance-tests.fr", MDP_ADMIN,
                       remember_me="true")
        assert corps["expires_in"] == 30 * 86400
        corps_court = _jeton(client_http, "admin@eperformance-tests.fr", MDP_ADMIN)
        assert corps_court["expires_in"] != 30 * 86400


# ============================================================
# B2 — Rôles scopés, isolation multi-tenant, 2FA, audit
# ============================================================


class TestIsolationMultiTenant:
    """LE test non négociable : un propriétaire ne voit PAS les autres sites."""

    def test_le_proprietaire_du_site_a_demande_le_site_b_404(self, client_http):
        jeton, _ = _creer_proprietaire(client_http, "tenant-a@client-tests.fr",
                                       role_client="client_operator",
                                       site_id=SITE_A)
        reponse = client_http.get(
            f"/api/client/v1/sites/{SITE_B}/conversations", headers=_entetes(jeton)
        )
        # 404 (et non 403) : ne pas révéler l'existence des autres sites.
        assert reponse.status_code == 404
        assert reponse.json()["detail"] == "Site non trouvé"

    def test_client_admin_sans_2fa_demande_le_site_b_404_aussi(self, client_http):
        """L'ISOLATION PRIME sur la porte 2FA : la vérification de propriété
        passe AVANT, donc même un client_admin en attente de configuration 2FA
        reçoit 404 — jamais un indice sur les autres sites."""
        jeton, _ = _creer_proprietaire(client_http, "tenant-a5@client-tests.fr",
                                       site_id=SITE_A)
        reponse = client_http.get(
            f"/api/client/v1/sites/{SITE_B}/conversations", headers=_entetes(jeton)
        )
        assert reponse.status_code == 404
        assert reponse.json()["detail"] == "Site non trouvé"

    def test_les_conversations_du_site_b_n_apparaissent_pas_dans_le_site_a(
        self, client_http
    ):
        jeton, _ = _creer_proprietaire(client_http, "tenant-a2@client-tests.fr",
                                       role_client="client_operator")
        corps = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/conversations",
            headers=_entetes(jeton),
        ).json()
        identifiants = {c["conversation_id"] for c in corps["conversations"]}
        assert identifiants == {"conv-a-1", "conv-a-2"}

    def test_une_conversation_d_un_autre_site_est_introuvable_meme_par_id(
        self, client_http
    ):
        jeton, _ = _creer_proprietaire(client_http, "tenant-a3@client-tests.fr",
                                       role_client="client_operator")
        reponse = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/conversations/conv-b-1",
            headers=_entetes(jeton),
        )
        assert reponse.status_code == 404

        # Idem pour le RGPD : ni export ni suppression d'un autre site.
        assert client_http.get(
            f"/api/client/v1/sites/{SITE_A}/rgpd/conversations/conv-b-1/export",
            headers=_entetes(jeton),
        ).status_code == 404
        # La suppression exige client_admin : l'appel est rejoué avec un
        # client_admin de SITE_A (rôle suffisant) pour prouver que la 404
        # vient de l'ISOLATION et non d'un refus de rôle — et le site B lui-
        # même est introuvable, peu importe le rôle.
        admin = _entetes(_creer_admin_2fa(client_http, "tenant-a6@client-tests.fr"))
        assert client_http.delete(
            f"/api/client/v1/sites/{SITE_A}/rgpd/conversations/conv-b-1",
            headers=admin,
        ).status_code == 404
        assert client_http.delete(
            f"/api/client/v1/sites/{SITE_B}/rgpd/conversations/conv-b-1",
            headers=admin,
        ).status_code == 404
        assert client_http.delete(
            f"/api/client/v1/sites/{SITE_B}/rgpd/conversations/site-inexistant",
            headers=admin,
        ).status_code == 404

    def test_les_leads_du_site_b_ne_fuient_pas(self, client_http):
        jeton, _ = _creer_proprietaire(client_http, "tenant-a4@client-tests.fr",
                                       role_client="client_operator")
        corps = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/leads", headers=_entetes(jeton)
        ).json()
        # Le lead de conv-a-2 oui, celui d'un site B non (aucun ici).
        assert corps["total"] == 1
        assert all(l["conversation_id"].startswith("conv-a") for l in corps["leads"])

    def test_l_admin_eperformance_passe_partout(self, client_http):
        entetes = _admin(client_http)
        for site in (SITE_A, SITE_B):
            assert client_http.get(
                f"/api/client/v1/sites/{site}/conversations", headers=entetes
            ).status_code == 200

    def test_un_compte_sans_role_client_est_refuse(self, client_http, donnees):
        """Un compte 'client' provisioné nulle part ne doit rien voir."""
        donnees.add(User(
            email="vieux-compte@client-tests.fr",
            password_hash=get_password_hash("ancien-mot-de-passe-3"),
            role="client", role_client=None, is_active=True,
        ))
        donnees.commit()
        jeton = _jeton(client_http, "vieux-compte@client-tests.fr",
                       "ancien-mot-de-passe-3")
        reponse = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/conversations", headers=_entetes(jeton)
        )
        assert reponse.status_code == 403


class TestHierarchieRoles:
    def test_le_lecteur_lit_mais_n_ecrit_pas(self, client_http):
        jeton = _jeton(client_http, "lecteur-a@client-tests.fr",
                       "ancien-mot-de-passe-2")
        entetes = _entetes(jeton)
        assert client_http.get(
            f"/api/client/v1/sites/{SITE_A}/conversations", headers=entetes
        ).status_code == 200
        assert client_http.post(
            f"/api/client/v1/sites/{SITE_A}/conversations/conv-a-1/takeover",
            headers=entetes,
        ).status_code == 403
        assert client_http.put(
            f"/api/client/v1/sites/{SITE_A}/settings",
            headers=entetes, json={"welcome_message": "pirate"},
        ).status_code == 403

    def test_l_operateur_repond_mais_ne_regle_pas(self, client_http):
        jeton, _ = _creer_proprietaire(client_http, "operateur@client-tests.fr",
                                       role_client="client_operator")
        entetes = _entetes(jeton)
        assert client_http.post(
            f"/api/client/v1/sites/{SITE_A}/conversations/conv-a-1/reply",
            headers=entetes, json={"content": "Bonjour, je regarde cela."},
        ).status_code == 200
        assert client_http.put(
            f"/api/client/v1/sites/{SITE_A}/settings",
            headers=entetes, json={"welcome_message": "Bienvenue !"},
        ).status_code == 403

    def test_le_proprietaire_admin_regle_son_site(self, client_http):
        jeton = _creer_admin_2fa(client_http, "regleur@client-tests.fr")
        entetes = _entetes(jeton)
        assert client_http.put(
            f"/api/client/v1/sites/{SITE_A}/settings",
            headers=entetes, json={"welcome_message": "Bienvenue chez nous !"},
        ).status_code == 200


class Test2FA:
    def _admin_actif(self, client_http):
        """Compte client_admin provisioné, mdp changé, prêt pour la 2FA."""
        jeton, mdp = _creer_proprietaire(client_http, "securise@client-tests.fr")
        client_http.post(
            "/api/client/v1/password", headers=_entetes(jeton),
            json={"ancien_mot_de_passe": mdp,
                  "nouveau_mot_de_passe": NOUVEAU_MDP},
        )
        return _jeton(client_http, "securise@client-tests.fr",
                      NOUVEAU_MDP)

    def test_client_admin_sans_2fa_est_bloque_sur_les_routes_du_site(
        self, client_http
    ):
        jeton = self._admin_actif(client_http)
        reponse = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/conversations", headers=_entetes(jeton)
        )
        assert reponse.status_code == 403
        assert "2FA" in reponse.json()["detail"]

    def test_setup_renvoie_secret_et_uri_une_fois_et_stocke_chiffre(
        self, client_http, donnees
    ):
        jeton = self._admin_actif(client_http)
        reponse = client_http.post("/api/client/v1/2fa/setup", headers=_entetes(jeton))
        assert reponse.status_code == 200
        corps = reponse.json()
        assert corps["secret"]
        assert corps["otpauth_uri"].startswith("otpauth://totp/")

        compte = donnees.query(User).filter_by(email="securise@client-tests.fr").one()
        # PREUVE du chiffrement : la base ne contient PAS le secret en clair.
        assert compte.totp_secret != corps["secret"]
        assert compte.totp_secret.startswith("fernet:v1:")
        assert corps["secret"] not in compte.totp_secret

    def test_activation_avec_mauvais_puis_bon_code(self, client_http):
        jeton = self._admin_actif(client_http)
        secret = client_http.post(
            "/api/client/v1/2fa/setup", headers=_entetes(jeton)
        ).json()["secret"]

        mauvais = client_http.post(
            "/api/client/v1/2fa/activate", headers=_entetes(jeton), json={"code": "000000"}
        )
        assert mauvais.status_code == 400

        bon = client_http.post(
            "/api/client/v1/2fa/activate", headers=_entetes(jeton),
            json={"code": pyotp.TOTP(secret).now()},
        )
        assert bon.status_code == 200
        assert bon.json()["tfa_active"] is True

        # La 2FA étant active, les routes du site s'ouvrent.
        assert client_http.get(
            f"/api/client/v1/sites/{SITE_A}/conversations", headers=_entetes(jeton)
        ).status_code == 200

    def test_login_bloque_sans_code_puis_passe_avec_code(self, client_http):
        jeton = self._admin_actif(client_http)
        secret = client_http.post(
            "/api/client/v1/2fa/setup", headers=_entetes(jeton)
        ).json()["secret"]
        assert client_http.post(
            "/api/client/v1/2fa/activate", headers=_entetes(jeton),
            json={"code": pyotp.TOTP(secret).now()},
        ).status_code == 200

        # Sans code → 401 avec la raison EXPLICITE `2fa_requise`.
        sans_code = client_http.post(
            "/api/auth/login",
            data={"username": "securise@client-tests.fr",
                  "password": NOUVEAU_MDP},
        )
        assert sans_code.status_code == 401
        assert sans_code.json()["detail"] == "2fa_requise"

        # Avec un code invalide → 401 également.
        assert client_http.post(
            "/api/auth/login",
            data={"username": "securise@client-tests.fr",
                  "password": NOUVEAU_MDP, "totp_code": "000000"},
        ).status_code == 401

        # Avec le BON code → la connexion passe.
        avec_code = client_http.post(
            "/api/auth/login",
            data={"username": "securise@client-tests.fr",
                  "password": NOUVEAU_MDP,
                  "totp_code": pyotp.TOTP(secret).now()},
        )
        assert avec_code.status_code == 200

        # Variante JSON : même contrat.
        assert client_http.post(
            "/api/auth/login/json",
            json={"email": "securise@client-tests.fr",
                  "password": NOUVEAU_MDP,
                  "totp_code": pyotp.TOTP(secret).now()},
        ).status_code == 200

    def test_desactivation_exige_le_mot_de_passe(self, client_http, donnees):
        jeton = self._admin_actif(client_http)
        entetes = _entetes(jeton)
        secret = client_http.post(
            "/api/client/v1/2fa/setup", headers=entetes
        ).json()["secret"]
        client_http.post("/api/client/v1/2fa/activate", headers=entetes,
                         json={"code": pyotp.TOTP(secret).now()})

        # Sans mot de passe → refus.
        assert client_http.post(
            "/api/client/v1/2fa/disable", headers=entetes, json={}
        ).status_code == 422
        # Avec le mauvais mot de passe → refus.
        assert client_http.post(
            "/api/client/v1/2fa/disable", headers=entetes,
            json={"mot_de_passe": "faux"},
        ).status_code == 400
        # Avec le bon → désactivée, secret effacé, audit tracé.
        ok = client_http.post(
            "/api/client/v1/2fa/disable", headers=entetes,
            json={"mot_de_passe": NOUVEAU_MDP},
        )
        assert ok.status_code == 200
        compte = donnees.query(User).filter_by(email="securise@client-tests.fr").one()
        assert compte.totp_enabled is False
        assert compte.totp_secret is None

        from backend.core.audit import AuditLog
        actions = [l.action for l in donnees.query(AuditLog).all()]
        assert "activation_2fa" in actions and "desactivation_2fa" in actions


class TestJournalAudit:
    def test_l_admin_lit_le_journal(self, client_http):
        _creer_proprietaire(client_http, "journal@client-tests.fr")
        reponse = client_http.get("/api/chatbot/admin/audit", headers=_admin(client_http))
        assert reponse.status_code == 200
        actions = {l["action"] for l in reponse.json()["audit"]}
        assert "creation_compte_client" in actions

    def test_le_journal_est_refuse_aux_non_admins(self, client_http):
        jeton, _ = _creer_proprietaire(client_http, "pas-admin@client-tests.fr")
        assert client_http.get(
            "/api/chatbot/admin/audit", headers=_entetes(jeton)
        ).status_code == 403


# ============================================================
# B3 — API client v1, endpoint par endpoint
# ============================================================


class TestConversationsClient:
    def test_me_expose_le_profil_complet(self, client_http):
        brut = client_http.post(
            "/api/chatbot/admin/clients",
            headers=_admin(client_http),
            json={"email": "profil@client-tests.fr", "nom": "Profil",
                  "site_id": SITE_A, "role_client": "client_admin"},
        )
        assert brut.status_code == 201
        jeton = _jeton(client_http, "profil@client-tests.fr",
                       brut.json()["mot_de_passe_temporaire"])
        corps = client_http.get("/api/client/v1/me", headers=_entetes(jeton)).json()
        assert corps["email"] == "profil@client-tests.fr"
        assert corps["role_client"] == "client_admin"
        assert corps["sites"][0]["site_id"] == SITE_A
        assert corps["sites"][0]["secteur"] == "restauration"
        assert corps["tfa"]["requise"] is True
        assert corps["must_change_password"] is True

    def test_liste_avec_pagination_et_filtres(self, client_http):
        jeton, _ = _creer_proprietaire(client_http, "liste@client-tests.fr",
                                       role_client="client_operator")
        entetes = _entetes(jeton)

        tout = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/conversations", headers=entetes
        ).json()
        assert tout["total"] == 2
        assert len(tout["conversations"]) == 2

        page = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/conversations?page=1&page_size=1",
            headers=entetes,
        ).json()
        assert page["page_size"] == 1 and len(page["conversations"]) == 1

        escaladees = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/conversations?escalade=true",
            headers=entetes,
        ).json()
        assert [c["conversation_id"] for c in escaladees["conversations"]] == ["conv-a-2"]

        avec_lead = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/conversations?avec_lead=true",
            headers=entetes,
        ).json()
        assert [c["conversation_id"] for c in avec_lead["conversations"]] == ["conv-a-2"]

        non_lues = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/conversations?non_lu=true",
            headers=entetes,
        ).json()
        # conv-a-1 : dernier message = assistant → lue ; conv-a-2 : user → non lue.
        assert [c["conversation_id"] for c in non_lues["conversations"]] == ["conv-a-2"]

        recherche = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/conversations?q=réservation",
            headers=entetes,
        ).json()
        assert [c["conversation_id"] for c in recherche["conversations"]] == ["conv-a-2"]

    def test_detail_sans_le_moindre_nom_d_agent(self, client_http):
        jeton, _ = _creer_proprietaire(client_http, "detail@client-tests.fr",
                                       role_client="client_operator")
        corps = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/conversations/conv-a-1",
            headers=_entetes(jeton),
        )
        assert corps.status_code == 200
        brut = corps.text.lower()
        assert "agent_used" not in brut
        assert "assigned_agent" not in brut
        assert corps.json()["visitor"]["email"] == "michu@exemple-tests.fr"
        assert len(corps.json()["messages"]) == 2

    def test_reprise_puis_rendu_de_la_main(self, client_http, donnees):
        jeton, _ = _creer_proprietaire(client_http, "main@client-tests.fr",
                                       role_client="client_operator")
        entetes = _entetes(jeton)
        prise = client_http.post(
            f"/api/client/v1/sites/{SITE_A}/conversations/conv-a-1/takeover",
            headers=entetes,
        )
        assert prise.status_code == 200
        conversation = donnees.query(ChatbotConversation).filter_by(
            conversation_id="conv-a-1").one()
        assert conversation.conversation_metadata["human_active"] is True
        assert conversation.status == "escalated"

        rendu = client_http.post(
            f"/api/client/v1/sites/{SITE_A}/conversations/conv-a-1/release",
            headers=entetes,
        )
        assert rendu.status_code == 200
        donnees.expire_all()
        conversation = donnees.query(ChatbotConversation).filter_by(
            conversation_id="conv-a-1").one()
        assert conversation.conversation_metadata["human_active"] is False
        assert conversation.status == "active"

    def test_reponse_humaine_ecrit_un_message_et_prend_la_main(self, client_http, donnees):
        jeton, _ = _creer_proprietaire(client_http, "repond@client-tests.fr",
                                       role_client="client_operator")
        reponse = client_http.post(
            f"/api/client/v1/sites/{SITE_A}/conversations/conv-a-1/reply",
            headers=_entetes(jeton),
            json={"content": "Bonjour, la table est réservée."},
        )
        assert reponse.status_code == 200
        message = donnees.query(ChatbotMessage).filter_by(
            conversation_id="conv-a-1").order_by(ChatbotMessage.id.desc()).first()
        assert message.content == "Bonjour, la table est réservée."
        assert message.context_data["human"] is True
        conversation = donnees.query(ChatbotConversation).filter_by(
            conversation_id="conv-a-1").one()
        assert conversation.conversation_metadata["human_active"] is True

    def test_analytics_reutilise_le_calcul_existant(self, client_http):
        jeton, _ = _creer_proprietaire(client_http, "stats@client-tests.fr",
                                       role_client="client_operator")
        reponse = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/analytics", headers=_entetes(jeton)
        )
        assert reponse.status_code == 200
        corps = reponse.json()
        # Même forme que GET /api/chatbot/analytics/{site_id}.
        assert "total_conversations" in corps or "conversations" in corps

    def test_leads_du_site(self, client_http):
        jeton, _ = _creer_proprietaire(client_http, "leads@client-tests.fr",
                                       role_client="client_operator")
        corps = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/leads", headers=_entetes(jeton)
        ).json()
        assert corps["total"] == 1
        lead = corps["leads"][0]
        assert lead["email"] == "seguin@exemple-tests.fr"
        assert lead["lead_type"] == "hot"

    def test_commandes_etat_explicite_200_pas_d_erreur(self, client_http):
        """Règle produit : ne jamais vendre ce qui n'existe pas."""
        jeton, _ = _creer_proprietaire(client_http, "orders@client-tests.fr",
                                       role_client="client_operator")
        reponse = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/orders", headers=_entetes(jeton)
        )
        assert reponse.status_code == 200
        corps = reponse.json()
        assert corps["disponible"] is False
        assert "e-commerce" in corps["raison"]
        assert corps["orders"] == []


class TestReglages:
    def test_get_expose_le_prompt_en_lecture_seule(self, client_http):
        jeton = _creer_admin_2fa(client_http, "lire@client-tests.fr")
        corps = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/settings", headers=_entetes(jeton)
        ).json()
        assert corps["system_prompt"].startswith("Tu es Mia")
        assert corps["system_prompt_modifiable"] is False
        assert "horaires" in corps
        assert corps["competences"] is None  # null = toutes actives

    def test_put_refuse_le_system_prompt_avec_la_raison(self, client_http):
        jeton = _creer_admin_2fa(client_http, "prompt@client-tests.fr")
        reponse = client_http.put(
            f"/api/client/v1/sites/{SITE_A}/settings", headers=_entetes(jeton),
            json={"system_prompt": "Nouveau prompt pirate"},
        )
        assert reponse.status_code == 400
        assert "ePerformance" in reponse.json()["detail"]

    def test_put_welcome_message_horaires_et_competences(self, client_http, donnees):
        jeton = _creer_admin_2fa(client_http, "regle@client-tests.fr")
        entetes = _entetes(jeton)
        reponse = client_http.put(
            f"/api/client/v1/sites/{SITE_A}/settings", headers=entetes,
            json={
                "welcome_message": "Bienvenue au Bistrot !",
                "horaires": {"lundi": "fermé", "dimanche": "9h-14h"},
                "competences": ["carte et plats", "horaires"],
                "rate_limit_messages_per_minute": 30,
            },
        )
        assert reponse.status_code == 200
        donnees.expire_all()
        site = donnees.query(ChatbotSite).filter_by(site_id=SITE_A).one()
        assert site.welcome_message == "Bienvenue au Bistrot !"
        # Le piège JSON du projet : réassignation + flag_modified → vérifié ici.
        assert site.horaires == {"lundi": "fermé", "dimanche": "9h-14h"}
        assert site.allowed_intents == ["carte et plats", "horaires"]
        assert site.rate_limit_messages_per_minute == 30

    def test_put_rate_limit_hors_bornes_422(self, client_http):
        jeton = _creer_admin_2fa(client_http, "bornes@client-tests.fr")
        reponse = client_http.put(
            f"/api/client/v1/sites/{SITE_A}/settings", headers=_entetes(jeton),
            json={"rate_limit_messages_per_minute": 99999},
        )
        assert reponse.status_code == 422

    def test_put_notification_settings_type_inconnu_422_et_partiel_complete(
        self, client_http, donnees
    ):
        jeton = _creer_admin_2fa(client_http, "notifs@client-tests.fr")
        entetes = _entetes(jeton)

        assert client_http.put(
            f"/api/client/v1/sites/{SITE_A}/settings", headers=entetes,
            json={"notification_settings": {"type_fantome": {"push": True}}},
        ).status_code == 422

        # Réglage PARTIEL : les canaux absents reprennent le DÉFAUT SENSIBLE
        # (nouveau_visiteur doit rester silencieux sur les canaux non cités).
        reponse = client_http.put(
            f"/api/client/v1/sites/{SITE_A}/settings", headers=entetes,
            json={"notification_settings": {
                "nouveau_visiteur": {"push": True},
            }},
        )
        assert reponse.status_code == 200
        reglage = reponse.json()["settings"]["notifications"]["par_type"]["nouveau_visiteur"]
        assert reglage == {"push": True, "email": False, "telegram": False}

    def test_put_rien_du_tout_400(self, client_http):
        jeton = _creer_admin_2fa(client_http, "vide@client-tests.fr")
        assert client_http.put(
            f"/api/client/v1/sites/{SITE_A}/settings", headers=_entetes(jeton), json={}
        ).status_code == 400


class TestCompetences:
    def test_les_competences_viennent_du_noyau_et_etat_par_allowed_intents(
        self, client_http, donnees
    ):
        jeton = _creer_admin_2fa(client_http, "comp@client-tests.fr")
        entetes = _entetes(jeton)

        corps = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/competences", headers=entetes
        ).json()
        assert corps["disponible"] is True
        assert corps["secteur"] == "restauration"
        themes = {c["theme"]: c["active"] for c in corps["competences"]}
        assert themes  # le noyau fournit les thèmes FAQ du secteur
        assert all(themes.values())  # null = toutes actives

        # Désactivation d'une compétence via PUT /settings.
        client_http.put(
            f"/api/client/v1/sites/{SITE_A}/settings", headers=entetes,
            json={"competences": list(themes)[:1]},
        )
        corps2 = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/competences", headers=entetes
        ).json()
        etats = {c["theme"]: c["active"] for c in corps2["competences"]}
        assert sum(etats.values()) == 1

    def test_sans_secteur_etat_explicite(self, client_http, donnees):
        site_b = donnees.query(ChatbotSite).filter_by(site_id=SITE_B).one()
        site_b.sector = None
        donnees.commit()
        jeton, _ = _creer_proprietaire(client_http, "sansecteur@client-tests.fr",
                                       role_client="client_operator",
                                       site_id=SITE_B)
        corps = client_http.get(
            f"/api/client/v1/sites/{SITE_B}/competences", headers=_entetes(jeton)
        ).json()
        assert corps["disponible"] is False
        assert corps["competences"] == []


class TestNotificationsInApp:
    def test_liste_et_marquage_lu(self, client_http, donnees):
        from backend.chatbot.models import ClientNotification

        donnees.add_all([
            ClientNotification(site_id=SITE_A, type="nouveau_lead",
                               titre="Nouveau lead", corps="Coordonnées laissées"),
            ClientNotification(site_id=SITE_A, type="escalade",
                               titre="Escalade", corps="Un humain est demandé"),
            ClientNotification(site_id=SITE_B, type="escalade",
                               titre="Chez le voisin", corps="Ne doit pas sortir"),
        ])
        donnees.commit()

        jeton, _ = _creer_proprietaire(client_http, "inbox@client-tests.fr",
                                       role_client="client_operator")
        entetes = _entetes(jeton)
        corps = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/notifications", headers=entetes
        ).json()
        assert corps["total"] == 2  # jamais la notification du site B
        assert corps["non_lues"] == 2

        lue = client_http.post(
            f"/api/client/v1/sites/{SITE_A}/notifications/read", headers=entetes,
            json={"toutes": True},
        ).json()
        assert lue["marquees_lues"] == 2
        assert client_http.get(
            f"/api/client/v1/sites/{SITE_A}/notifications?lu=false",
            headers=entetes,
        ).json()["total"] == 0


class TestRGPD:
    def test_export_complet_et_trace(self, client_http, donnees):
        from backend.core.audit import AuditLog

        jeton, _ = _creer_proprietaire(client_http, "rgpd@client-tests.fr",
                                       role_client="client_operator")
        reponse = client_http.get(
            f"/api/client/v1/sites/{SITE_A}/rgpd/conversations/conv-a-1/export",
            headers=_entetes(jeton),
        )
        assert reponse.status_code == 200
        corps = reponse.json()
        assert corps["export_rgpd"] is True
        assert len(corps["messages"]) == 2
        assert corps["conversation"]["visitor_email"] == "michu@exemple-tests.fr"
        assert donnees.query(AuditLog).filter_by(
            action="export_rgpd_conversation").count() == 1

    def test_suppression_cascade_messages_leads_et_trace(self, client_http, donnees):
        from backend.core.audit import AuditLog

        donnees.add(ChatbotLead(
            conversation_id="conv-a-1", site_id=SITE_A, name="Madame Michu",
            email="michu@exemple-tests.fr", lead_type="cold", status="new",
        ))
        donnees.commit()

        jeton = _creer_admin_2fa(client_http, "efface@client-tests.fr")
        reponse = client_http.delete(
            f"/api/client/v1/sites/{SITE_A}/rgpd/conversations/conv-a-1",
            headers=_entetes(jeton),
        )
        assert reponse.status_code == 200
        assert reponse.json()["supprime"] is True
        assert donnees.query(ChatbotMessage).filter_by(
            conversation_id="conv-a-1").count() == 0
        assert donnees.query(ChatbotLead).filter_by(
            conversation_id="conv-a-1").count() == 0
        assert donnees.query(ChatbotConversation).filter_by(
            conversation_id="conv-a-1").count() == 0
        assert donnees.query(AuditLog).filter_by(
            action="suppression_rgpd_conversation").count() == 1

        # Une fois supprimée : 404, même pour le propriétaire.
        assert client_http.get(
            f"/api/client/v1/sites/{SITE_A}/conversations/conv-a-1",
            headers=_entetes(jeton),
        ).status_code == 404


# ============================================================
# Rate limiting (mécanisme in-memory existant, bornes B1/B2)
# ============================================================


class TestRateLimiting:
    def test_429_sur_la_route_mdp_apres_5_tentatives(self, client_http):
        """La route /password est bornée à 5/300s (force brute). Le middleware
        passe AVANT l'auth : des requêtes sans jeton suffisent à remplir le sac."""
        for _ in range(5):
            reponse = client_http.post(
                "/api/client/v1/password",
                headers={"Authorization": "Bearer jeton-invalide"},
                json={"ancien_mot_de_passe": "x", "nouveau_mot_de_passe": "y"},
            )
            assert reponse.status_code == 401  # refus d'auth, sac rempli
        deborde = client_http.post(
            "/api/client/v1/password",
            headers={"Authorization": "Bearer jeton-invalide"},
            json={"ancien_mot_de_passe": "x", "nouveau_mot_de_passe": "y"},
        )
        assert deborde.status_code == 429
        assert "Trop de requêtes" in deborde.json()["detail"]

    def test_une_autre_route_n_est_pas_contaminee(self, client_http):
        for _ in range(6):
            client_http.post(
                "/api/client/v1/password",
                headers={"Authorization": "Bearer jeton-invalide"}, json={},
            )
        # Le sac est par chemin : /2fa/setup reste servie (401, pas 429).
        reponse = client_http.post(
            "/api/client/v1/2fa/setup",
            headers={"Authorization": "Bearer jeton-invalide"},
        )
        assert reponse.status_code == 401

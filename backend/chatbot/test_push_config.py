#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests de `GET /api/chatbot/push/config` — la clé publique servie au navigateur.

CE QUE CETTE ROUTE DOIT GARANTIR, ET QUI EST VÉRIFIÉ ICI
--------------------------------------------------------
  1. elle est PUBLIQUE (aucun jeton) et en LECTURE SEULE (aucune écriture, aucune
     dépendance à la base : elle répond même si la base est indisponible) ;
  2. sans clé configurée, elle répond 200 avec un ÉTAT explicite — jamais une
     erreur, jamais une exception : c'est le monde réel d'aujourd'hui ;
  3. avec des clés valides, elle sert la clé PUBLIQUE dans la forme attendue par
     `applicationServerKey` (base64url sans remplissage, point P-256 non
     compressé) ;
  4. **la clé PRIVÉE ne sort jamais** — y compris dans le cas le plus
     dangereux : la clé privée collée par erreur dans `VAPID_PUBLIC_KEY`. Ce
     cas n'est pas hypothétique, le script de génération documenté imprime les
     deux lignes à la suite. Les tests ci-dessous vérifient le corps BRUT de la
     réponse (pas le JSON analysé) et cherchent la valeur ET ses préfixes, dans
     la clé servie comme dans les messages d'erreur.

Les tests ne dépendent d'aucune clé réelle : les clés VAPID sont générées à la
volée, dans le test, et ne sont jamais écrites sur disque ni versionnées.

Exécution :
    cd /home/ballo/OX6A/unified-ia-backend
    python3 -m pytest backend/chatbot/test_push_config.py -q
"""
import base64
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))

from backend.chatbot import notifications, push_abonnements  # noqa: E402

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

CHEMIN = "/api/chatbot/push/config"


# ============================================================
# OUTILS — DES CLÉS VRAIES, GÉNÉRÉES POUR LE TEST
# ============================================================


def b64url(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode()


def paire_de_cles() -> dict:
    """Une paire VAPID P-256 réelle, dans le format que produit la doc (§7.1).

    `py_vapid` n'est pas nécessaire : `cryptography`, lui, est une dépendance de
    production (`python-jose[cryptography]`).
    """
    from cryptography.hazmat.primitives import serialization as ser
    from cryptography.hazmat.primitives.asymmetric import ec

    cle = ec.generate_private_key(ec.SECP256R1())
    return {
        "privee": b64url(
            cle.private_bytes(
                ser.Encoding.DER, ser.PrivateFormat.PKCS8, ser.NoEncryption()
            )
        ),
        "publique": b64url(
            cle.public_key().public_bytes(
                ser.Encoding.X962, ser.PublicFormat.UncompressedPoint
            )
        ),
    }


@pytest.fixture
def cles(monkeypatch):
    """Paire VAPID posée dans l'environnement du test. Jamais sur disque."""
    paire = paire_de_cles()
    monkeypatch.setenv("VAPID_PUBLIC_KEY", paire["publique"])
    monkeypatch.setenv("VAPID_PRIVATE_KEY", paire["privee"])
    monkeypatch.setenv("VAPID_CONTACT", "notifications@exemple.test")
    return paire


def _simuler_bibliotheque(monkeypatch, presente: bool) -> None:
    """Déclare `pywebpush` présente (ou absente) à `notifications.etat_canal`.

    L'environnement de test n'installe pas `pywebpush` : dix-neuf tests de la
    suite le constatent et se sautent. Or `etat_canal("webpush")` refuse de
    déclarer le canal configuré quand la bibliothèque manque — c'est voulu, mais
    ce n'est pas ce que cette route teste. Les deux états sont donc rendus
    DÉTERMINISTES ici, sans installer ni désinstaller quoi que ce soit : seule
    la recherche de spécification (`importlib.util.find_spec`, exactement ce que
    fait `etat_canal`) est remplacée.
    """
    import importlib.util as util

    vrai = util.find_spec

    def _trouve(nom, *args, **kwargs):
        if nom == "pywebpush":
            return object() if presente else None
        return vrai(nom, *args, **kwargs)

    monkeypatch.setattr(util, "find_spec", _trouve)


@pytest.fixture
def bibliotheque_presente(monkeypatch):
    """Le canal peut réellement envoyer : clés présentes ET bibliothèque là."""
    _simuler_bibliotheque(monkeypatch, True)


@pytest.fixture
def bibliotheque_absente(monkeypatch):
    """Clés présentes mais bibliothèque manquante : le canal ne peut pas envoyer."""
    _simuler_bibliotheque(monkeypatch, False)


@pytest.fixture
def sans_cles(monkeypatch):
    """Aucune clé de notification : le monde réel d'aujourd'hui."""
    for nom in VARIABLES_NOTIFICATION:
        monkeypatch.delenv(nom, raising=False)


@pytest.fixture
def client():
    """Client de test. Aucune base n'est nécessaire : la route n'en dépend pas."""
    from fastapi.testclient import TestClient

    from backend.api.app import app

    with TestClient(app) as c:
        yield c


def configurer(client) -> dict:
    reponse = client.get(CHEMIN)
    assert reponse.status_code == 200, reponse.text
    return reponse.json()


# ============================================================
# 1. LA ROUTE — PUBLIQUE, LECTURE SEULE, SANS BASE
# ============================================================


class TestLaRoute:
    def test_la_route_est_publique_et_ne_demande_aucun_jeton(self, client, sans_cles):
        reponse = client.get(CHEMIN, headers={})
        assert reponse.status_code == 200

    def test_la_route_ne_touche_pas_la_base(self, client, sans_cles):
        """Elle répond même si la base est indisponible : état, pas panne.

        Le test remplace la dépendance de base par une fonction qui LÈVE. Si la
        route la déclarait, l'appel produirait une erreur ; comme elle ne la
        déclare pas, la réponse est normale.
        """
        from backend.api.app import app
        from backend.core.database import get_db

        def _base_morte():  # pragma: no cover - ne doit jamais être appelée
            raise RuntimeError("base indisponible")

        app.dependency_overrides[get_db] = _base_morte
        try:
            assert client.get(CHEMIN).status_code == 200
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_la_route_n_accepte_aucune_ecriture(self, client, sans_cles):
        """Lecture seule : POST, PUT et DELETE ne sont pas routés."""
        for methode in ("post", "put", "delete", "patch"):
            assert getattr(client, methode)(CHEMIN).status_code == 405, methode

    def test_la_route_est_stable_sur_appels_repetes(self, client, cles):
        """Une constante : deux appels donnent exactement la même réponse."""
        assert configurer(client) == configurer(client)

    def test_la_route_ne_prend_aucun_parametre(self, client, cles):
        """Aucune entrée : la réponse ne peut pas dépendre de l'appelant."""
        assert configurer(client) == client.get(CHEMIN + "?x=1&y=2").json()

    def test_la_reponse_ne_contient_ni_jeton_ni_endpoint_d_abonnement(self, client, cles):
        corps = configurer(client)
        assert "endpoint" not in json.dumps(corps)
        assert "keys" not in corps
        assert "p256dh" not in json.dumps(corps)
        assert "auth" not in corps


# ============================================================
# 2. SANS CLÉ — UN ÉTAT EXPLICITE, PAS UNE ERREUR
# ============================================================


class TestSansCle:
    def test_sans_cle_la_reponse_reste_200(self, client, sans_cles):
        assert client.get(CHEMIN).status_code == 200

    def test_sans_cle_le_canal_est_declare_non_configure(self, client, sans_cles):
        corps = configurer(client)
        assert corps["configure"] is False
        assert corps["canal"]["configure"] is False
        assert corps["canal"]["canal"] == "webpush"

    def test_sans_cle_aucune_cle_n_est_servie(self, client, sans_cles):
        corps = configurer(client)
        assert corps["cle_publique"] is None

    def test_sans_cle_la_raison_est_explicite_et_nomme_la_variable(self, client, sans_cles):
        corps = configurer(client)
        assert "VAPID_PUBLIC_KEY" in corps["raison"]
        assert "non configuré" in corps["raison"]

    def test_sans_cle_le_message_dit_que_rien_ne_casse_cote_visiteur(self, client, sans_cles):
        corps = configurer(client)
        assert "non configuré" in corps["message"]
        assert corps["forme_cle"] == "absente"

    def test_aucune_exception_levee_sans_aucune_variable(self, client, sans_cles):
        """Point dur de la dégradation : zéro variable, zéro exception."""
        corps = configurer(client)
        assert isinstance(corps, dict)
        assert set(corps) == {
            "canal",
            "configure",
            "cle_publique",
            "raison",
            "forme_cle",
            "message",
        }


# ============================================================
# 3. AVEC CLÉ — LA BONNE VALEUR, DANS LA BONNE FORME
# ============================================================


class TestAvecCle:
    def test_avec_cles_le_canal_est_configure(self, client, cles, bibliotheque_presente):
        corps = configurer(client)
        assert corps["configure"] is True
        assert corps["canal"]["configure"] is True
        assert corps["raison"] is None

    def test_la_cle_publique_servie_est_celle_de_l_environnement(self, client, cles):
        assert configurer(client)["cle_publique"] == cles["publique"]

    def test_la_cle_servie_se_decode_en_point_p256_valide(self, client, cles):
        """La forme attendue par `applicationServerKey`, vérifiée pour de vrai."""
        from cryptography.hazmat.primitives.asymmetric import ec

        servie = configurer(client)["cle_publique"]
        octets = base64.urlsafe_b64decode(servie + "=" * (-len(servie) % 4))
        assert len(octets) == 65
        assert octets[0] == 0x04
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), octets)

    def test_la_cle_est_servie_sans_remplissage(self, client, cles):
        assert "=" not in configurer(client)["cle_publique"]

    def test_le_remplissage_est_tolere_et_retire(self, client, cles, bibliotheque_presente, monkeypatch):
        """Une variable collée avec du remplissage reste utilisable."""
        monkeypatch.setenv("VAPID_PUBLIC_KEY", cles["publique"] + "==")
        corps = configurer(client)
        assert corps["configure"] is True
        assert corps["cle_publique"] == cles["publique"]

    def test_un_espace_autour_de_la_valeur_est_ignore(self, client, cles, monkeypatch):
        monkeypatch.setenv("VAPID_PUBLIC_KEY", f"  {cles['publique']}\n")
        assert configurer(client)["cle_publique"] == cles["publique"]

    def test_la_forme_reconnue_est_nommee(self, client, cles):
        assert "P-256" in configurer(client)["forme_cle"]

    def test_cle_publique_seule_le_canal_reste_non_configure(self, client, cles, monkeypatch):
        """Clé publique sans clé privée : le navigateur pourrait s'abonner,
        mais RIEN ne pourrait être envoyé. La fonctionnalité n'est donc pas
        proposée — promettre ce qui ne peut pas partir serait une fausse
        promesse — tandis que la clé publique, elle, reste servie."""
        monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
        corps = configurer(client)
        assert corps["configure"] is False
        assert corps["cle_publique"] == cles["publique"]
        assert "VAPID_PRIVATE_KEY" in corps["raison"]
        assert "non configuré" in corps["message"]

    def test_sans_bibliotheque_le_canal_reste_non_configure(self, client, cles, bibliotheque_absente):
        """Clés posées mais `pywebpush` absent : la clé publique est servie, la
        fonctionnalité n'est pas proposée, et la raison nomme ce qui manque."""
        corps = configurer(client)
        assert corps["cle_publique"] == cles["publique"]
        assert corps["configure"] is False
        assert "pywebpush" in corps["raison"]


# ============================================================
# 4. LA CLÉ PRIVÉE NE SORT JAMAIS — LE POINT DE SÉCURITÉ
# ============================================================


def _corps_brut(client) -> str:
    """Le corps de la réponse tel qu'il part sur le réseau, non analysé."""
    reponse = client.get(CHEMIN)
    assert reponse.status_code == 200
    return reponse.text


class TestClePriveeJamaisExposee:
    def test_la_cle_privee_n_est_pas_dans_la_reponse(self, client, cles):
        corps = _corps_brut(client)
        assert cles["privee"] not in corps
        assert cles["publique"] in corps  # la publique, elle, DOIT être là

    def test_aucun_prefixe_de_la_cle_privee_n_apparait(self, client, cles):
        """Même une valeur tronquée serait une fuite : on cherche les préfixes."""
        corps = _corps_brut(client)
        for longueur in (16, 24, 32, 48, 64):
            assert cles["privee"][:longueur] not in corps, longueur

    def test_aucun_morceau_de_la_cle_privee_n_apparait(self, client, cles):
        """Découpage glissant : aucun bloc de 24 caractères consécutifs."""
        corps = _corps_brut(client)
        morceaux = [cles["privee"][i : i + 24] for i in range(0, len(cles["privee"]) - 24, 8)]
        assert not [m for m in morceaux if m in corps]

    def test_aucun_pem_n_est_servi(self, client, cles):
        corps = _corps_brut(client)
        assert "-----BEGIN" not in corps
        assert "PRIVATE KEY" not in corps.upper()

    def test_la_cle_privee_inversee_dans_la_variable_publique_est_REFUSEE(
        self, client, cles, monkeypatch
    ):
        """LE CAS DANGEREUX, celui que la route doit rendre impossible.

        Le script de génération documenté imprime la ligne de la clé privée EN
        PREMIER. Un copier-coller du mauvais bloc met donc la clé privée dans
        `VAPID_PUBLIC_KEY`. Sans contrôle de forme, cet endpoint public la
        servirait au monde entier.
        """
        monkeypatch.setenv("VAPID_PUBLIC_KEY", cles["privee"])
        corps = configurer(client)
        assert corps["cle_publique"] is None
        assert corps["configure"] is False
        assert corps["raison"] is not None
        assert "clé privée PKCS8" in corps["forme_cle"]

    def test_la_cle_privee_inversee_n_apparait_NULLE_PART_dans_la_reponse(
        self, client, cles, monkeypatch
    ):
        """Y compris dans le message d'erreur : il ne recopie jamais la valeur."""
        monkeypatch.setenv("VAPID_PUBLIC_KEY", cles["privee"])
        corps = _corps_brut(client)
        assert cles["privee"] not in corps
        for longueur in (8, 16, 24, 32, 48):
            assert cles["privee"][:longueur] not in corps, longueur

    def test_la_cle_privee_inversee_est_refusee_pour_tous_les_formats(
        self, client, cles, bibliotheque_presente, monkeypatch
    ):
        """La même clé privée sous d'autres habits : PEM, avec remplissage.

        La mention « EXAMPLE » dans l'en-tête n'est pas décorative : c'est le
        marqueur de gabarit du garde-fou `scripts/verifier-secrets.py`, qui
        signale tout en-tête PEM privé en clair. Sans lui, ce test — qui ne
        contient aucune clé, seulement l'en-tête — serait pris pour une fuite et
        bloquerait le push. Ne pas la retirer.
        """
        pem = (
            "-----BEGIN EXAMPLE PRIVATE KEY-----\n"
            + cles["privee"]
            + "\n-----END EXAMPLE PRIVATE KEY-----"
        )
        for valeur in (cles["privee"], cles["privee"] + "=", pem):
            monkeypatch.setenv("VAPID_PUBLIC_KEY", valeur)
            corps = configurer(client)
            assert corps["cle_publique"] is None
            assert corps["configure"] is False
            assert cles["privee"][:32] not in _corps_brut(client)

    @pytest.mark.parametrize(
        "nom, valeur",
        [
            ("PEM publique", "-----BEGIN PUBLIC KEY-----\nMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE\n-----END PUBLIC KEY-----"),
            ("PEM sur une ligne", "-----BEGIN PUBLIC KEY----- MFkw EwYHKoZIzj0 -----END PUBLIC KEY-----"),
            ("graine brute de 32 octets", "A" * 43),
            ("texte libre", "cle-publique-de-demonstration"),
            ("point hors courbe", "B" * 87),
            ("point compressé de 33 octets", "A" * 44),
            ("trop court", "B" * 40),
            ("trop long", "B" * 120),
            ("base64url avec un caractère hors alphabet", "B" * 86 + "!"),
        ],
    )
    def test_toute_forme_non_publique_est_refusee_sans_etre_recopiee(
        self, client, monkeypatch, nom, valeur
    ):
        monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
        monkeypatch.setenv("VAPID_PUBLIC_KEY", valeur)
        corps_brut = _corps_brut(client)
        corps = json.loads(corps_brut)

        assert corps["cle_publique"] is None, nom
        assert corps["configure"] is False, nom
        assert corps["raison"], nom
        # Le motif ne doit pas non plus recopier la valeur entière.
        if len(valeur) > 8:
            assert valeur not in corps_brut, nom

    def test_le_code_de_la_route_ne_nomme_jamais_la_cle_privee(self):
        """Garde-fou de lecture : la route ne peut pas fuiter ce qu'elle ne lit pas.

        Vérification sur la SOURCE, en complément des tests de comportement :
        elle tient même pour un chemin d'exécution qu'aucun test n'emprunte.
        """
        import inspect

        from backend.api.routes import chatbot

        source_route = inspect.getsource(chatbot.configurer_push)
        source_config = inspect.getsource(push_abonnements.config_cle_publique)
        for source in (source_route, source_config):
            assert "VAPID_PRIVATE_KEY" not in source

    def test_seule_la_variable_publique_est_lue(self, monkeypatch):
        """`config_cle_publique` ne lit QUE `VAPID_PUBLIC_KEY`."""
        import os

        vues = []
        vrai_getenv = os.getenv

        def _espion(nom, *args, **kwargs):
            vues.append(nom)
            return vrai_getenv(nom, *args, **kwargs)

        monkeypatch.setattr(push_abonnements.os, "getenv", _espion)
        monkeypatch.setattr(notifications.os, "getenv", _espion)
        push_abonnements.config_cle_publique()
        assert "VAPID_PRIVATE_KEY" not in vues

    def test_le_journal_ne_recopie_pas_la_cle_privee(self, client, cles, caplog):
        """Aucun journal de cette route ne porte la clé privée."""
        import logging

        with caplog.at_level(logging.DEBUG):
            configurer(client)
        assert cles["privee"] not in caplog.text
        assert cles["privee"][:32] not in caplog.text

    def test_la_cle_publique_servie_n_est_pas_utilisable_comme_cle_privee(self, client, cles):
        """Contre-épreuve : ce qui est servi ne permet pas de SIGNER.

        Sans elle, on pourrait servir une clé qui se décode mais qui contient
        aussi la matière privée. Le test vérifie que la valeur servie ne
        contient pas de scalaire privé exploitable : elle fait 65 octets et se
        décode comme un point public, pas comme une clé privée PKCS8.
        """
        from cryptography.hazmat.primitives import serialization as ser

        servie = configurer(client)["cle_publique"]
        octets = base64.urlsafe_b64decode(servie + "=" * (-len(servie) % 4))
        with pytest.raises(Exception):
            ser.load_der_private_key(octets, password=None)


# ============================================================
# 5. LE CONTRAT ENTRE LA ROUTE ET LE WIDGET
# ============================================================


class TestContratWidget:
    def test_les_cles_de_reponse_sont_stables(self, client, cles):
        """Le widget lit ces champs : les renommer casserait son état."""
        corps = configurer(client)
        for champ in ("canal", "configure", "cle_publique", "raison", "message"):
            assert champ in corps, champ

    def test_configure_est_un_booleen_dans_les_deux_mondes(
        self, client, sans_cles, cles, bibliotheque_presente, monkeypatch
    ):
        """Le widget teste `configure` : ce doit être un booléen, jamais None."""
        assert configurer(client)["configure"] is True
        monkeypatch.delenv("VAPID_PUBLIC_KEY", raising=False)
        assert configurer(client)["configure"] is False
        assert isinstance(configurer(client)["configure"], bool)

    def test_la_reponse_est_du_json(self, client, sans_cles):
        reponse = client.get(CHEMIN)
        assert reponse.headers["content-type"].startswith("application/json")

    def test_le_widget_peut_s_abonner_avec_la_cle_servie(
        self, client, cles, bibliotheque_presente, monkeypatch
    ):
        """Bout en bout : la clé servie est acceptée par la route d'abonnement.

        C'est le seul enchaînement qui compte : le widget récupère la clé, le
        navigateur produit un abonnement, l'abonnement s'enregistre.
        """
        from fastapi.testclient import TestClient

        from backend.api.app import app
        from backend.core.database import Base, get_db
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        import backend.core.models  # noqa: F401

        moteur = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(bind=moteur)
        Session = sessionmaker(bind=moteur)
        session = Session()

        def _db():
            try:
                yield session
            finally:
                pass

        app.dependency_overrides[get_db] = _db
        try:
            with TestClient(app) as c:
                cle_servie = c.get(CHEMIN).json()["cle_publique"]
                assert cle_servie == cles["publique"]
                reponse = c.post(
                    "/api/chatbot/push/subscribe",
                    json={
                        "endpoint": "https://fcm.googleapis.com/fcm/send/jeton-de-test",
                        "keys": {"p256dh": "B" * 87, "auth": "C" * 22},
                    },
                )
                assert reponse.status_code == 200
                assert reponse.json()["canal"]["configure"] is True
        finally:
            app.dependency_overrides.pop(get_db, None)
            session.close()
            moteur.dispose()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests du chantier B4 — déclencheurs de notification du propriétaire (app Mia).

CE QUE CETTE SUITE PROUVE
-------------------------
· Les TROIS événements (nouveau lead, escalade, nouveau visiteur) déduits du
  pipeline `POST /message` préviennent le propriétaire ;
· la notification IN-APP est écrite TOUJOURS (elle ne dépend d'aucune clé) ;
· les canaux suivent les RÉGLAGES PAR TYPE du site (défauts sensibles : lead
  et escalade prévenus, nouveau visiteur silencieux) ;
· les trois états de canal (envoyé, échec, non configuré) sont tracés et
  n'importe JAMAIS d'exception dans le pipeline du visiteur ;
· sans clés VAPID, dégradation propre : `non_configure`, pas de panne ;
· aucun nom d'agent ne sort dans une notification (règle produit : Mia seule).

Exécution :
    cd /home/ballo/OX6A/unified-ia-backend
    python3 -m pytest backend/chatbot/test_refonte_declencheurs.py -q
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

import backend.core.models  # noqa: E402,F401 (déclare users — FK implicites)
from backend.chatbot import declencheurs, notifications  # noqa: E402
from backend.chatbot.models import (  # noqa: E402
    ChatbotConversation,
    ChatbotNotificationLog,
    ChatbotSite,
    ClientNotification,
    PushSubscription,
)
from backend.core.database import Base  # noqa: E402

SITE = "site_restaurant_b4"


@pytest.fixture
def base():
    """Base SQLite en mémoire avec toutes les tables nécessaires."""
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
def site(base):
    """Un site client, sans aucun réglage de notification (défauts produits)."""
    site = ChatbotSite(
        site_id=SITE,
        site_name="Le Bistrot B4",
        system_prompt="Tu es Mia.",
        is_active=True,
    )
    base.add(site)
    base.commit()
    return site


@pytest.fixture
def sans_cles(monkeypatch):
    """Aucune clé de fournisseur : tous les canaux sont « non configurés »."""
    for variable in (
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_ADMIN_CHAT_ID",
        "BREVO_API_KEY", "BREVO_SENDER_EMAIL", "BREVO_NOTIF_EMAIL",
        "VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_CONTACT",
    ):
        monkeypatch.delenv(variable, raising=False)
    return True


def _conversation(base, conversation_id="conv-b4-1", status="active",
                  lead_captured=False):
    conversation = ChatbotConversation(
        conversation_id=conversation_id,
        site_id=SITE,
        status=status,
        lead_captured=lead_captured,
        message_count=1,
    )
    base.add(conversation)
    base.commit()
    return conversation


def _abonnement(base, endpoint="https://push.example/abo-1"):
    """Un abonnement push ACTIF du site (créé par le widget)."""
    abonnement = PushSubscription(
        endpoint=endpoint,
        keys_p256dh="cle-p256dh-de-test",
        keys_auth="cle-auth-de-test",
        site_id=SITE,
        actif=True,
    )
    base.add(abonnement)
    base.commit()
    return abonnement


# ============================================================
# Réglages par type
# ============================================================


class TestReglagesEffectifs:
    def test_les_defauts_sensibles_sont_respectes(self, site):
        effectifs = declencheurs.reglages_effectifs(site)
        assert effectifs["nouveau_lead"] == {"push": True, "email": True, "telegram": True}
        assert effectifs["escalade"] == {"push": True, "email": True, "telegram": True}
        assert effectifs["nouveau_visiteur"] == {"push": False, "email": False, "telegram": False}

    def test_un_reglage_partiel_est_complete_par_les_defauts(self, base, site):
        site.notification_settings = {"nouveau_visiteur": {"push": True}}
        base.commit()
        effectifs = declencheurs.reglages_effectifs(site)
        # push demandé vrai, les canaux absents reprennent le défaut (False).
        assert effectifs["nouveau_visiteur"] == {"push": True, "email": False, "telegram": False}

    def test_un_reglage_malforme_ne_leve_jamais(self, base, site):
        site.notification_settings = {"nouveau_lead": "pas-un-dict", "autre": 42}
        base.commit()
        effectifs = declencheurs.reglages_effectifs(site)
        assert effectifs["nouveau_lead"] == {"push": True, "email": True, "telegram": True}
        assert set(effectifs) == set(declencheurs.TYPES_EVENEMENTS)


# ============================================================
# L'événement unique : in-app TOUJOURS, canaux selon réglages
# ============================================================


class TestNotifierEvenement:
    def test_la_notification_in_app_est_ecrite_sans_aucune_cle(
        self, base, site, sans_cles
    ):
        resume = declencheurs.notifier_evenement(
            base, SITE, declencheurs.TYPE_NOUVEAU_LEAD,
            "Nouveau lead capturé par Mia", "Un visiteur a laissé ses coordonnées.",
            arriere_plan=False,
        )
        assert resume["in_app"] is True
        notifications_table = base.query(ClientNotification).all()
        assert len(notifications_table) == 1
        assert notifications_table[0].site_id == SITE
        assert notifications_table[0].type == "nouveau_lead"
        assert notifications_table[0].lu is False

    def test_sans_cles_les_canaux_sont_non_configures_et_traces(
        self, base, site, sans_cles
    ):
        _abonnement(base)  # un abonnement push ACTIF attend un envoi
        declencheurs.notifier_evenement(
            base, SITE, declencheurs.TYPE_NOUVEAU_LEAD,
            "Nouveau lead", "Corps", arriere_plan=False,
            fabrique_session=lambda: sessionmaker(bind=base.get_bind())(),
        )
        traces = base.query(ChatbotNotificationLog).all()
        statuts = {t.canal: t.statut for t in traces}
        # Dégradation propre : non_configure, jamais d'exception.
        assert statuts.get("webpush") == "non_configure"
        assert statuts.get("email") == "non_configure"
        assert statuts.get("telegram") == "non_configure"
        # Rien n'a été « envoyé ».
        assert all(t.succes is False for t in traces)

    def test_le_reglage_par_type_coupe_les_canaux(self, base, site, sans_cles, monkeypatch):
        # Nouveau visiteur : désactivé par défaut → AUCUN envoi tenté.
        appel = {"compte": 0}

        def _envoyer_interdit(*args, **kwargs):
            appel["compte"] += 1
            raise AssertionError("aucun envoi ne doit être tenté")

        monkeypatch.setattr(notifications, "envoyer", _envoyer_interdit)
        declencheurs.notifier_evenement(
            base, SITE, declencheurs.TYPE_NOUVEAU_VISITEUR,
            "Nouveau visiteur", "Corps", arriere_plan=False,
            fabrique_session=lambda: sessionmaker(bind=base.get_bind())(),
        )
        assert appel["compte"] == 0
        assert base.query(ChatbotNotificationLog).count() == 0
        # ... mais la notification in-app est écrite quand même.
        assert base.query(ClientNotification).count() == 1

    def test_le_reglage_par_type_active_les_canaux(self, base, site, sans_cles, monkeypatch):
        site.notification_settings = {"nouveau_visiteur": {"push": True}}
        base.commit()
        canaux = []

        def _envoyer_factice(canal, destinataire, sujet, message, abonnements=None):
            canaux.append(canal)
            return notifications.ResultatEnvoi(
                canal=canal, succes=False, statut="non_configure",
                destinataire=destinataire, erreur="test",
            )

        monkeypatch.setattr(notifications, "envoyer", _envoyer_factice)
        declencheurs.notifier_evenement(
            base, SITE, declencheurs.TYPE_NOUVEAU_VISITEUR,
            "Nouveau visiteur", "Corps", arriere_plan=False,
            fabrique_session=lambda: sessionmaker(bind=base.get_bind())(),
        )
        assert canaux == ["webpush"]

    def test_les_interrupteurs_du_site_coupent_leurs_canaux(
        self, base, site, sans_cles, monkeypatch
    ):
        site.notification_telegram_enabled = False
        site.notification_email_enabled = False
        base.commit()
        canaux = []

        def _envoyer_factice(canal, destinataire, sujet, message, abonnements=None):
            canaux.append(canal)
            return notifications.ResultatEnvoi(
                canal=canal, succes=False, statut="non_configure",
                destinataire=destinataire, erreur="test",
            )

        monkeypatch.setattr(notifications, "envoyer", _envoyer_factice)
        declencheurs.notifier_evenement(
            base, SITE, declencheurs.TYPE_NOUVEAU_LEAD,
            "Nouveau lead", "Corps", arriere_plan=False,
            fabrique_session=lambda: sessionmaker(bind=base.get_bind())(),
        )
        assert canaux == ["webpush"]

    def test_site_inconnu_etat_explicite_pas_d_exception(self, base, sans_cles):
        resume = declencheurs.notifier_evenement(
            base, "site-inexistant", declencheurs.TYPE_NOUVEAU_LEAD,
            "Titre", "Corps", arriere_plan=False,
            fabrique_session=lambda: sessionmaker(bind=base.get_bind())(),
        )
        assert resume["raison"] == "site_inconnu"
        assert base.query(ClientNotification).count() == 0

    def test_le_compte_provisione_devient_destinataire_email(
        self, base, site, sans_cles
    ):
        from backend.core.auth import get_password_hash
        from backend.core.models import User

        base.add(User(
            email="proprio@client-tests.fr",
            password_hash=get_password_hash("mot-de-passe-test-1"),
            role="client", role_client="client_operator",
            site_id=SITE, is_active=True,
        ))
        base.commit()
        destinataires = declencheurs._destinataires_email(site, base)
        assert destinataires == ["proprio@client-tests.fr"]

    def test_le_mode_arriere_plan_n_bloque_pas_le_visiteur(self, base, site, sans_cles, monkeypatch):
        """Par défaut (arriere_plan=True), l'envoi est DÉLÉGUÉ à un thread et
        la fonction rend la main immédiatement, l'in-app déjà écrite. Le
        thread est capturé (pas laissé courir) : le travail délégué est
        exécuté ensuite de façon déterministe sur SA propre session."""
        delegue = {}

        class _ThreadCapturé:
            def __init__(self, target=None, name=None, daemon=None):
                delegue["target"] = target
                delegue["daemon"] = daemon

            def start(self):
                pass  # le vrai thread partirait ici ; on le garde sous la main

        monkeypatch.setattr(declencheurs.threading, "Thread", _ThreadCapturé)
        debut = time.monotonic()
        resume = declencheurs.notifier_evenement(
            base, SITE, declencheurs.TYPE_NOUVEAU_LEAD,
            "Nouveau lead", "Corps",  # arriere_plan=True par défaut
            fabrique_session=lambda: sessionmaker(bind=base.get_bind())(),
        )
        assert resume["in_app"] is True
        assert resume["arriere_plan"] is True
        assert delegue["daemon"] is True  # un thread daemon : jamais bloquant
        base.commit()
        assert base.query(ClientNotification).count() == 1

        # Le travail délégué s'exécute proprement, sur sa session propre.
        delegue["target"]()


# ============================================================
# Les trois états d'un canal, tracés dans tous les cas
# ============================================================


class TestLesTroisEtats:
    """Chaque canal est testé dans ses 3 états (même contrat que la 6.5)."""

    @pytest.fixture
    def notification_envoyee(self, base, site):
        _abonnement(base)
        declencheurs.notifier_evenement(
            base, SITE, declencheurs.TYPE_NOUVEAU_LEAD,
            "Nouveau lead", "Corps", arriere_plan=False,
            fabrique_session=lambda: sessionmaker(bind=base.get_bind())(),
        )
        return base

    def test_etat_envoye_est_trace_et_l_abonnement_marque(
        self, base, site, monkeypatch
    ):
        _abonnement(base)
        envoyes = []

        def _envoyer_reussi(canal, destinataire, sujet, message, abonnements=None):
            envoyes.append(canal)
            return notifications.ResultatEnvoi(
                canal=canal, succes=True, statut="envoye",
                destinataire=destinataire or "1 abonnement",
                messages_envoyes=1, identifiant_fournisseur="msg-123",
            )

        monkeypatch.setattr(notifications, "envoyer", _envoyer_reussi)
        declencheurs.notifier_evenement(
            base, SITE, declencheurs.TYPE_NOUVEAU_LEAD,
            "Nouveau lead", "Corps", arriere_plan=False,
            fabrique_session=lambda: sessionmaker(bind=base.get_bind())(),
        )
        trace = base.query(ChatbotNotificationLog).filter_by(canal="webpush").one()
        assert trace.statut == "envoye"
        assert trace.succes is True
        assert trace.envoye_le is not None
        abonnement = base.query(PushSubscription).one()
        assert abonnement.date_derniere_utilisation is not None

    def test_etat_echec_est_trace_sans_lever(self, base, site, monkeypatch):
        _abonnement(base)

        def _envoyer_echoue(canal, destinataire, sujet, message, abonnements=None):
            return notifications.ResultatEnvoi(
                canal=canal, succes=False, statut="echec",
                destinataire=destinataire, code_erreur="401",
                erreur="jeton refusé par le fournisseur",
            )

        monkeypatch.setattr(notifications, "envoyer", _envoyer_echoue)
        # NE LÈVE PAS — c'est le contrat.
        declencheurs.notifier_evenement(
            base, SITE, declencheurs.TYPE_ESCALADE,
            "Escalade", "Corps", arriere_plan=False,
            fabrique_session=lambda: sessionmaker(bind=base.get_bind())(),
        )
        trace = base.query(ChatbotNotificationLog).filter_by(canal="webpush").one()
        assert trace.statut == "echec"
        assert trace.code_erreur == "401"
        # L'in-app est écrite malgré l'échec du canal.
        assert base.query(ClientNotification).count() == 1

    def test_etat_non_configure_est_trace(self, base, site, sans_cles):
        _abonnement(base)
        declencheurs.notifier_evenement(
            base, SITE, declencheurs.TYPE_NOUVEAU_LEAD,
            "Nouveau lead", "Corps", arriere_plan=False,
            fabrique_session=lambda: sessionmaker(bind=base.get_bind())(),
        )
        trace = base.query(ChatbotNotificationLog).filter_by(canal="webpush").one()
        assert trace.statut == "non_configure"
        assert trace.succes is False
        assert "VAPID" in (trace.erreur or "") or trace.erreur


# ============================================================
# La déduction des événements après le pipeline /message
# ============================================================


class TestTraiterApresMessage:
    def test_nouveau_lead_par_action_reussie(self, base, site, sans_cles):
        _conversation(base)
        resumes = declencheurs.traiter_apres_message(
            db=base, site_id=SITE, conversation_id="conv-b4-1",
            est_nouvelle_conversation=False,
            lead_captured_avant=False, statut_avant="active",
            actions=[{"action": "lead_capture", "success": True}],
            arriere_plan=False,
        )
        assert len(resumes) == 1
        assert resumes[0]["type"] == "nouveau_lead"
        assert base.query(ClientNotification).filter_by(
            type="nouveau_lead").count() == 1

    def test_nouveau_lead_par_bascule_du_drapeau(self, base, site, sans_cles):
        _conversation(base, lead_captured=True)  # faux avant, vrai maintenant
        resumes = declencheurs.traiter_apres_message(
            db=base, site_id=SITE, conversation_id="conv-b4-1",
            est_nouvelle_conversation=False,
            lead_captured_avant=False, statut_avant="active",
            actions=[],
            arriere_plan=False,
        )
        assert [r["type"] for r in resumes] == ["nouveau_lead"]

    def test_pas_de_lead_si_le_drapeau_etait_deja_leve(self, base, site, sans_cles):
        _conversation(base, lead_captured=True)
        resumes = declencheurs.traiter_apres_message(
            db=base, site_id=SITE, conversation_id="conv-b4-1",
            est_nouvelle_conversation=False,
            lead_captured_avant=True, statut_avant="active",
            actions=[],
            arriere_plan=False,
        )
        assert resumes == []
        assert base.query(ClientNotification).count() == 0

    def test_escalade_par_bascule_de_statut(self, base, site, sans_cles):
        _conversation(base, status="escalated")
        resumes = declencheurs.traiter_apres_message(
            db=base, site_id=SITE, conversation_id="conv-b4-1",
            est_nouvelle_conversation=False,
            lead_captured_avant=False, statut_avant="active",
            actions=[],
            arriere_plan=False,
        )
        assert [r["type"] for r in resumes] == ["escalade"]

    def test_pas_d_escalade_si_le_statut_n_a_pas_change(self, base, site, sans_cles):
        _conversation(base, status="escalated")
        resumes = declencheurs.traiter_apres_message(
            db=base, site_id=SITE, conversation_id="conv-b4-1",
            est_nouvelle_conversation=False,
            lead_captured_avant=False, statut_avant="escalated",
            actions=[],
            arriere_plan=False,
        )
        assert resumes == []

    def test_nouveau_visiteur_in_app_silencieux_sur_les_canaux(
        self, base, site, sans_cles, monkeypatch
    ):
        _conversation(base)
        canaux = []

        def _envoyer_compte(canal, destinataire, sujet, message, abonnements=None):
            canaux.append(canal)
            return notifications.ResultatEnvoi(
                canal=canal, succes=False, statut="non_configure",
                destinataire=destinataire, erreur="test",
            )

        monkeypatch.setattr(notifications, "envoyer", _envoyer_compte)
        resumes = declencheurs.traiter_apres_message(
            db=base, site_id=SITE, conversation_id="conv-b4-1",
            est_nouvelle_conversation=True,
            lead_captured_avant=False, statut_avant="active",
            actions=[],
            arriere_plan=False,
        )
        assert [r["type"] for r in resumes] == ["nouveau_visiteur"]
        assert canaux == []  # réglage par défaut : silencieux
        assert base.query(ClientNotification).count() == 1

    def test_lead_et_escalade_et_visiteur_le_meme_message(self, base, site, sans_cles):
        """Un message qui capture un lead ET escalade prévient deux fois :
        ce sont deux événements métier distincts."""
        _conversation(base, status="escalated", lead_captured=True)
        resumes = declencheurs.traiter_apres_message(
            db=base, site_id=SITE, conversation_id="conv-b4-1",
            est_nouvelle_conversation=True,
            lead_captured_avant=False, statut_avant="active",
            actions=[{"action": "lead_capture", "success": True}],
            arriere_plan=False,
        )
        assert {r["type"] for r in resumes} == {
            "nouveau_lead", "escalade", "nouveau_visiteur",
        }

    def test_actions_malformees_ne_levent_jamais(self, base, site, sans_cles):
        _conversation(base)
        resumes = declencheurs.traiter_apres_message(
            db=base, site_id=SITE, conversation_id="conv-b4-1",
            est_nouvelle_conversation=False,
            lead_captured_avant=False, statut_avant=None,
            actions=["pas-un-dict", None, {"success": True}],
            arriere_plan=False,
        )
        assert resumes == []

    def test_aucun_nom_d_agent_dans_les_notifications(self, base, site, sans_cles):
        """Règle produit : Mia seule — jamais le nom ni le compteur d'agents."""
        _conversation(base, status="escalated", lead_captured=True)
        declencheurs.traiter_apres_message(
            db=base, site_id=SITE, conversation_id="conv-b4-1",
            est_nouvelle_conversation=True,
            lead_captured_avant=False, statut_avant="active",
            actions=[{"action": "lead_capture", "success": True}],
            arriere_plan=False,
        )
        for notification in base.query(ClientNotification).all():
            texte = f"{notification.titre} {notification.corps}".lower()
            assert "agent" not in texte
            assert "27" not in texte

    def test_le_pipeline_ne_leve_jamais_meme_en_cas_de_sinistre(
        self, base, site, monkeypatch
    ):
        """Le visiteur ne doit JAMAIS payer une panne de notification."""
        def _sinistre(*args, **kwargs):
            raise RuntimeError("panne simulée")

        monkeypatch.setattr(declencheurs, "notifier_evenement", _sinistre)
        resumes = declencheurs.traiter_apres_message(
            db=base, site_id=SITE, conversation_id="conv-b4-1",
            est_nouvelle_conversation=False,
            lead_captured_avant=False, statut_avant="active",
            actions=[{"action": "lead_capture", "success": True}],
            arriere_plan=False,
        )
        assert resumes == []  # absorbé, journalisé, jamais propagé


if __name__ == "__main__":
    pytest.main([__file__, "-q"])

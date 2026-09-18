#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests de la tâche 6.3-BIS (Bloc A) — backend.

Couvre, sans réseau ni base de données :
  · A.1 — vision : détection par magic bytes, plafond de dimension, detail,
          corps multimodal OpenAI-compatible, modèle `deepseek-flash` ;
  · A.5 — plus aucun canevas de premier contact dans les personas ;
  · A.6 — aucune clé d'agent ne peut sortir dans une réponse (post-processing)
          et aucun persona ne porte de prénom de collègue ;
  · A.8 — les neuf intents pointent vers des agents RÉELS, le préfixe
          `[intent:…]` est reconnu puis retiré, le mapping reste interne.

Exécution :
    cd /home/ballo/OX6A/unified-ia-backend
    python3 -m pytest backend/chatbot/test_tache_6_3_bis.py -q
"""
import base64
import io
import re
import struct
import sys
import zlib
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))

from backend.chatbot import vision  # noqa: E402
from backend.chatbot.agent_router import AgentRouter  # noqa: E402
from backend.chatbot.response_generator import ResponseGenerator  # noqa: E402
from backend.chatbot.service import extraire_intent_explicite  # noqa: E402
from backend.core import llm_client  # noqa: E402

AGENTS_DIR = Path(__file__).resolve().parent / "agents"


# ---------------------------------------------------------------- fabriques

def png(w: int, h: int, rgb=(180, 40, 40)) -> bytes:
    """PNG minimal uni, sans dépendance."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        corps = tag + data
        return (
            struct.pack(">I", len(data))
            + corps
            + struct.pack(">I", zlib.crc32(corps) & 0xFFFFFFFF)
        )

    ligne = b"\x00" + bytes(rgb) * w
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(ligne * h))
        + chunk(b"IEND", b"")
    )


GIF_1PX = base64.b64decode(
    b"R0lGODlhAgACAIAAAP///////yH5BAAAAAAALAAAAAACAAIAAAIChFEAOw=="
)
WEBP_1PX = base64.b64decode(b"UklGRhoAAABXRUJQVlA4TA0AAAAvAAAAEAcQERGIiP4HAA==")


def b64(octets: bytes) -> str:
    return base64.b64encode(octets).decode("ascii")


# ============================================================ A.1 — VISION

class TestVisionFormats:
    """Les quatre formats acceptés sont reconnus par leur CONTENU."""

    @pytest.mark.parametrize(
        "octets,attendu",
        [
            (png(8, 8), "image/png"),
            (GIF_1PX, "image/gif"),
            (WEBP_1PX, "image/webp"),
            # JPEG minimal : SOI + APP0 + fin de scan
            (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9", "image/jpeg"),
        ],
    )
    def test_detection_par_contenu(self, octets, attendu):
        assert vision.detecter_media_type(octets) == attendu

    def test_extension_menteuse_le_contenu_gagne(self):
        """Un PNG annoncé `image/jpeg` est traité comme un PNG."""
        image = vision.preparer_image(
            data=b64(png(8, 8)),
            media_type_declare="image/jpeg",
            nom="photo.jpg",
        )
        assert image["media_type"] == "image/png"
        assert image["media_type_declare"] == "image/jpeg"  # écart conservé
        assert image["data_uri"].startswith("data:image/png;base64,")

    @pytest.mark.parametrize(
        "contenu",
        [b"<html><body>pas une image</body></html>", b"MZ\x90\x00" + b"\x00" * 64, b""],
    )
    def test_formats_refuses(self, contenu):
        with pytest.raises(vision.ImageInvalide):
            vision.preparer_image(data=b64(contenu))

    def test_base64_invalide_refuse(self):
        with pytest.raises(vision.ImageInvalide):
            vision.preparer_image(data="ceci-n'est-pas-du-base64!!")


class TestVisionBudget:
    """Le coût en tokens est borné avant l'envoi (plafond ~384)."""

    def test_grande_image_reduite_a_512(self):
        from PIL import Image

        tampon = io.BytesIO()
        Image.new("RGB", (2000, 1500), (10, 120, 200)).save(
            tampon, format="JPEG", quality=90
        )
        image = vision.preparer_image(data=b64(tampon.getvalue()))
        mesures = image["mesures"]
        assert mesures["reduite"] is True
        assert max(mesures["largeur"], mesures["hauteur"]) == vision.MAX_DIMENSION
        assert mesures["origine"] == (2000, 1500)

    def test_image_deja_petite_non_retouchee(self):
        image = vision.preparer_image(data=b64(png(64, 64)))
        assert image["mesures"]["reduite"] is False

    def test_estimation_sous_le_plafond_de_384_tokens(self):
        """Borne documentée : 512 px ⇒ 1 tuile ⇒ 85 (low) / 255 (high)."""
        assert vision.TOKENS_ESTIMES_LOW < 384
        assert vision.TOKENS_ESTIMES_HIGH < 384

    def test_poids_maximum_refuse(self):
        gros = b"\xff\xd8\xff" + b"\x00" * (vision.TAILLE_MAX_OCTETS + 10)
        with pytest.raises(vision.ImageInvalide) as err:
            vision.preparer_image(data=b64(gros))
        assert "volumineuse" in str(err.value)


class TestVisionDetail:
    def test_detail_par_defaut_auto(self):
        assert vision.preparer_image(data=b64(png(8, 8)))["detail"] == "auto"

    @pytest.mark.parametrize("detail", ["low", "high", "auto"])
    def test_detail_acceptes(self, detail):
        image = vision.preparer_image(data=b64(png(8, 8)), detail=detail)
        assert vision.bloc_vision(image)["image_url"]["detail"] == detail

    def test_detail_inconnu_refuse(self):
        with pytest.raises(vision.ImageInvalide):
            vision.preparer_image(data=b64(png(8, 8)), detail="ultra")

    def test_bloc_openai_compatible(self):
        bloc = vision.bloc_vision(vision.preparer_image(data=b64(png(8, 8))))
        assert bloc["type"] == "image_url"
        assert set(bloc["image_url"]) == {"url", "detail"}
        assert bloc["image_url"]["url"].startswith("data:image/png;base64,")


class TestVisionDansLePrompt:
    """Le message courant devient multi-contenu ; l'historique reste textuel."""

    def _generateur(self):
        return ResponseGenerator(agents_dir=AGENTS_DIR)

    def test_message_multimodal(self):
        generateur = self._generateur()
        image = vision.preparer_image(data=b64(png(16, 16)))
        messages = generateur._build_messages_history(
            system_prompt="system", message="Que vois-tu ?", context={}, image=image
        )
        contenu = messages[-1]["content"]
        assert isinstance(contenu, list)
        assert contenu[0] == {"type": "text", "text": "Que vois-tu ?"}
        assert contenu[1]["type"] == "image_url"
        assert len(messages) == 2

    def test_sans_image_message_textuel(self):
        generateur = self._generateur()
        messages = generateur._build_messages_history(
            system_prompt="system", message="Bonjour", context={}, image=None
        )
        assert messages[-1]["content"] == "Bonjour"

    def test_prompt_vision_interdit_de_redemander_une_description(self):
        generateur = self._generateur()
        prompt = generateur._build_system_prompt(
            agent_persona=None,
            context={},
            intent="general_question",
            agent_key="sales-discovery-coach",
            has_image=True,
        )
        assert "IMAGE JOINTE" in prompt
        assert "Ne demande JAMAIS" in prompt

    def test_prompt_sans_image_ne_parle_pas_de_vision(self):
        generateur = self._generateur()
        prompt = generateur._build_system_prompt(
            agent_persona=None,
            context={},
            intent="general_question",
            agent_key="sales-discovery-coach",
            has_image=False,
        )
        assert "IMAGE JOINTE" not in prompt


class TestModeleDeepSeek:
    """A.1 — l'ID unique est `deepseek-flash`, surchargeable par l'environnement."""

    def test_modele_par_defaut(self):
        assert llm_client.DEEPSEEK_MODEL == "deepseek-flash"

    def test_surchargeable_par_env(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-autre")
        import importlib

        module = importlib.reload(llm_client)
        try:
            assert module.DEEPSEEK_MODEL == "deepseek-autre"
        finally:
            monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
            importlib.reload(llm_client)

    def test_plus_aucune_reference_a_lancien_id_dans_le_corps(self):
        corps = llm_client._deepseek_body([{"role": "user", "content": "hi"}], 0.7, 100)
        assert corps["model"] == llm_client.DEEPSEEK_MODEL
        assert "deepseek-chat" not in str(corps)

    def test_reasoning_effort_par_defaut_present(self):
        corps = llm_client._deepseek_body([], 0.7, 100)
        assert corps["reasoning_effort"] == llm_client.DEEPSEEK_REASONING_EFFORT

    def test_contenu_multimodal_traverse_le_corps(self):
        image = vision.preparer_image(data=b64(png(8, 8)))
        corps = llm_client._deepseek_body(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "décris"},
                        vision.bloc_vision(image),
                    ],
                }
            ],
            0.3,
            300,
        )
        assert isinstance(corps["messages"][0]["content"], list)
        assert corps["messages"][0]["content"][1]["image_url"]["url"].startswith("data:")


# ================================================= A.5 / A.6 — PERSONAS

def _personas():
    return sorted(AGENTS_DIR.rglob("*.md"))


class TestPersonas:
    """A.5 (pas de canevas) et A.6 (aucun nom d'agent humain)."""

    def test_les_27_agents_sont_presents(self):
        assert len(_personas()) == 27

    def test_tous_nomment_mia(self):
        sans_mia = [p.name for p in _personas() if "Mia" not in p.read_text(encoding="utf-8")]
        assert sans_mia == [], f"personas sans identité Mia : {sans_mia}"

    @pytest.mark.parametrize(
        "prenom",
        [
            "Marc", "Sarah", "David", "Moussa", "Ibrahim", "Karim", "Aïcha",
            "Fatima", "Mariama", "Aissatou", "Boubacar", "Abdoul", "Amina",
            "Ousmane", "Sekou", "Mariam", "Salimata", "Ibrahima", "Fatoumata",
            "Youssef", "Khadija", "Amadou", "Ndeye",
        ],
    )
    def test_aucun_prenom_de_collegue(self, prenom):
        coupables = []
        for persona in _personas():
            for numero, ligne in enumerate(
                persona.read_text(encoding="utf-8").splitlines(), 1
            ):
                if re.search(rf"\b{prenom}\b", ligne):
                    coupables.append(f"{persona.name}:{numero}")
        assert coupables == [], f"« {prenom} » fuit dans {coupables}"

    def test_plus_de_canevas_spin_ni_de_structure_numerotee(self):
        coach = (AGENTS_DIR / "sales" / "sales-discovery-coach.md").read_text(encoding="utf-8")
        # Les sections qui portaient le canevas ont disparu (les titres cités
        # dans la note de maintenance ne sont pas des sections)
        for titre in (
            "## Structure de Réponse",
            "## Exemples de Réponses",
            "### Framework SPIN",
            "### Lead CHAUD",
            "### Lead TIÈDE",
        ):
            assert titre not in coach, titre
        # Le rôle de découverte reste décrit — en principes
        assert "Situation" in coach and "Problème" in coach
        assert "Tu n'as pas de liste à dérouler" in coach

    def test_plus_de_phrase_de_transfert_nommee(self):
        support = (AGENTS_DIR / "support" / "customer_support.md").read_text(encoding="utf-8")
        assert "notre experte marketing" not in support
        assert "notre expert technique" not in support
        assert "notre expert sales" not in support

    def test_conseiller_generique_utilise(self):
        support = (AGENTS_DIR / "support" / "customer_support.md").read_text(encoding="utf-8")
        assert "un conseiller ePerformance" in support


class TestFuiteNomAgent:
    """A.6 — défense en profondeur à la sortie du générateur."""

    def _generateur(self):
        return ResponseGenerator(agents_dir=AGENTS_DIR)

    @pytest.mark.parametrize(
        "entree",
        [
            "Je te passe à sales-discovery-coach pour la suite.",
            "Notre expert sales va reprendre avec toi.",
            "Je suis la discovery coach de ePerformance.",
            "Contacte marketing-seo-specialist, il gère ça.",
            "L'agent support prend le relais.",
        ],
    )
    def test_sortie_nettoyee(self, entree):
        generateur = self._generateur()
        sortie = generateur._neutraliser_noms_agents(entree)
        for motif in ResponseGenerator.MOTIFS_AGENTS:
            assert not re.search(motif, sortie, flags=re.IGNORECASE), motif

    def test_texte_normal_intact(self):
        """Le filtre ne touche pas une réponse légitime."""
        generateur = self._generateur()
        texte = "Bonjour 👋 Je suis Mia. Tu veux développer ton activité MLM ?"
        assert generateur._neutraliser_noms_agents(texte) == texte

    def test_prompt_pose_la_regle_d_identite(self):
        generateur = self._generateur()
        prompt = generateur._build_system_prompt(
            agent_persona="## persona",
            context={},
            intent="general_question",
            agent_key="sales-discovery-coach",
        )
        assert "IDENTITÉ — RÈGLE ABSOLUE" in prompt
        assert "sales-discovery-coach" in prompt  # en interdit, pas en identité
        assert "Jamais de nom d'agent" in prompt


# ================================================= A.8 — INTENTS

class TestIntentsSuggestions:
    """A.8 — les neuf intents routent vers des agents réels."""

    def test_dossier_des_agents_existe(self):
        assert AGENTS_DIR.is_dir()

    @pytest.mark.parametrize("intent", AgentRouter.INTENTS_SUGGESTIONS)
    def test_intent_mappe_vers_un_agent_reel(self, intent):
        agent = AgentRouter.INTENT_TO_AGENT_MAP.get(intent)
        assert agent, f"intent {intent} non mappé"
        fichiers = {p.stem for p in AGENTS_DIR.rglob("*.md")}
        assert agent in fichiers, f"{intent} → {agent} n'existe pas dans agents/"

    def test_tous_les_mappings_pointent_vers_un_agent_reel(self):
        fichiers = {p.stem for p in AGENTS_DIR.rglob("*.md")}
        orphelins = {
            intent: agent
            for intent, agent in AgentRouter.INTENT_TO_AGENT_MAP.items()
            if agent not in fichiers
        }
        assert orphelins == {}, f"mappings orphelins : {orphelins}"

    def test_routeur_resout_le_chemin_des_nouveaux_agents(self):
        routeur = AgentRouter(agents_base_path=str(AGENTS_DIR))
        for intent in AgentRouter.INTENTS_SUGGESTIONS:
            agent, meta = routeur.route(intent=intent, context={}, intent_metadata=None)
            assert Path(meta["agent_path"]).exists(), f"{intent} → chemin introuvable"

    def test_les_neuf_intents_sont_distincts_et_complets(self):
        assert len(set(AgentRouter.INTENTS_SUGGESTIONS)) == 9
        assert set(AgentRouter.INTENTS_SUGGESTIONS) <= set(AgentRouter.INTENT_TO_AGENT_MAP)

    def test_override_mlm_ne_detourne_pas_une_suggestion(self):
        """Un clic « Améliorer mon référencement » reste sur l'agent SEO."""
        routeur = AgentRouter(agents_base_path=str(AGENTS_DIR))
        contexte = {"history": [{"content": "je fais du MLM Longrich avec des filleuls"}]}
        agent, meta = routeur.route(
            intent="seo",
            context=contexte,
            intent_metadata={"source": "suggestion_click"},
        )
        assert agent == "marketing-seo-specialist"
        assert meta["routing_reason"] == "suggestion_intent"

    def test_override_mlm_toujours_actif_hors_suggestion(self):
        routeur = AgentRouter(agents_base_path=str(AGENTS_DIR))
        contexte = {"history": [{"content": "je fais du MLM Longrich avec des filleuls"}]}
        agent, meta = routeur.route(
            intent="general_question", context=contexte, intent_metadata=None
        )
        assert agent == "sales-outbound-strategist"
        assert meta["routing_reason"] == "mlm_override"


class TestPrefixeIntent:
    """Le préfixe `[intent:…]` est reconnu puis retiré du texte."""

    def test_prefixe_extrait(self):
        intent, message = extraire_intent_explicite("[intent:clients] Trouver plus de clients")
        assert intent == "clients"
        assert message == "Trouver plus de clients"

    def test_insensible_a_la_casse_et_aux_espaces(self):
        intent, message = extraire_intent_explicite("  [INTENT:Site_Web]  Créer un site  ")
        assert intent == "site_web"
        assert message == "Créer un site"

    def test_message_sans_prefixe_intact(self):
        intent, message = extraire_intent_explicite("Bonjour, comment ça va ?")
        assert intent is None
        assert message == "Bonjour, comment ça va ?"

    def test_le_prefixe_ne_survit_pas_dans_le_texte(self):
        _, message = extraire_intent_explicite("[intent:funnel] Optimiser mon tunnel")
        assert "[intent:" not in message

    @pytest.mark.parametrize("intent", AgentRouter.INTENTS_SUGGESTIONS)
    def test_les_neuf_intents_sont_reconnus(self, intent):
        extrait, message = extraire_intent_explicite(f"[intent:{intent}] Libellé")
        assert extrait == intent
        assert message == "Libellé"


# ================================================= lancer sans pytest

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ================================================= A.1 — OBSERVATION DÉDIÉE

class TestObservationImage:
    """
    L'image est décrite par un appel DÉDIÉ puis injectée dans le message.

    Mesure qui a motivé ce choix : avec le prompt complet de Mia (≈ 9 300
    caractères), un appel multimodal direct se trompait sur la couleur d'une
    image unie de 512 px ; avec un prompt minimal, il la lisait 3 fois sur 3.
    """

    def _generateur(self):
        return ResponseGenerator(agents_dir=AGENTS_DIR)

    def test_observation_injectee_dans_le_message(self):
        generateur = self._generateur()
        messages = generateur._build_messages_history(
            system_prompt="system",
            message="Tu penses quoi de ce visuel ?",
            context={},
            image={"data_uri": "data:image/png;base64,AAAA", "detail": "auto"},
            observation_image="Un carré vert uni sur fond blanc.",
        )
        contenu = messages[-1]["content"]
        assert isinstance(contenu, str)  # plus de multi-parties
        assert "[Observation de l'image jointe]" in contenu
        assert "Un carré vert uni sur fond blanc." in contenu
        assert "[Message du visiteur]" in contenu
        assert "Tu penses quoi de ce visuel ?" in contenu

    def test_repli_multimodal_si_observation_indisponible(self):
        generateur = self._generateur()
        messages = generateur._build_messages_history(
            system_prompt="system",
            message="Regarde",
            context={},
            image={"data_uri": "data:image/png;base64,AAAA", "detail": "auto"},
            observation_image=None,
        )
        contenu = messages[-1]["content"]
        assert isinstance(contenu, list)
        assert contenu[1]["type"] == "image_url"

    def test_message_vide_avec_image_reste_exploitable(self):
        generateur = self._generateur()
        messages = generateur._build_messages_history(
            system_prompt="system",
            message="",
            context={},
            image={"data_uri": "data:image/png;base64,AAAA", "detail": "auto"},
            observation_image="Une capture d'écran.",
        )
        assert "sans texte" in messages[-1]["content"]

    def test_prompt_de_description_ne_contient_pas_le_persona(self):
        """L'appel de description est court : c'est ce qui le rend fiable."""
        import inspect

        source = inspect.getsource(ResponseGenerator._decrire_image)
        assert "persona" not in source.lower()
        assert "_build_system_prompt" not in source

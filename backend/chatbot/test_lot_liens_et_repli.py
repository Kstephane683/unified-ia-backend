"""
Tests du lot du 24/09 : liens directs du site (chantier D) et marqueur
d'indisponibilité LLM (chantier C).

Le module liens_site est déterministe et sans base : les tests portent sur la
logique de déclenchement, les URLs composées et les garde-fous (site_url
absent, jamais lever, volume borné).
"""

import pytest

from backend.chatbot import liens_site


class TestCatalogue:
    def test_le_catalogue_ne_reference_que_des_pages_du_gabarit(self):
        """Aucun lien mort : les chemins existent dans le gabarit eperformance
        (vérifié contre site-eperformance/ au 24/09)."""
        pages_gabarit = {
            "diagnostic_eperformance.html",
            "ia.html",
            "site-web.html",
            "automatisation.html",
            "formation.html",
            "ebook.html",
        }
        for item in liens_site.CATALOGUE:
            assert item["chemin"] in pages_gabarit, item["cle"]

    def test_chaque_entree_a_label_phrase_mots(self):
        for item in liens_site.CATALOGUE:
            assert item["label"] and item["phrase"], item["cle"]
            assert item["mots"] or item["intents"], item["cle"]


class TestLiensPour:
    def test_sans_site_url_aucun_lien(self):
        """Sans URL de tenant : liste vide — jamais de lien relatif (le widget
        vit dans une iframe, un chemin relatif pointerait le domaine du widget)."""
        assert liens_site.liens_pour(None, "je veux un diagnostic") == []
        assert liens_site.liens_pour("", "tarifs ?") == []

    def test_intention_d_achat_produit_le_diagnostic(self):
        liens = liens_site.liens_pour(
            "https://client-exemple.pro", "je veux acheter votre offre, c'est combien ?"
        )
        assert liens, "l'achat doit produire au moins un lien"
        cles = [l["url"] for l in liens]
        assert any(u.endswith("diagnostic_eperformance.html") for u in cles)

    def test_mots_cles_page_produisent_le_lien(self):
        liens = liens_site.liens_pour(
            "https://client-exemple.pro", "vous faites les relances automatiques ?"
        )
        urls = [l["url"] for l in liens]
        assert any(u.endswith("automatisation.html") for u in urls)

    def test_intent_classifie_suffit(self):
        liens = liens_site.liens_pour(
            "https://client-exemple.pro", "bonjour", intent="diagnostic_request"
        )
        assert any(l["url"].endswith("diagnostic_eperformance.html") for l in liens)

    def test_url_absolue_avec_trailing_slash_gere(self):
        liens = liens_site.liens_pour("https://client-exemple.pro/", "diagnostic s'il vous plaît")
        assert liens[0]["url"].startswith("https://client-exemple.pro/")

    def test_volume_borne_a_trois(self):
        """Un message qui déclenche tout ne doit pas devenir un annuaire."""
        liens = liens_site.liens_pour(
            "https://client-exemple.pro",
            "diagnostic chatbot site web automatisation formation ebook prix",
        )
        assert len(liens) <= 3

    def test_message_vide_ne_leve_pas_et_ne_produit_rien(self):
        assert liens_site.liens_pour("https://client-exemple.pro", "") == []
        assert liens_site.liens_pour("https://client-exemple.pro", None) == []


class TestIaIndisponible:
    """Lot C : quand tous les fournisseurs échouent, la réponse est marquée."""

    @pytest.mark.asyncio
    async def test_generate_response_marque_le_repli(self, monkeypatch):
        from pathlib import Path

        from backend.chatbot.response_generator import ResponseGenerator

        gen = ResponseGenerator(
            agents_dir=Path(__file__).parent / "agents",
        )

        class _ClientHorsService:
            """Tous les fournisseurs échouent (crédit épuisé, 402, etc.)."""

            async def chat_completion(self, **kwargs):
                raise RuntimeError("402 insufficient balance")

        gen.llm_client = _ClientHorsService()

        texte, meta = await gen.generate_response(
            agent_key="sales-discovery-coach",
            agent_metadata={},
            message="bonjour",
            context={"site": {"site_name": "ePerformance"}},
            intent="greeting",
            intent_metadata={},
            image=None,
        )
        assert "indisponible" in texte.lower() or "conseiller" in texte.lower()
        assert meta["llm_provider"] == "fallback"

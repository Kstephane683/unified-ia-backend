"""
Tests des chantiers E, F, G du lot du 24/09 :
- E : connaissance du site du tenant (extraction, recherche, garde-fous) ;
- F : connaissances du propriétaire (reconstruire, chercher, invalider) ;
- G : instructions sectorielles (source canonique noyau, ton documenté).

Aucun de ces tests n'appelle le réseau : les pages sont des HTML de test.
"""

from pathlib import Path

from backend.chatbot import (
    connaissance_site,
    connaissances,
    instructions_sectorielles,
)

# ============================================================
# G — instructions sectorielles
# ============================================================


class TestInstructionsSectorielles:
    def test_fichier_canonique_present_et_peuple(self):
        donnees = instructions_sectorielles.charger()
        assert len(donnees) >= 12, "12 secteurs clients attendus (blog/email exclus)"
        assert "restauration" in donnees and "immobilier" in donnees

    def test_bloc_restauration_porte_intention_et_faq_canoniques(self):
        bloc = instructions_sectorielles.bloc_instructions("restauration")
        assert bloc is not None
        assert "Restauration" in bloc
        assert "réservation" in bloc  # faq_themes de sectors.py (canonique)
        assert "Ton de conversation" in bloc  # décision produit documentée
        # l'intention canonique du noyau, mot pour mot en préfixe
        assert "Donner faim et lever le doute pratique" in bloc

    def test_secteur_inconnu_ne_produit_rien(self):
        """Un secteur non déclaré ne produit JAMAIS d'invention générique."""
        assert instructions_sectorielles.bloc_instructions("astrologie") is None
        assert instructions_sectorielles.bloc_instructions("") is None
        assert instructions_sectorielles.bloc_instructions(None) is None

    def test_tons_couverts_sur_les_secteurs_clients(self):
        donnees = instructions_sectorielles.charger()
        manquants = [s for s in donnees if s not in instructions_sectorielles.TONS]
        assert manquants == [], f"ton manquant pour : {manquants}"


# ============================================================
# E — connaissance du site du tenant
# ============================================================

PAGE_TEST = """
<html><head><title>Diagnostic gratuit</title></head><body>
<header>Accueil Blog Contact</header>
<main><h1>Faites votre diagnostic</h1>
<p>Le diagnostic analyse votre visibilité locale, votre site et vos pratiques
commerciales. Vous recevez le rapport sous 48 heures, gratuit.</p></main>
</body></html>
"""


class TestConnaissanceSite:
    def test_extraction_texte_sans_balises_ni_script(self):
        texte = connaissance_site._extraire_texte(PAGE_TEST)
        assert texte is not None
        assert "diagnostic" in texte.lower()
        assert "<main>" not in texte and "<p>" not in texte and "<h1>" not in texte

    def test_titre_extrait_du_title(self):
        assert connaissance_site._titre_page(PAGE_TEST, "x.html") == "Diagnostic gratuit"

    def test_recherche_trouve_la_page_pertinente(self):
        pages = [{"url": "https://x.pro/", "titre": "Diagnostic gratuit", "texte": connaissance_site._extraire_texte(PAGE_TEST)}]
        resultats = connaissance_site._rechercher(pages, "le diagnostic analyse la visibilité locale ?")
        assert resultats and resultats[0]["url"] == "https://x.pro/"

    def test_recherche_insuree_ne_produit_rien(self):
        pages = [{"url": "https://x.pro/", "titre": "Diagnostic gratuit", "texte": "visibilité locale rapport"}]
        assert connaissance_site._rechercher(pages, "recette de gâteau au chocolat") == []

    def test_enrichir_contexte_sans_site_url_ne_leve_pas(self):
        assert connaissance_site.enrichir_contexte("diagnostic", None) is None
        assert connaissance_site.enrichir_contexte("", "https://x.pro") is None

    def test_etat_index_lisible(self):
        etat = connaissance_site.etat_index("https://jamais-charge.pro")
        assert etat["charge"] is False


# ============================================================
# F — connaissances du propriétaire
# ============================================================


class TestConnaissancesProprietaire:
    def setup_method(self):
        connaissances.invalider()

    def test_qr_trouvee_par_question_reformulee(self):
        connaissances.reconstruire(
            "site_test",
            [{"id": 1, "type": "qr", "question": "Livrez-vous à Abidjan ?", "reponse": "Oui, sous 24 h.", "actif": True}],
        )
        resultats = connaissances.chercher("site_test", "Vous livrez à Abidjan ou pas ?")
        assert resultats and resultats[0]["reponse"] == "Oui, sous 24 h."

    def test_inactif_ne_repond_pas(self):
        connaissances.reconstruire(
            "site_test",
            [{"id": 1, "type": "qr", "question": "Livrez-vous à Abidjan ?", "reponse": "Oui, sous 24 h.", "actif": False}],
        )
        assert connaissances.chercher("site_test", "livrez-vous à Abidjan ?") == []

    def test_invalidation_efface_l_index(self):
        connaissances.reconstruire(
            "site_x",
            [{"id": 1, "type": "qr", "question": "Quels horaires ?", "reponse": "9h-18h", "actif": True}],
        )
        assert connaissances.chercher("site_x", "quels horaires ?")
        connaissances.invalider("site_x")
        assert connaissances.chercher("site_x", "quels horaires ?") == []

    def test_qr_incomplete_rejetee_a_la_construction(self):
        connaissances.reconstruire(
            "site_y",
            [{"id": 1, "type": "qr", "question": "Seulement une question", "reponse": "", "actif": True}],
        )
        assert connaissances.chercher("site_y", "seulement une question") == []

    def test_document_texte_repond_avec_2_tokens_commun(self):
        connaissances.reconstruire(
            "site_z",
            [{"id": 2, "type": "texte", "contenu": "Nos formations IA se déroulent en présentiel à Abidjan, avec certificat.", "actif": True}],
        )
        resultats = connaissances.chercher("site_z", "les formations ont un certificat ?")
        assert resultats

    def test_message_vide_ne_leve_pas(self):
        assert connaissances.chercher("site_vide", "") == []


# ============================================================
# G — le bloc sectoriel est branché dans le prompt (intégration)
# ============================================================


class TestBlocDansLePrompt:
    def test_prompt_porte_le_bloc_sectoriel_pour_un_site_declare(self):
        from backend.chatbot.response_generator import ResponseGenerator

        gen = ResponseGenerator(agents_dir=Path(__file__).parent / "agents")
        prompt = gen._build_system_prompt(
            agent_persona="Tu es Mia.",
            context={"site": {"site_name": "Chez Amina", "sector": "restauration"}},
            intent="greeting",
            agent_key="sales-discovery-coach",
        )
        assert "SECTEUR DU SITE" in prompt
        assert "réservation" in prompt

    def test_prompt_sans_secteur_rest_identique(self):
        from backend.chatbot.response_generator import ResponseGenerator

        gen = ResponseGenerator(agents_dir=Path(__file__).parent / "agents")
        prompt = gen._build_system_prompt(
            agent_persona="Tu es Mia.",
            context={"site": {"site_name": "Neutre"}},
            intent="greeting",
            agent_key="sales-discovery-coach",
        )
        assert "SECTEUR DU SITE" not in prompt

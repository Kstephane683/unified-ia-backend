#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests de la tâche 6.8 — recherche dans le contenu du blog.

Couvre, SANS RÉSEAU et SANS BASE DE DONNÉES :
  · le classement BM25F sur un corpus construit de toutes pièces ;
  · les cas de dégradation : requête vide, requête absurde, index absent,
    schéma d'index changé côté blog ;
  · la mémoïsation : l'index n'est pas reconstruit à chaque appel ;
  · la non-intrusivité : l'enrichissement de la conversation ne bloque jamais
    et ne lève jamais, même quand tout échoue ;
  · l'extraction du texte d'une page d'article ;
  · le bloc de prompt : présent quand il y a des articles, VIDE sinon.

Exécution :
    cd /home/ballo/OX6A/unified-ia-backend
    python3 -m pytest backend/chatbot/test_tache_6_8_recherche_blog.py -q
"""
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))

from backend.chatbot import blog_search as bs  # noqa: E402
from backend.chatbot.response_generator import ResponseGenerator  # noqa: E402

AGENTS_DIR = Path(__file__).resolve().parent / "agents"


# ---------------------------------------------------------------- fabriques

def article(slug, titre, description="", tags=None, corps="", date="2026-09-15T09:00:00+00:00"):
    return bs.Article(
        slug=slug,
        titre=titre,
        description=description,
        url=f"https://blog.eperformance.pro/articles/{slug}/",
        collection="ia-generative",
        collection_titre="IA générative",
        date=date,
        tags=tags or [],
        corps=corps,
    )


def corps_avec(termes_repetes, remplissage="information"):
    """Corps d'article contenant les termes voulus, noyés dans du texte neutre."""
    return " ".join(list(termes_repetes) + [remplissage] * 400)


@pytest.fixture
def corpus():
    """Trois articles dont les sujets ne se recouvrent pas."""
    return [
        article(
            "calculer-cac-cote-ivoire",
            "Calculer son vrai CAC en Côte d'Ivoire : le guide complet",
            "Le coût d'acquisition client inclut la publicité, les outils et le temps.",
            ["CAC", "coût d'acquisition", "Côte d'Ivoire"],
            corps_avec(["cac", "acquisition", "client", "cout", "budget", "publicite"]),
            date="2026-09-16T09:00:00+00:00",
        ),
        article(
            "ia-service-client-nuit",
            "IA et service client : répondre la nuit sans recruter",
            "Les trois niveaux d'automatisation du service client et le calcul qui tranche.",
            ["ia service client pme", "chatbot whatsapp", "support automatique"],
            corps_avec(["service", "client", "nuit", "repondre", "automatisation", "recruter"]),
            date="2026-09-18T12:00:00+00:00",
        ),
        article(
            "seo-local-abidjan-guide",
            "SEO local à Abidjan : apparaître sur Google quand vos clients cherchent",
            "46 % des recherches Google ont une intention locale.",
            ["SEO local Abidjan", "Google Business Profile"],
            corps_avec(["seo", "google", "abidjan", "local", "recherche", "visibilite"]),
            date="2026-09-30T09:00:00+00:00",
        ),
    ]


@pytest.fixture
def index(corpus):
    return bs.IndexBlog(corpus)


# ============================================================
# 1. CLASSEMENT
# ============================================================


class TestClassement:
    def test_trouve_l_article_du_bon_sujet(self, index):
        """Le sujet est désigné par une question, pas par le titre de l'article."""
        resultats = index.rechercher("combien me coute un nouveau client")
        assert resultats, "la recherche doit trouver au moins un article"
        assert resultats[0].article.slug == "calculer-cac-cote-ivoire"

    def test_le_titre_pese_plus_que_le_corps(self, index):
        """Un mot du titre doit battre un mot noyé dans 400 mots de corps."""
        resultats = index.rechercher("seo local abidjan")
        assert resultats[0].article.slug == "seo-local-abidjan-guide"

    def test_les_accents_ne_changent_rien(self, index):
        avec = index.rechercher("cout acquisition")
        sans = index.rechercher("coût acquisition")
        assert [r.article.slug for r in avec] == [r.article.slug for r in sans]

    def test_ordre_stable_entre_deux_appels(self, index):
        premier = [r.article.slug for r in index.rechercher("client")]
        second = [r.article.slug for r in index.rechercher("client")]
        assert premier == second

    def test_la_couverture_est_exposee(self, index):
        resultats = index.rechercher("seo local abidjan")
        assert resultats[0].couverture == 1.0

    def test_limite_respectee(self, index):
        assert len(index.rechercher("client", limite=1)) == 1
        assert len(index.rechercher("client", limite=100)) <= bs.RESULTATS_MAX

    def test_les_mots_vides_ne_font_pas_trouver_tout(self, index):
        """« le la de et » ne doit ramener aucun article."""
        assert index.rechercher("le la de et du") == []


# ============================================================
# 2. REQUÊTES VIDES, ABSURDES, HORS SUJET
# ============================================================


class TestRequetesDegradees:
    def test_requete_vide_repond_proprement(self):
        """Jamais d'exception, jamais de 500 : un message clair et zéro résultat."""
        reponse = bs.rechercher("")
        assert reponse["resultats"] == []
        assert reponse["total"] == 0
        assert "message" in reponse

    def test_requete_espaces_repond_proprement(self):
        reponse = bs.rechercher("     ")
        assert reponse["resultats"] == []
        assert "message" in reponse

    def test_requete_absurde_ne_retient_rien_de_pertinent(self, monkeypatch, corpus):
        """Le cas qui compte : ne PAS injecter d'article hors sujet dans Mia."""
        monkeypatch.setattr(bs, "_chargeur", _ChargeurFige(bs.IndexBlog(corpus)))
        reponse = bs.rechercher("zorglub qwerty xyzzy")
        assert [r for r in reponse["resultats"] if r["pertinent"]] == []

    def test_la_reponse_porte_toujours_la_forme_attendue(self, monkeypatch, corpus):
        monkeypatch.setattr(bs, "_chargeur", _ChargeurFige(bs.IndexBlog(corpus)))
        for requete in ("", "   ", "a", "zorglub", "comment calculer mon cac"):
            reponse = bs.rechercher(requete)
            assert set(reponse) >= {"requete", "resultats", "total", "index"}
            assert isinstance(reponse["resultats"], list)


# ============================================================
# 3. INDEX ABSENT OU SCHÉMA CHANGÉ (risque nommé au contrat)
# ============================================================


class _ChargeurFige(bs.ChargeurIndexBlog):
    """Chargeur dont l'index est déjà construit — pour les tests hors réseau."""

    def __init__(self, index):
        super().__init__()
        self._index = index
        self._charge_le = time.time()
        self._genere_le = "2026-09-18T10:40:16Z"
        self._source_corps = "figé (test)"

    def declencher(self):  # aucun rafraîchissement en test
        return None

    def attendre_pret(self, secondes):
        return True


class _ChargeurImpossible(bs.ChargeurIndexBlog):
    """Chargeur dont toutes les sources échouent — le cas « blog injoignable »."""

    def _lire_index(self):
        return None, "aucune source disponible (test)"

    def declencher(self):
        return None

    def attendre_pret(self, secondes):
        return False


class TestDegradation:
    def test_index_indisponible_ne_leve_pas(self, monkeypatch):
        monkeypatch.setattr(bs, "_chargeur", _ChargeurImpossible())
        reponse = bs.rechercher("calculer mon cac")
        assert reponse["resultats"] == []
        assert reponse["index"]["disponible"] is False
        assert "message" in reponse

    def test_index_indisponible_bloque_le_moins_possible(self, monkeypatch):
        monkeypatch.setattr(bs, "_chargeur", _ChargeurImpossible())
        debut = time.time()
        bs.rechercher("n'importe quoi")
        assert (time.time() - debut) < 1.0, "une source morte ne doit pas faire attendre"

    def test_enrichir_contexte_renvoie_none_sans_index(self, monkeypatch):
        monkeypatch.setattr(bs, "_chargeur", _ChargeurImpossible())
        assert bs.enrichir_contexte("comment calculer mon cac") is None

    def test_schema_d_index_changé_est_refuse_et_dit(self):
        """Le blog peut changer son schéma : on doit le DIRE, pas échouer en silence."""
        for mauvais, motif in (
            ([], "objet JSON"),
            ({}, "articles"),
            ({"articles": "pas une liste"}, "articles"),
            ({"articles": [{"description": "sans slug ni titre"}]}, "slug"),
        ):
            valide, raison = bs._valider_index(mauvais)
            assert valide is False
            assert motif in raison

    def test_index_valide_est_accepte(self):
        valide, _ = bs._valider_index(
            {"articles": [{"slug": "a", "titre": "Un titre"}]}
        )
        assert valide is True

    def test_construction_avec_schema_invalide_conserve_l_index_precedent(
        self, monkeypatch, corpus
    ):
        chargeur = bs.ChargeurIndexBlog()
        chargeur._index = bs.IndexBlog(corpus)
        monkeypatch.setattr(
            chargeur, "_lire_index", lambda: ({"articles": "cassé"}, "test")
        )
        resultat = chargeur.construire()
        assert resultat is chargeur._index, "l'index précédent ne doit pas être perdu"
        assert "schéma" in (chargeur.etat()["derniere_erreur"] or "")


# ============================================================
# 4. MÉMOÏSATION
# ============================================================


class TestMemoisation:
    def test_l_index_est_construit_une_seule_fois(self, monkeypatch, corpus):
        chargeur = bs.ChargeurIndexBlog()
        appels = {"n": 0}

        def fausse_lecture():
            appels["n"] += 1
            return {
                "genere_le": "2026-09-18T10:40:16Z",
                "articles": [
                    {
                        "slug": a.slug,
                        "titre": a.titre,
                        "description": a.description,
                        "url": a.url,
                        "tags": a.tags,
                        "date": a.date,
                    }
                    for a in corpus
                ],
            }, "test"

        monkeypatch.setattr(chargeur, "_lire_index", fausse_lecture)
        monkeypatch.setattr(chargeur, "_enrichir_avec_les_corps", lambda articles: 0)
        monkeypatch.setattr(bs, "_chargeur", chargeur)

        for _ in range(5):
            bs.rechercher("client")
        assert appels["n"] == 1, "l'index ne doit pas être relu à chaque recherche"

    def test_la_date_de_generation_est_exposee(self, monkeypatch, corpus):
        monkeypatch.setattr(bs, "_chargeur", _ChargeurFige(bs.IndexBlog(corpus)))
        reponse = bs.rechercher("client")
        assert reponse["index"]["genere_le"] == "2026-09-18T10:40:16Z"

    def test_l_etat_porte_la_couverture_du_corps(self, monkeypatch, corpus):
        monkeypatch.setattr(bs, "_chargeur", _ChargeurFige(bs.IndexBlog(corpus)))
        etat = bs.rechercher("client")["index"]
        assert etat["articles_indexes"] == 3
        assert etat["articles_avec_corps"] == 3

    def test_construction_en_fond_ne_bloque_pas_l_appelant(self, monkeypatch):
        """Processus froid : l'appel revient tout de suite, l'index se bâtit après."""
        chargeur = bs.ChargeurIndexBlog()

        def lecture_lente():
            time.sleep(0.3)
            return None, "lent (test)"

        monkeypatch.setattr(chargeur, "_lire_index", lecture_lente)
        monkeypatch.setattr(bs, "_chargeur", chargeur)

        debut = time.time()
        reponse = bs.rechercher("client")
        duree = time.time() - debut
        assert duree < 0.2, "le premier appel ne doit pas attendre la construction"
        assert reponse["index"]["disponible"] is False


# ============================================================
# 5. EXTRACTION DU TEXTE D'UNE PAGE D'ARTICLE
# ============================================================

PAGE_ARTICLE = """<!doctype html><html><head><title>Un article</title></head><body>
<header><nav>Accueil Blog Contact</nav></header>
<div class="article-hero"><h1>Un article</h1></div>
<div class="article-body container-reading">
  <p>La plupart des entrepreneurs posent la bonne question.</p>
  <h2>Le calcul</h2>
  <p>Additionnez le budget publicitaire, les outils et le temps passé.</p>
</div>
<footer><p>ePerformance 2026</p></footer>
<div class="consent"><button>Retour</button><button>Enregistrer mes choix</button></div>
<a href="/autre"><div class="related">À lire aussi : un autre article</div></a>
</body></html>"""


class TestExtraction:
    def test_extrait_le_corps_sans_le_menu_ni_le_pied(self):
        texte = bs.extraire_texte_article(PAGE_ARTICLE)
        assert "entrepreneurs" in texte
        assert "budget publicitaire" in texte
        # Ni navigation, ni pied de page, ni bandeau de consentement.
        assert "Accueil" not in texte
        assert "ePerformance 2026" not in texte
        assert "Enregistrer mes choix" not in texte

    def test_ne_laisse_pas_fuir_le_texte_de_la_balise(self):
        """Défaut constaté puis corrigé : `class="article-body"` dans le texte."""
        texte = bs.extraire_texte_article(PAGE_ARTICLE)
        assert 'class="' not in texte
        assert "container-reading" not in texte
        assert not texte.lstrip().startswith("article-body")

    def test_page_sans_repere_connu_utilise_toute_la_page(self):
        texte = bs.extraire_texte_article("<html><body><p>Un texte court.</p></body></html>")
        assert "Un texte court" in texte

    def test_html_vide_ou_invalide_ne_leve_pas(self):
        assert bs.extraire_texte_article("") == ""
        assert isinstance(bs.extraire_texte_article("<html><body>"), str)
        assert isinstance(bs.extraire_texte_article(None), str)


# ============================================================
# 6. NON-INTRUSIVITÉ DANS LA CONVERSATION
# ============================================================


class TestNonIntrusivite:
    def _generateur(self):
        return ResponseGenerator(agents_dir=AGENTS_DIR)

    def test_le_bloc_prompt_est_vide_sans_article(self):
        generateur = self._generateur()
        assert generateur._format_blog_context({}) == ""
        assert generateur._format_blog_context({"blog": None}) == ""
        assert generateur._format_blog_context({"blog": {"articles": []}}) == ""

    def test_le_bloc_prompt_est_present_avec_articles(self):
        generateur = self._generateur()
        bloc = generateur._format_blog_context(
            {
                "blog": {
                    "articles": [
                        {
                            "slug": "seo-local-abidjan-guide",
                            "titre": "SEO local à Abidjan",
                            "url": "https://blog.eperformance.pro/articles/seo-local-abidjan-guide/",
                            "date": "2026-09-30T09:00:00+00:00",
                            "extrait": "Quand un client cherche un restaurant.",
                        }
                    ]
                }
            }
        )
        assert "SEO local à Abidjan" in bloc
        assert "https://blog.eperformance.pro/articles/seo-local-abidjan-guide/" in bloc
        # Le bloc doit dire explicitement qu'on peut l'ignorer.
        assert "ignore" in bloc.lower()

    def test_le_bloc_prompt_ne_nomme_aucun_agent(self):
        generateur = self._generateur()
        bloc = generateur._format_blog_context(
            {
                "blog": {
                    "articles": [
                        {
                            "slug": "x",
                            "titre": "Un article",
                            "url": "https://exemple.test/",
                            "extrait": "Texte.",
                        }
                    ]
                }
            }
        )
        for interdit in ("agent", "persona", "sales-", "routing", "prompt"):
            assert interdit not in bloc.lower().replace("interlocuteurs", "")

    def test_l_enrichissement_absorbe_les_erreurs(self, monkeypatch):
        """Si la recherche explose, l'enrichissement renvoie None — point."""

        def explose(*args, **kwargs):
            raise RuntimeError("panne simulée")

        monkeypatch.setattr(bs, "rechercher", explose)
        assert bs.enrichir_contexte("calculer mon cac") is None

    def test_desactivation_par_variable_d_environnement(self, monkeypatch):
        monkeypatch.setattr(bs, "ACTIF", False)
        reponse = bs.rechercher("calculer mon cac")
        assert reponse["resultats"] == []
        assert reponse["index"]["disponible"] is False
        assert bs.enrichir_contexte("calculer mon cac") is None

    def test_le_bloc_prompt_ne_contient_que_des_articles_pertinents(self, monkeypatch, corpus):
        monkeypatch.setattr(bs, "_chargeur", _ChargeurFige(bs.IndexBlog(corpus)))
        bloc = bs.enrichir_contexte("comment calculer mon cout d acquisition client")
        assert bloc is not None
        assert bloc["articles"], "un bloc sans article ne doit pas être produit"
        assert bloc["articles"][0]["slug"] == "calculer-cac-cote-ivoire"

    def test_l_extrait_est_borne(self, corpus):
        for a in corpus:
            assert len(a.extrait()) <= bs.LONGUEUR_EXTRAIT + 10

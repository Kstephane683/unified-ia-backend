"""
Recherche dans le contenu du blog ePerformance — tâche 6.8.

CE QUE FAIT CE MODULE
---------------------
Il rend le contenu du blog interrogeable par Mia : étant donné une question de
visiteur, il renvoie les articles les plus proches, avec leur URL publique.
Deux usages :
  1. `GET /api/chatbot/search` — recherche explicite (onglet Aide du widget) ;
  2. enrichissement du contexte de `POST /api/chatbot/message` — Mia peut
     s'appuyer sur un article existant plutôt que de reformuler une réponse.

DÉCISION D'ARCHITECTURE — MOTEUR DE RECHERCHE
---------------------------------------------
Ce module utilise **BM25 en Python pur**. Ce n'est pas un pis-aller : c'est un
choix dicté par une mesure.

POURQUOI PAS DES EMBEDDINGS (mesuré le 2026-09-18, sorties dans le rapport) :
  · `OPENAI_API_KEY` est **absent** partout — `api_keys.openai` vaut `''` dans
    `config_ia.json`, et `railway variables` (production) ne liste AUCUNE
    variable OpenAI. Un appel réel à `https://api.openai.com/v1/embeddings`
    sans clé répond **HTTP 401**.
  · DeepSeek, qui porte la conversation, **n'expose pas** d'endpoint
    d'embeddings : `POST https://api.deepseek.com/v1/embeddings` → **HTTP 404**
    (avec une clé valide, vérifiée en parallèle sur `chat/completions` → 200).
  · La passerelle du projet (`aiapiflow.com/v1/embeddings`) répond
    **HTTP 404** « Embeddings API is not supported for this platform ».

Aucun fournisseur d'embeddings n'est donc joignable, et en ajouter un
imposerait une nouvelle dépendance, une nouvelle clé et un nouveau coût par
requête. BM25 est un moteur de recherche lexical de référence (utilisé par
Lucene, Elasticsearch, SQLite FTS5) : sur un corpus d'articles en français, il
trouve les articles pertinents sans dépendance et sans coût. La qualité est
**mesurée** (`scripts/benchmark_recherche_blog.py`), pas supposée.

COMMENT LE CORPUS EST OBTENU (et pourquoi c'est le vrai contenu)
----------------------------------------------------------------
`chatbot-index.json` ne contient que les articles **publiés** (8 le 2026-09-18),
et de chacun il ne donne que le titre, la description et les tags. Indexer
cela seul aurait produit une recherche qui « a l'air de marcher » et qui ne
trouve rien : 30 mots par article, c'est le résumé d'un résumé.

Or la page publique de chaque article publié contient **tout le texte**
(≈ 2 300 mots mesurés sur le premier article). C'est la même source, publique,
que celle du widget : on récupère donc, pour chaque article publié :
  · sa fiche depuis `chatbot-index.json` (titre, description, tags, date, URL) ;
  · son corps depuis son URL publique, balises retirées.

Règle de non-fuite respectée : on ne lit QUE les articles présents dans
l'index, donc uniquement `published: true` sans `noindex`. Les 73 articles en
avant-première de `_schedule.json` ne sont jamais lus ni indexés. C'est la
même garantie que celle du générateur d'index du blog.

FRAGILITÉ ASSUMÉE ET CONTRÔLÉE
------------------------------
Le format d'`index.json` et la structure des pages d'articles appartiennent au
dépôt du blog. Si l'un des deux change, la recherche se dégraderait **sans
erreur visible** — c'est le risque nommé dans `COORDINATION-AGENTS.md`. Trois
parades : la validation de forme à la lecture (`_valider_index`), un repli
automatique sur titre + description si le corps n'est pas extractible, et une
sonde de couverture exposée dans la réponse (`articles_avec_corps`).
"""
from __future__ import annotations

import html
import json
import logging
import math
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION (surchargeable par variables d'environnement)
# ============================================================

#: Index public du blog — produit par `blog-eperformance/_build/generer_index_chatbot.py`
INDEX_URL = os.getenv(
    "BLOG_INDEX_URL", "https://blog.eperformance.pro/chatbot-index.json"
)
#: Repli local (poste de développement) : chemin du fichier d'index du blog.
INDEX_PATH = os.getenv("BLOG_INDEX_PATH", "")
#: Cache disque : sert quand le réseau est indisponible (Railway redémarre souvent).
CACHE_PATH = os.getenv(
    "BLOG_INDEX_CACHE",
    str(Path(__file__).resolve().parent / "data" / "blog_index_cache.json"),
)
#: Durée de validité d'un index avant reconstruction (le blog publie 5 articles/jour).
TTL_SECONDES = int(os.getenv("BLOG_INDEX_TTL_SECONDES", str(6 * 3600)))
#: Délai maximal de lecture du corps d'un article (secondes).
DELAI_FETCH = float(os.getenv("BLOG_FETCH_TIMEOUT", "8"))
#: Nombre maximal d'articles dont on récupère le corps (garde la construction bornée).
MAX_ARTICLES_CORPS = int(os.getenv("BLOG_FETCH_MAX_ARTICLES", "40"))
#: Budget total de la récupération des corps (secondes) — au-delà, on s'arrête
#: avec ce qu'on a : mieux vaut un index partiel qu'un démarrage bloqué.
BUDGET_CORPS = float(os.getenv("BLOG_FETCH_BUDGET", "25"))
#: Interrupteur général : `0` désactive la recherche (Mia répond normalement).
ACTIF = os.getenv("BLOG_SEARCH_ENABLED", "1").strip().lower() not in ("0", "false", "non", "")
#: Nombre de résultats par défaut et maximum.
RESULTATS_DEFAUT = int(os.getenv("BLOG_SEARCH_LIMIT", "5"))
RESULTATS_MAX = int(os.getenv("BLOG_SEARCH_LIMIT_MAX", "20"))
#: Seuil de pertinence pour ENRICHIR LA CONVERSATION (jamais pour l'endpoint :
#: l'endpoint renvoie ce qu'il a, c'est au widget de décider quoi afficher).
#: Couverture minimale : part des mots de la question retrouvés dans l'article.
SEUIL_COUVERTURE = float(os.getenv("BLOG_SEARCH_SEUIL_COUVERTURE", "0.5"))
#: Score BM25F minimal. La couverture seule ne suffit pas : sur la question
#: « réservation d'un billet d'avion pour Tokyo », l'article CAC obtient une
#: couverture de 0,50 parce qu'il contient la métaphore « le prix d'un billet
#: d'avion » — deux mots rares, donc bien notés, mais hors sujet.
#: VALEURS MESURÉES le 2026-09-18 sur les 8 articles publiés (banc
#: `scripts/benchmark_recherche_blog.py`) : vrais positifs de 6,29 à 36,2 ;
#: faux positifs à 2,46 et 0,26. Le seuil de 4,0 est au milieu des deux
#: populations, avec ≈ 1,6× de marge de chaque côté. À revoir quand le corpus
#: dépassera la quarantaine d'articles : l'IDF croît avec le nombre de
#: documents, donc les scores augmentent — le seuil devra être remonté d'autant.
SEUIL_SCORE = float(os.getenv("BLOG_SEARCH_SEUIL_SCORE", "4.0"))
#: Nombre d'articles injectés au maximum dans le prompt (coût en tokens).
MAX_ARTICLES_CONTEXTE = int(os.getenv("BLOG_CONTEXT_MAX_ARTICLES", "3"))
#: Longueur maximale d'un extrait d'article injecté dans le prompt.
LONGUEUR_EXTRAIT = int(os.getenv("BLOG_CONTEXT_EXTRAIT", "600"))

# ============================================================
# PARAMÈTRES BM25 (valeurs usuelles de la littérature)
# ============================================================

K1 = 1.5  # saturation de la fréquence de terme
B = 0.75  # normalisation par la longueur du document

#: Champs indexés séparément (BM25F). Chaque champ a son propre IDF et sa
#: propre longueur moyenne : c'est indispensable ici, parce qu'un titre fait
#: 6 mots et un corps 2 300. Mélanger les deux dans un seul compteur — ce que
#: fait un BM25 plat — noie le signal du titre : mesuré sur « prix d'un site
#: internet », l'article « Site web professionnel à Abidjan » (le bon) sortait
#: **hors du top 3** parce que « site » y apparaît 65 fois dans le corps et que
#: cette masse écrasait sa présence dans le titre. Avec un IDF par champ, le
#: titre redevient discriminant.
CHAMPS = ("titre", "tags", "description", "corps")

#: Pondération des champs dans le score final.
POIDS_CHAMPS = {
    "titre": 3.0,
    "tags": 2.0,
    "description": 1.5,
    "corps": 1.0,
}

#: Part du score qui ne dépend PAS de la couverture (voir `_score_final`).
PLANCHER_COUVERTURE = 0.35

# ============================================================
# MOTS-VIDES FRANÇAIS
# ============================================================
# Volontairement courts et sans dépendance : les mots-outils du français qui
# n'apportent aucun signal de recherche. Un mot vide conservé ferait gagner
# tous les articles à égalité ; un mot vide retiré à tort coûte peu.
MOTS_VIDES = frozenset("""
a afin ai aie ainsi alors au aucun aucune aujourd auquel aussi autant autre autres aux avais avait
avant avec avoir ayant bien car ce ceci cela celle celles celui cependant certain certaine ces cet
cette ceux chaque chez ci comme comment dans de dedans dehors deja depuis des desquels dessous dessus
deux du duquel durant elle elles en encor encore entre est et etaient etais etait etant ete etes etre
eu eux fait faire fois font hors ici il ils je jusqu jusque l la laquelle le lequel les lesquels leur
leurs lors lui ma mais malgre me meme memes mes mien moi moins mon ne ni non nos notre nous on ont ou
oui par parce parmi pas pendant peu peut plus plusieurs pour pourquoi pourtant pouvais pouvait pres
puis puisque qu quand que quel quelle quelles quels quelque quelques qui quoi sa sans se selon sera
serai serais serait serions serons seront ses si sien soit son sont sous souvent suis sur ta tandis
tant te tel telle telles tels tes toi ton tous tout toute toutes tres trop tu un une vers voici voila
vos votre vous vu y ont ete etre n y d l s c j m t qu
combien faire veux veut voulez peux peut pouvez pouvons dois doit devez devons faut donc alors
maintenant jamais toujours rien personne chose choses truc trucs
""".split())


def _sans_accent(texte: str) -> str:
    """« générative » → « generative » : la recherche ne doit pas dépendre des accents."""
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c))


#: Tokens alphanumériques de 2 caractères ou plus. Les chiffres sont conservés
#: (« 2026 », « 46 % », « 7 critères » sont des requêtes réelles du blog).
RE_TOKEN = re.compile(r"[a-z0-9]{2,}")


def _racine(mot: str) -> str:
    """Racinisation minimale et prudente du français.

    Le pluriel est la seule flexion qui change vraiment le rappel ici
    (« clients » vs « client », « chiffres » vs « chiffre »). On ne touche ni
    aux verbes ni aux suffixes ambigus : une racinisation agressive ferait
    collisionner « clientèle » et « client » — ce qui est justement ici un
    rapprochement souhaitable, mais aussi « coût » et « couture ». On s'en tient
    au pluriel, mesuré comme le gain le plus net sans perte.
    """
    if len(mot) > 4 and mot.endswith("s") and not mot.endswith(("ss", "us", "is")):
        return mot[:-1]
    if len(mot) > 5 and mot.endswith("x"):
        return mot[:-1]
    return mot


def _variantes(mot: str) -> List[str]:
    """Formes supplémentaires d'un mot, pour rapprocher les flexions du français.

    POURQUOI (mesuré). « combien coute un client » ne trouvait pas l'article du
    CAC : le visiteur écrit « coute », l'article dit « coût » — deux tokens
    différents, donc aucun rapprochement. C'est une question fréquente, le
    défaut était réel.

    COMMENT, et pourquoi c'est sans risque. Les variantes sont produites des
    DEUX côtés — dans les documents ET dans la requête. Une variante ne peut
    donc jamais faire perdre une correspondance : elle ne peut qu'en ajouter.
    Le seuil de 4 caractères évite les variantes trop courtes et trop
    générales (« site » → « sit » est refusé, ce qui serait du bruit pur).

    Ce n'est pas une racinisation linguistique complète, et c'est volontaire :
    une racinisation agressive ferait collisionner des mots sans rapport
    (« coût » et « coutume »), ce qui coûterait plus qu'elle ne rapporte.
    """
    variantes: List[str] = []
    if len(mot) >= 5:
        if mot.endswith(("er", "ez")):
            radical = mot[:-2]  # calculer -> calcul, couter -> cout
        elif mot.endswith("ent"):
            radical = mot[:-3]  # calculent -> calcul
        elif mot.endswith(("e", "es")):
            radical = mot[:-2] if mot.endswith("es") else mot[:-1]  # coute -> cout
        else:
            radical = ""
        if len(radical) >= 4:
            variantes.append(radical)
    return variantes


def tokeniser(texte: str) -> List[str]:
    """Découpe un texte en tokens de recherche (sans accents, sans mots vides)."""
    if not texte:
        return []
    jetons: List[str] = []
    for mot in RE_TOKEN.findall(_sans_accent(texte).lower()):
        if mot in MOTS_VIDES:
            continue
        racine = _racine(mot)
        jetons.append(racine)
        jetons.extend(_variantes(racine))
    return jetons


# ============================================================
# EXTRACTION DU TEXTE D'UNE PAGE D'ARTICLE
# ============================================================

RE_TAGS = re.compile(r"<[^>]+>")
#: Blocs qui ne sont PAS de l'article : navigation, pied de page, bandeau de
#: consentement, scripts, styles. Mesuré sur les pages réelles : sans ce
#: retrait, le bandeau cookies (« Retour / Enregistrer mes choix ») se
#: retrouvait dans le texte de chaque article.
RE_BRUIT = re.compile(
    r"<(script|style|nav|header|footer|form|svg|noscript)\b[^>]*>.*?</\1>",
    re.S | re.I,
)
RE_BRUIT_VIDE = re.compile(
    r"<(script|style|svg|noscript|link|meta)\b[^>]*/?>", re.S | re.I
)
RE_CLASSE_BRUIT = re.compile(
    r'<(div|section|aside)\b[^>]*class="[^"]*'
    r'(consent|cookie|breadcrumb|nav|menu|footer|sidebar|related|share|cta-banner)'
    r'[^"]*"[^>]*>.*?</\1>',
    re.S | re.I,
)
#: Repères du corps de l'article dans les pages du blog. Le premier est celui
#: du générateur actuel (`_build/compose.py`) ; les suivants couvrent une
#: refonte raisonnable. Aucun n'est trouvé → on retombe sur la page entière.
REPRES_DEBUT = ('class="article-body', 'class="article-content', "<article")
REPRES_FIN = ("<footer", 'class="consent', "<footer", "article-footer")


def extraire_texte_article(page_html: str) -> str:
    """Texte de l'article depuis le HTML de sa page.

    Ne lève jamais : renvoie une chaîne vide si rien d'exploitable n'est trouvé,
    l'appelant retombe alors sur titre + description.
    """
    if not page_html:
        return ""
    try:
        source = page_html

        # 1. Délimiter le corps entre un repère de début et un repère de fin.
        debut = -1
        for repere in REPRES_DEBUT:
            position = source.find(repere)
            if position != -1:
                # Le repère est le début d'une balise : on démarre APRÈS son
                # `>`, sinon `class="article-body"` se retrouve dans le texte
                # extrait (constaté, corrigé).
                fermeture = source.find(">", position)
                debut = fermeture + 1 if fermeture != -1 else position
                break
        if debut != -1:
            fin = -1
            for repere in REPRES_FIN:
                fin = source.find(repere, debut)
                if fin != -1:
                    break
            source = source[debut: fin if fin != -1 else debut + 120_000]

        # 2. Retirer les blocs de bruit, puis les balises restantes.
        source = RE_BRUIT.sub(" ", source)
        source = RE_BRUIT_VIDE.sub(" ", source)
        source = RE_CLASSE_BRUIT.sub(" ", source)

        # 3. Un bloc `<details>` (FAQ des articles) porte sa réponse dans un
        #    enfant : après retrait des balises, le texte reste — c'est voulu,
        #    les questions fréquentes sont d'excellents résultats de recherche.
        texte = html.unescape(RE_TAGS.sub(" ", source))
        texte = re.sub(r"\s+", " ", texte).strip()
        return texte
    except Exception:  # pragma: no cover - filet de sécurité
        return ""


# ============================================================
# MODÈLE DE DONNÉES
# ============================================================


@dataclass
class Article:
    """Un article du blog, prêt pour la recherche."""

    slug: str
    titre: str
    description: str
    url: str
    collection: Optional[str] = None
    collection_titre: Optional[str] = None
    date: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    corps: str = ""
    #: Longueur pondérée (BM25) et fréquences de termes par champ.
    longueur: float = 0.0
    champs: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def a_un_corps(self) -> bool:
        return len(self.corps.split()) >= 80

    def extrait(self, longueur: int = LONGUEUR_EXTRAIT) -> str:
        """Extrait centré sur le début du corps (les articles ouvrent sur l'idée)."""
        if not self.corps:
            return self.description
        if len(self.corps) <= longueur:
            return self.corps
        coupe = self.corps[:longueur]
        # Ne pas trancher un mot en deux.
        if " " in coupe:
            coupe = coupe[: coupe.rfind(" ")]
        return coupe.rstrip() + " […]"

    def pour_api(self) -> Dict:
        """Forme publique — aucun champ interne, aucun nom d'agent."""
        return {
            "slug": self.slug,
            "titre": self.titre,
            "description": self.description,
            "url": self.url,
            "collection": self.collection,
            "collection_titre": self.collection_titre,
            "date": self.date,
            "tags": self.tags,
        }


@dataclass
class Resultat:
    """Un résultat de recherche, avec de quoi expliquer le classement."""

    article: Article
    score: float  # score de classement (BM25F pondéré par la couverture)
    couverture: float  # part des mots de la requête présents dans l'article
    termes_trouves: List[str]
    score_bm25: float = 0.0  # score BM25F brut, avant pondération par la couverture

    @property
    def pertinent(self) -> bool:
        """Le résultat mérite-t-il d'être injecté dans la conversation ?

        Deux conditions, toutes deux nécessaires :
          · au moins la moitié des mots de la question sont dans l'article
            (couverture) ;
          · le score BM25F dépasse un plancher mesuré (`SEUIL_SCORE`).

        POURQUOI PAS LA COUVERTURE SEULE. Elle est grossière sur les questions
        courtes : « mes visiteurs ne me contactent pas » ne produit que deux
        termes, donc un article qui n'en contient qu'un atteint déjà 0,50. Le
        score, lui, distingue un article qui parle du sujet d'un article qui
        mentionne un mot en passant.
        """
        return self.couverture >= SEUIL_COUVERTURE and self.score >= SEUIL_SCORE

    def pour_api(self) -> Dict:
        d = self.article.pour_api()
        d.update(
            {
                "score": round(self.score, 4),
                "couverture": round(self.couverture, 3),
                "termes_trouves": self.termes_trouves,
                "pertinent": self.pertinent,
            }
        )
        return d


# ============================================================
# INDEX BM25
# ============================================================


class IndexBlog:
    """Index BM25F d'un ensemble d'articles. Immuable une fois construit."""

    def __init__(self, articles: List[Article]):
        self.articles = articles
        #: {champ: {slug: Counter(terme -> fréquence)}}
        self._frequences: Dict[str, Dict[str, Dict[str, int]]] = {}
        #: {champ: {terme: nombre de documents le contenant}}
        self._df: Dict[str, Dict[str, int]] = {}
        #: {champ: longueur moyenne du champ}
        self._longueur_moyenne: Dict[str, float] = {}
        #: {champ: {slug: longueur}}
        self._longueurs: Dict[str, Dict[str, int]] = {}
        self._construire()

    # --- construction -------------------------------------------------
    def _construire(self) -> None:
        for champ in CHAMPS:
            self._frequences[champ] = {}
            self._df[champ] = {}
            self._longueurs[champ] = {}

        for article in self.articles:
            champs = {
                "titre": tokeniser(article.titre),
                "tags": tokeniser(" ".join(article.tags)),
                "description": tokeniser(article.description),
                "corps": tokeniser(article.corps),
            }
            article.champs = champs
            for champ in CHAMPS:
                jetons = champs.get(champ) or []
                compteur: Dict[str, int] = {}
                for jeton in jetons:
                    compteur[jeton] = compteur.get(jeton, 0) + 1
                self._frequences[champ][article.slug] = compteur
                self._longueurs[champ][article.slug] = len(jetons)
                for terme in compteur:
                    self._df[champ][terme] = self._df[champ].get(terme, 0) + 1

        for champ in CHAMPS:
            longueurs = list(self._longueurs[champ].values())
            self._longueur_moyenne[champ] = (
                sum(longueurs) / len(longueurs) if longueurs else 1.0
            ) or 1.0

        # Longueur pondérée : sert au calcul de couverture et à l'affichage.
        for article in self.articles:
            article.longueur = sum(len(article.champs.get(c) or []) for c in CHAMPS)

    # --- interrogation ------------------------------------------------
    @property
    def taille(self) -> int:
        return len(self.articles)

    @property
    def articles_avec_corps(self) -> int:
        return sum(1 for a in self.articles if a.a_un_corps)

    def _idf(self, champ: str, terme: str) -> float:
        """IDF de Robertson/Sparck Jones, calculé PAR CHAMP (forme lissée).

        Un terme courant dans le corps (« site ») reste discriminant s'il est
        rare dans les titres : c'est ce que la version par champ apporte.
        """
        n = self._df[champ].get(terme, 0)
        if n == 0:
            return 0.0
        return math.log(1.0 + (self.taille - n + 0.5) / (n + 0.5))

    def _score_bm25(self, article: Article, termes: List[str]) -> Tuple[float, List[str]]:
        """Score BM25F : somme, pondérée par champ, des scores de chaque terme."""
        total = 0.0
        trouves: List[str] = []

        for terme in termes:
            score_terme = 0.0
            for champ in CHAMPS:
                tf = self._frequences[champ].get(article.slug, {}).get(terme, 0)
                if tf <= 0:
                    continue
                idf = self._idf(champ, terme)
                if idf <= 0:
                    continue
                longueur = self._longueurs[champ].get(article.slug, 0)
                moyenne = self._longueur_moyenne[champ]
                normalisation = 1.0 - B + B * (longueur / moyenne)
                score_terme += (
                    POIDS_CHAMPS[champ]
                    * idf
                    * (tf * (K1 + 1.0))
                    / (tf + K1 * normalisation)
                )
            if score_terme > 0:
                trouves.append(terme)
                total += score_terme

        return total, trouves

    @staticmethod
    def _score_final(score_bm25: float, couverture: float) -> float:
        """Score de classement : BM25F pondéré par la part de question couverte.

        POURQUOI LES DEUX CRITÈRES. Le seul BM25 classe « chatbot sur mon site »
        en tête sur l'article « Site web professionnel à Abidjan » — parce que
        « site » y est partout dans le titre — alors qu'un article couvre
        réellement les DEUX mots de la question. Inversement, la couverture
        seule fait gagner un article qui reprend tous les mots de la question
        sans être le bon sujet. Les deux sont nécessaires, et aucun ne doit
        pouvoir écraser l'autre : d'où une pondération, pas un filtre.
        """
        return score_bm25 * (PLANCHER_COUVERTURE + (1.0 - PLANCHER_COUVERTURE) * couverture)

    def rechercher(
        self, requete: str, limite: int = RESULTATS_DEFAUT, seuil_couverture: float = 0.0
    ) -> List[Resultat]:
        """Meilleurs articles pour `requete`, du plus pertinent au moins pertinent."""
        termes = tokeniser(requete)
        if not termes or not self.articles:
            return []

        termes_uniques = list(dict.fromkeys(termes))
        resultats: List[Resultat] = []

        for article in self.articles:
            score_bm25, trouves = self._score_bm25(article, termes_uniques)
            if not trouves:
                continue
            couverture = len(trouves) / len(termes_uniques)
            resultats.append(
                Resultat(
                    article=article,
                    score=self._score_final(score_bm25, couverture),
                    score_bm25=score_bm25,
                    couverture=couverture,
                    termes_trouves=trouves,
                )
            )

        # Tri multi-clés de directions MIXTES (score ↓, couverture ↓, date ↓,
        # slug ↑) : `reverse=True` ne sait pas mélanger les sens, on empile
        # donc trois tris STABLES, du moins significatif au plus significatif.
        # Le résultat est total et reproductible d'un appel à l'autre.
        resultats.sort(key=lambda r: r.article.slug)
        resultats.sort(key=lambda r: (r.couverture, r.article.date or ""), reverse=True)
        resultats.sort(key=lambda r: r.score, reverse=True)

        if seuil_couverture > 0:
            resultats = [r for r in resultats if r.couverture >= seuil_couverture]
        return resultats[: max(1, min(limite, RESULTATS_MAX))]


# ============================================================
# CHARGEMENT / MÉMOÏSATION
# ============================================================


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _valider_index(donnees: object) -> Tuple[bool, str]:
    """Vérifie la forme de l'index du blog avant de s'en servir.

    C'est la parade au risque nommé dans la coordination : si le dépôt du blog
    change le schéma, on le détecte **ici**, avec un message clair, au lieu de
    produire une recherche qui ne trouve rien sans rien dire.
    """
    if not isinstance(donnees, dict):
        return False, "l'index n'est pas un objet JSON"
    articles = donnees.get("articles")
    if not isinstance(articles, list):
        return False, "la clé 'articles' est absente ou n'est pas une liste"
    for article in articles[:5]:
        if not isinstance(article, dict):
            return False, "un élément de 'articles' n'est pas un objet"
        for cle in ("slug", "titre"):
            if not isinstance(article.get(cle), str) or not article.get(cle):
                return False, f"un article n'a pas de '{cle}' exploitable"
    return True, "ok"


def _articles_depuis_index(donnees: Dict) -> List[Article]:
    """Fiches d'articles depuis l'index, sans le corps."""
    articles: List[Article] = []
    for brut in donnees.get("articles") or []:
        slug = (brut.get("slug") or "").strip()
        titre = (brut.get("titre") or "").strip()
        if not slug or not titre:
            continue
        tags = brut.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        articles.append(
            Article(
                slug=slug,
                titre=titre,
                description=(brut.get("description") or "").strip(),
                url=(brut.get("url") or "").strip(),
                collection=brut.get("collection"),
                collection_titre=brut.get("collection_titre"),
                date=brut.get("date"),
                tags=[str(t) for t in tags],
            )
        )
    return articles


class ChargeurIndexBlog:
    """Charge l'index du blog une fois, le garde en mémoire, le rafraîchit à TTL.

    TROIS GARANTIES DE NON-INTERFÉRENCE AVEC LA CONVERSATION :
      · `instantane()` ne fait AUCUNE entrée-sortie : il rend ce qui est en
        mémoire, ou None. Il ne peut donc pas ralentir `POST /message` ;
      · toute erreur (réseau, JSON, schéma) est journalisée et absorbée — la
        recherche disparaît, la conversation continue ;
      · la construction se fait dans un fil d'arrière-plan déclenché au
        premier appel, jamais sur le fil de la requête.
    """

    def __init__(self) -> None:
        self._verrou = threading.Lock()
        self._index: Optional[IndexBlog] = None
        self._charge_le: float = 0.0
        self._genere_le: Optional[str] = None
        self._en_cours = False
        self._derniere_erreur: Optional[str] = None
        self._source_corps = "index seul"

    # --- lecture ------------------------------------------------------
    def instantane(self) -> Optional[IndexBlog]:
        """Index en mémoire, ou None. Aucune entrée-sortie, aucun blocage."""
        index = self._index
        if index is not None and self._est_perime():
            self.declencher()
        return index

    def pret(self) -> bool:
        return self._index is not None

    def _est_perime(self) -> bool:
        return (time.time() - self._charge_le) > TTL_SECONDES

    def etat(self) -> Dict:
        """État interne — exposé dans les réponses pour rendre le diagnostic possible."""
        return {
            "disponible": self._index is not None,
            "articles_indexes": self._index.taille if self._index else 0,
            "articles_avec_corps": self._index.articles_avec_corps if self._index else 0,
            "genere_le": self._genere_le,
            "charge_il_y_a_s": int(time.time() - self._charge_le) if self._charge_le else None,
            "ttl_s": TTL_SECONDES,
            "source": self._source_corps,
            "derniere_erreur": self._derniere_erreur,
        }

    # --- construction -------------------------------------------------
    def declencher(self) -> None:
        """Lance une reconstruction en tâche de fond si aucune n'est en cours.

        Publique et NON BLOQUANTE : c'est ce que la conversation appelle pour
        amorcer l'index au premier message, sans jamais faire attendre le
        visiteur. Sans cet appel, un index jamais demandé ailleurs ne se
        construirait jamais.
        """
        with self._verrou:
            if self._en_cours:
                return
            self._en_cours = True
        fil = threading.Thread(
            target=self._construire_en_fond, name="blog-index", daemon=True
        )
        fil.start()

    def _construire_en_fond(self) -> None:
        try:
            self.construire()
        except Exception as exc:  # pragma: no cover - filet
            self._derniere_erreur = f"{type(exc).__name__}: {exc}"
            logger.warning("Index blog : construction impossible (%s)", exc)
        finally:
            with self._verrou:
                self._en_cours = False

    def attendre_pret(self, secondes: float) -> bool:
        """Attend (au plus `secondes`) que l'index soit construit.

        Réservé à `GET /api/chatbot/search` : une recherche explicite peut
        attendre le premier chargement, la conversation non.
        """
        if self._index is not None:
            return True
        fin = time.time() + max(0.0, secondes)
        self.declencher()
        while time.time() < fin:
            if self._index is not None:
                return True
            time.sleep(0.05)
        return self._index is not None

    def construire(self) -> Optional[IndexBlog]:
        """Construit l'index : fiches depuis l'index, corps depuis les pages."""
        donnees, origine = self._lire_index()
        if donnees is None:
            # Aucune source : on garde l'index précédent s'il existe, sinon on
            # reste indisponible — sans lever, sans bloquer.
            logger.warning("Index blog indisponible (origine: %s)", origine)
            return self._index

        valide, motif = _valider_index(donnees)
        if not valide:
            self._derniere_erreur = (
                f"schéma d'index inattendu ({motif}) — l'index du blog a peut-être changé"
            )
            logger.warning("Index blog : %s", self._derniere_erreur)
            return self._index

        articles = _articles_depuis_index(donnees)
        avec_corps = self._enrichir_avec_les_corps(articles)

        index = IndexBlog(articles)
        self._index = index
        self._charge_le = time.time()
        self._genere_le = donnees.get("genere_le")
        self._source_corps = (
            f"index + corps d'articles ({avec_corps}/{len(articles)})"
            if avec_corps
            else "index seul (titres, descriptions, tags)"
        )
        self._derniere_erreur = None
        logger.info(
            "Index blog chargé : %s articles, %s avec corps, genere_le=%s (origine %s)",
            len(articles),
            avec_corps,
            self._genere_le,
            origine,
        )
        return index

    # --- sources de l'index -------------------------------------------
    def _lire_index(self) -> Tuple[Optional[Dict], str]:
        """Index brut + origine. Ordre : fichier local, réseau, cache disque."""
        if INDEX_PATH and Path(INDEX_PATH).exists():
            donnees = self._lire_json_fichier(Path(INDEX_PATH))
            if donnees is not None:
                return donnees, f"fichier local {INDEX_PATH}"

        donnees = self._lire_json_reseau(INDEX_URL)
        if donnees is not None:
            self._ecrire_cache(donnees)
            return donnees, f"réseau {INDEX_URL}"

        donnees = self._lire_json_fichier(Path(CACHE_PATH))
        if donnees is not None:
            return donnees, f"cache disque {CACHE_PATH}"

        return None, "aucune source disponible"

    @staticmethod
    def _lire_json_fichier(chemin: Path) -> Optional[Dict]:
        try:
            return json.loads(chemin.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Index blog : lecture de %s impossible (%s)", chemin, exc)
            return None

    @staticmethod
    def _lire_json_reseau(url: str) -> Optional[Dict]:
        """Lecture HTTP de l'index. `httpx` et `requests` sont des dépendances
        existantes du projet ; on n'en ajoute aucune."""
        try:
            import httpx

            reponse = httpx.get(url, timeout=DELAI_FETCH, follow_redirects=True)
            if reponse.status_code != 200:
                logger.warning("Index blog : HTTP %s sur %s", reponse.status_code, url)
                return None
            return reponse.json()
        except Exception as exc:
            logger.warning("Index blog : %s injoignable (%s)", url, exc)
            return None

    @staticmethod
    def _ecrire_cache(donnees: Dict) -> None:
        try:
            chemin = Path(CACHE_PATH)
            chemin.parent.mkdir(parents=True, exist_ok=True)
            chemin.write_text(
                json.dumps(donnees, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:  # pragma: no cover - disque en lecture seule
            logger.debug("Index blog : cache non écrit (%s)", exc)

    # --- enrichissement par le corps des articles ----------------------
    def _enrichir_avec_les_corps(self, articles: List[Article]) -> int:
        """Récupère le texte des articles publiés. Renvoie le nombre de succès.

        Borné par `MAX_ARTICLES_CORPS` et `BUDGET_CORPS` : sur un blog de 81
        articles, la construction reste mesurée au lieu de s'étaler.
        """
        if not articles:
            return 0
        try:
            import httpx
        except Exception:  # pragma: no cover - httpx est une dépendance du projet
            logger.warning("Index blog : httpx absent, index sur titres seulement")
            return 0

        debut = time.time()
        succes = 0
        with httpx.Client(timeout=DELAI_FETCH, follow_redirects=True) as client:
            for article in articles[:MAX_ARTICLES_CORPS]:
                if time.time() - debut > BUDGET_CORPS:
                    logger.info(
                        "Index blog : budget de %ss atteint, %s articles lus",
                        BUDGET_CORPS,
                        succes,
                    )
                    break
                if not article.url:
                    continue
                try:
                    reponse = client.get(article.url)
                    if reponse.status_code != 200:
                        continue
                    texte = extraire_texte_article(reponse.text)
                    # Garde-fou : un texte trop court signifie que l'extraction
                    # a échoué (page refondue) — on préfère titre + description
                    # à un corps qui polluerait l'index avec du menu.
                    if len(texte.split()) >= 80:
                        article.corps = texte
                        succes += 1
                except Exception as exc:
                    logger.debug("Index blog : corps de %s non lu (%s)", article.slug, exc)
                    continue
        return succes


# ============================================================
# INSTANCE PARTAGÉE (mémoïsation du processus)
# ============================================================

_chargeur: Optional[ChargeurIndexBlog] = None
_verrou_chargeur = threading.Lock()


def chargeur() -> ChargeurIndexBlog:
    """Instance unique de processus — c'est elle qui garantit la mémoïsation."""
    global _chargeur
    if _chargeur is None:
        with _verrou_chargeur:
            if _chargeur is None:
                _chargeur = ChargeurIndexBlog()
    return _chargeur


# ============================================================
# INTERFACE PUBLIQUE
# ============================================================


def rechercher(
    requete: str,
    limite: int = RESULTATS_DEFAUT,
    attendre: float = 0.0,
) -> Dict:
    """Recherche dans le blog.

    Renvoie TOUJOURS un dictionnaire — jamais d'exception, jamais de `None`.
    C'est ce qui rend l'appel sûr depuis le flux de conversation comme depuis
    une route HTTP.

    Args:
        requete: question du visiteur.
        limite: nombre de résultats souhaités (borné par `RESULTATS_MAX`).
        attendre: secondes d'attente maximale du premier chargement.
    """
    if not ACTIF:
        return {
            "requete": requete,
            "resultats": [],
            "total": 0,
            "index": {"disponible": False, "raison": "recherche désactivée"},
        }

    requete_propre = (requete or "").strip()
    if not requete_propre:
        return {
            "requete": "",
            "resultats": [],
            "total": 0,
            "message": "Requête vide : indiquez des mots-clés (exemple : « calculer mon CAC »).",
            "index": chargeur().etat(),
        }

    try:
        memo = chargeur()
        if not memo.pret():
            if attendre > 0:
                memo.attendre_pret(attendre)
            else:
                # Conversation : on amorce la construction SANS attendre, et on
                # répond avec l'index disponible (souvent aucun). Le message
                # suivant — quelques secondes plus tard — en profitera.
                memo.declencher()
        index = memo.instantane()

        if index is None or index.taille == 0:
            return {
                "requete": requete_propre,
                "resultats": [],
                "total": 0,
                "message": (
                    "Le contenu du blog n'est pas disponible pour le moment. "
                    "La conversation reste possible."
                ),
                "index": memo.etat(),
            }

        resultats = index.rechercher(requete_propre, limite=limite)
        reponse = {
            "requete": requete_propre,
            "resultats": [r.pour_api() for r in resultats],
            "total": len(resultats),
            "index": memo.etat(),
        }
        if not resultats:
            reponse["message"] = (
                "Aucun article du blog ne correspond à cette recherche. "
                "Reformulez avec d'autres mots, ou posez la question à Mia."
            )
        return reponse
    except Exception as exc:  # pragma: no cover - filet de sécurité
        logger.error("Recherche blog : échec (%s)", exc, exc_info=True)
        return {
            "requete": requete_propre,
            "resultats": [],
            "total": 0,
            "message": "La recherche est momentanément indisponible.",
            "index": {"disponible": False},
        }


def enrichir_contexte(requete: str) -> Optional[Dict]:
    """Bloc de contexte blog pour le prompt de Mia, ou None.

    N'appelle JAMAIS le réseau (attendre=0) : si l'index n'est pas prêt, la
    recherche est simplement absente de ce message. La conversation ne peut
    donc pas être ralentie ni cassée par cette fonction.
    """
    if not ACTIF or not (requete or "").strip():
        return None
    try:
        resultat = rechercher(requete, limite=MAX_ARTICLES_CONTEXTE, attendre=0.0)
        pertinents = [r for r in resultat.get("resultats", []) if r.get("pertinent")]
        if not pertinents:
            return None
        memo = chargeur()
        index = memo.instantane()
        extraits = []
        for r in pertinents:
            article = None
            if index is not None:
                for candidat in index.articles:
                    if candidat.slug == r["slug"]:
                        article = candidat
                        break
            extraits.append(
                {
                    "slug": r["slug"],
                    "titre": r["titre"],
                    "url": r["url"],
                    "date": r.get("date"),
                    "extrait": article.extrait() if article else r.get("description", ""),
                }
            )
        return {"genere_le": resultat.get("index", {}).get("genere_le"), "articles": extraits}
    except Exception as exc:  # pragma: no cover - filet de sécurité
        logger.warning("Contexte blog : ignoré (%s)", exc)
        return None

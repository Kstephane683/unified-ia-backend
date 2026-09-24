"""
Connaissance du SITE du tenant (chantier E du lot du 24/09) — E.1 : quand le
visiteur pose une question, Mia cherche D'ABORD dans le contenu du site du
client (pages services, produit, diagnostic, à propos) avant le blog et avant
de générer une réponse LLM.

Fonctionnement :
- les pages indexées sont celles du gabarit eperformance, chemin par chemin —
  la même liste que `liens_site.CATALOGUE` (une seule source : le catalogue
  qui alimente les liens du chat sert aussi au corpus) ;
- les pages sont chargées en HTTP public depuis `ChatbotSite.site_url`, en
  mémoire avec TTL, dans un thread de fond : le premier message du site lance
  le chargement, la réponse part sans attendre ; les suivants en profitent ;
- la recherche est lexicale, sans LLM, et n'appelle jamais le réseau une fois
  l'index en mémoire ;
- ce module NE LÈVE JAMAIS et ne peut pas ralentir une réponse : toute erreur
  est absorbée, et un index absent signifie simplement « pas de bloc ».
"""

import html as _html
import re
import threading
import time
from typing import Dict, List, Optional

from .blog_search import tokeniser
from .liens_site import CATALOGUE

CHEMINS: List[str] = [""] + [c["chemin"] for c in CATALOGUE]
TTL_SECONDES = 6 * 3600
DELAI_FETCH = 3.0
SEUIL_SCORE = 6.0
MIN_TOKENS_COMUNS = 2

_lock = threading.Lock()
_index_par_site: Dict[str, dict] = {}
_en_chargement: set = set()


def _extraire_texte(page_html: str) -> Optional[str]:
    """Texte lisible d'une page : sans scripts, styles, balises ni navigation."""
    if not page_html:
        return None
    try:
        corps = page_html
        # Le corps utile : après <body>, avant le bandeau de consentement/pied
        m = re.search(r"<body[^>]*>(.*?)</body>", corps, re.S | re.I)
        if m:
            corps = m.group(1)
        corps = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", corps, flags=re.S | re.I)
        corps = re.sub(r"<[^>]+>", " ", corps)
        corps = _html.unescape(corps)
        corps = re.sub(r"\s+", " ", corps).strip()
        return corps or None
    except Exception:
        return None


def _titre_page(page_html: str, chemin: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", page_html or "", re.S | re.I)
    if m and m.group(1).strip():
        return _html.unescape(m.group(1).strip())
    return chemin or "accueil"


def _charger_pages(site_url: str) -> List[dict]:
    """Charge les pages du gabarit en HTTP public. Toute erreur -> page absente."""
    from urllib.request import Request, urlopen

    base = site_url if site_url.endswith("/") else site_url + "/"
    pages: List[dict] = []
    for chemin in CHEMINS:
        url = base + chemin
        try:
            demande = Request(url, headers={"User-Agent": "ePerformance-Chatbot/1.0"})
            with urlopen(demande, timeout=DELAI_FETCH) as reponse:
                brut = reponse.read(800_000).decode("utf-8", "ignore")
            texte = _extraire_texte(brut)
            if texte and len(texte) > 200:
                pages.append(
                    {
                        "url": url,
                        "titre": _titre_page(brut, chemin),
                        "texte": texte,
                    }
                )
        except Exception:
            continue  # page absente ou site injoignable : on continue
    return pages


def _demander_chargement(site_url: str) -> None:
    """Lance le chargement en fond si l'index est absent ou périmé."""
    with _lock:
        entree = _index_par_site.get(site_url)
        if entree and time.time() - entree["charge_le"] < TTL_SECONDES:
            return
        if site_url in _en_chargement:
            return
        _en_chargement.add(site_url)

    def _travail():
        try:
            pages = _charger_pages(site_url)
            with _lock:
                _index_par_site[site_url] = {"pages": pages, "charge_le": time.time()}
        finally:
            with _lock:
                _en_chargement.discard(site_url)

    threading.Thread(target=_travail, daemon=True, name="index-site-tenant").start()


def _rechercher(pages: List[dict], requete: str, limite: int = 2) -> List[dict]:
    """Recherche lexicale simple par recouvrement de tokens, pondérée titre."""
    termes = set(tokeniser(requete or ""))
    if not termes:
        return []
    resultats = []
    for page in pages:
        tokens_corps = tokeniser(page["texte"])
        tokens_titre = set(tokeniser(page["titre"]))
        communs = termes & (set(tokens_corps) | tokens_titre)
        if len(communs) < MIN_TOKENS_COMUNS:
            continue
        score = 3.0 * sum(1 for t in communs if t in tokens_titre) + 1.0 * sum(
            1 for t in tokens_corps if t in termes
        )
        if score < SEUIL_SCORE:
            continue
        resultats.append(
            {
                "url": page["url"],
                "titre": page["titre"],
                "score": round(score, 2),
                "extrait": page["texte"][:400],
            }
        )
    resultats.sort(key=lambda r: r["score"], reverse=True)
    return resultats[:limite]


def rechercher(requete: str, site_url: Optional[str], attendre: float = 0.0) -> List[dict]:
    """Résultats dans les pages du site du tenant — [] si rien ne joue.

    `attendre` : secondes d'attente maximale d'un index en cours de chargement
    (0 par défaut : la réponse ne doit jamais attendre le réseau).
    """
    if not site_url or not (requete or "").strip():
        return []
    _démarré = False
    entree = _index_par_site.get(site_url)
    if not entree or time.time() - entree["charge_le"] >= TTL_SECONDES:
        _demander_chargement(site_url)
        _démarré = True
        entree = _index_par_site.get(site_url)
        if not entree and attendre > 0:
            fin = time.time() + attendre
            while time.time() < fin:
                time.sleep(0.2)
                entree = _index_par_site.get(site_url)
                if entree:
                    break
    if not entree:
        return []
    try:
        return _rechercher(entree["pages"], requete)
    except Exception:
        return []


def enrichir_contexte(requete: str, site_url: Optional[str]) -> Optional[dict]:
    """Bloc de contexte « pages du site » pour le prompt de Mia, ou None.

    N'appelle JAMAIS le réseau de façon bloquante : le chargement se fait en
    fond, et tant qu'il n'est pas prêt le bloc est simplement absent.
    """
    if not site_url or not (requete or "").strip():
        return None
    try:
        resultats = rechercher(requete, site_url, attendre=0.0)
        if not resultats:
            return None
        return {"site_url": site_url, "pages": resultats}
    except Exception:
        return None


def etat_index(site_url: Optional[str] = None) -> dict:
    """État lisible de l'index (diagnostic, jamais levant)."""
    with _lock:
        if site_url:
            entree = _index_par_site.get(site_url)
            if not entree:
                return {"site_url": site_url, "charge": False}
            return {
                "site_url": site_url,
                "charge": True,
                "pages": len(entree["pages"]),
                "age_secondes": int(time.time() - entree["charge_le"]),
            }
        return {u: len(e["pages"]) for u, e in _index_par_site.items()}

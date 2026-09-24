"""
Mode apprentissage (chantier F du lot du 24/09) — moteur de recherche des
connaissances ajoutées par le propriétaire depuis le dashboard admin.

Le propriétaire enseigne : Q/R fréquentes et documents texte. Ces données ont
PRIORITÉ sur tout le reste (pages du site, blog, génération LLM) : quand une
connaissance répond à la question, elle est injectée dans le contexte en tête.

Recherche lexicale par recouvrement de tokens (même langue que blog_search et
connaissance_site — pas d'embedding, aucun coût LLM pour la recherche).

Index par site, mémoïsé, invalidé à chaque écriture (create/update/delete) —
l'invalidation est déclenchée par les routes admin, pas par un TTL : le
propriétaire doit voir l'effet de son entraînement immédiatement.
"""

import threading
from typing import Dict, List, Optional

from .blog_search import tokeniser

_lock = threading.Lock()
_index_par_site: Dict[str, List[dict]] = {}


def invalider(site_id: Optional[str] = None) -> None:
    """Invalide le cache (un site, ou tous). Appelé par les routes admin."""
    with _lock:
        if site_id:
            _index_par_site.pop(site_id, None)
        else:
            _index_par_site.clear()


def reconstruire(site_id: str, connaissances: List[dict]) -> None:
    """Remplace l'index du site par la liste fournie (lues depuis la base)."""
    items = []
    for c in connaissances:
        if not c.get("actif", True):
            continue
        if c.get("type") == "qr":
            question = (c.get("question") or "").strip()
            reponse = (c.get("reponse") or "").strip()
            if not question or not reponse:
                continue
            items.append(
                {
                    "id": c["id"],
                    "type": "qr",
                    "corpus": f"{question}\n{reponse}",
                    "question": question,
                    "reponse": reponse,
                }
            )
        elif c.get("type") == "texte":
            contenu = (c.get("contenu") or "").strip()
            if not contenu:
                continue
            items.append(
                {
                    "id": c["id"],
                    "type": "texte",
                    "corpus": contenu,
                    "question": None,
                    "reponse": contenu,
                    "source_url": c.get("source_url"),
                }
            )
    with _lock:
        if items:
            _index_par_site[site_id] = items
        else:
            _index_par_site.pop(site_id, None)


def chercher(site_id: str, message: str, seuil: float = 0.34) -> List[dict]:
    """Les connaissances qui correspondent au message — [] sinon.

    `seuil` : fraction des tokens de la QUESTION du propriétaire qui doit se
    retrouver dans le message du visiteur (les Q/R sont courtes : un
    recouvrement de mots suffit, un score BM25 complet serait du luxe ici).
    """
    with _lock:
        items = list(_index_par_site.get(site_id) or [])
    if not items or not (message or "").strip():
        return []
    tokens_message = set(tokeniser(message))
    if not tokens_message:
        return []

    resultats = []
    for item in items:
        if item["type"] != "qr":
            # Document texte : recouvrement de corpus, au moins 2 tokens.
            tokens_doc = set(tokeniser(item["corpus"]))
            communs = tokens_message & tokens_doc
            if len(communs) >= 2:
                resultats.append({**item, "score": len(communs) / max(len(tokens_doc), 1)})
            continue
        tokens_question = set(tokeniser(item["question"]))
        if not tokens_question:
            continue
        communs = tokens_question & tokens_message
        couverture = len(communs) / len(tokens_question)
        if couverture >= seuil:
            resultats.append({**item, "score": round(couverture, 2)})

    resultats.sort(key=lambda r: r["score"], reverse=True)
    return resultats[:3]


def charger_depuis_db(db, site_id: str) -> None:
    """(Re)charge l'index d'un site depuis la base. Ne lève jamais."""
    try:
        from sqlalchemy import text

        lignes = (
            db.execute(
                text(
                    "SELECT id, type, question, reponse, contenu, source_url, actif "
                    "FROM connaissances_proprietaire WHERE site_id = :s"
                ),
                {"s": site_id},
            )
            .mappings()
            .all()
        )
        reconstruire(site_id, [dict(l) for l in lignes])
    except Exception:
        pass  # table absente (premier boot) ou base injoignable : index vide

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Banc de mesure de la recherche blog — tâche 6.8.

CE QU'IL MESURE
---------------
Que la recherche trouve les BONS articles, pas seulement qu'elle répond. Une
recherche qui renvoie « quelque chose » sans rapport est pire qu'une recherche
absente : elle ferait écrire à Mia une réponse appuyée sur un article hors
sujet. Ce banc compare donc, pour des questions réelles de visiteurs, le
premier résultat à l'article attendu.

UTILISATION
-----------
    python3 scripts/benchmark_recherche_blog.py              # index public du blog
    python3 scripts/benchmark_recherche_blog.py --json       # sortie machine
    python3 scripts/benchmark_recherche_blog.py --limite 5

Code de sortie : 0 si toutes les questions attendues sont trouvées dans le
top-1, 1 sinon. Un échec ici signale une régression de la recherche (ou un
article renommé côté blog).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from backend.chatbot import blog_search as bs  # noqa: E402

#: (question posée par un visiteur, slug de l'article qui doit sortir en tête)
#: Les questions sont formulées comme un visiteur les écrit — pas avec les mots
#: de l'article. C'est ce qui rend la mesure utile : une question qui reprend
#: le titre exact ne prouve rien.
QUESTIONS = [
    ("calculer mon cout d'acquisition client", "calculer-cac-cote-ivoire"),
    ("comment etre visible sur Google a Abidjan", "seo-local-abidjan-guide"),
    ("repondre aux clients la nuit sans recruter", "ia-service-client-nuit"),
    ("combien coute un site web professionnel", "site-web-professionnel-abidjan-guide"),
    (
        "faire rediger ses fiches produits avec intelligence artificielle",
        "rediger-fiches-produits-ia",
    ),
    ("chatbot sur mon site", "chatbot-ia-repondre-site"),
    ("gagner du temps avec l'IA dans mon entreprise", "cinq-taches-ia-entreprise"),
    ("prix d'un site internet", "site-web-professionnel-abidjan-guide"),
    ("j'ai un budget pub limite, par ou commencer", "calculer-cac-cote-ivoire"),
]

#: Requêtes qui ne DOIVENT rien trouver — elles prouvent que la recherche ne
#: « trouve pas toujours quelque chose ». Sans ce test, un moteur qui renvoie
#: systématiquement son premier article passerait le banc.
#: La deuxième est un faux positif RÉEL, trouvé puis corrigé : l'article CAC
#: contient la métaphore « le prix d'un billet d'avion », ce qui donnait à la
#: question aérienne une couverture de 0,50. Le plancher de score l'écarte.
HORS_SUJET = [
    "recette du gateau au chocolat",
    "zorglub qwerty xyzzy",
    "réservation d'un billet d'avion pour Tokyo",
]

#: Questions LÉGITIMES pour lesquelles le corpus publié n'a pas encore
#: d'article. Elles sont mesurées à part, et le résultat attendu est
#: explicitement « aucun article pertinent » : le blog publie 5 articles par
#: jour, ces questions trouveront leur réponse au fil des parutions. Les
#: compter comme des échecs de la recherche serait malhonnête ; les compter
#: comme des succès aussi. C'est la limite réelle du corpus, documentée.
SANS_ARTICLE_PUBLIE = [
    "mes visiteurs ne me contactent pas",
    "comment ameliorer mon taux de conversion",
]


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--limite", type=int, default=3, help="résultats affichés")
    parseur.add_argument("--json", action="store_true", help="sortie machine")
    args = parseur.parse_args()

    memo = bs.chargeur()
    index = memo.construire()
    etat = memo.etat()

    if index is None or index.taille == 0:
        print("ÉCHEC : index indisponible —", etat, file=sys.stderr)
        return 1

    if not args.json:
        print("=" * 78)
        print("BANC DE RECHERCHE BLOG — tâche 6.8")
        print("=" * 78)
        print(f"Articles indexés   : {index.taille}")
        print(f"Avec corps complet : {index.articles_avec_corps}/{index.taille}")
        print(f"Index généré le    : {etat.get('genere_le')}")
        print(f"Source             : {etat.get('source')}")
        print()

    resultats_json = []
    succes = 0
    for question, attendu in QUESTIONS:
        reponse = bs.rechercher(question, limite=args.limite)
        trouves = [r["slug"] for r in reponse["resultats"]]
        gagne = bool(trouves) and trouves[0] == attendu
        succes += int(gagne)
        resultats_json.append(
            {
                "question": question,
                "attendu": attendu,
                "top1": trouves[0] if trouves else None,
                "gagne": gagne,
                "resultats": reponse["resultats"],
            }
        )
        if not args.json:
            marque = "OK " if gagne else "ÉCHEC"
            print(f"{marque}  {question}")
            for rang, r in enumerate(reponse["resultats"], 1):
                fleche = "  <-- attendu" if r["slug"] == attendu else ""
                print(
                    f"        {rang}. score={r['score']:8.3f} "
                    f"couverture={r['couverture']:.2f}  {r['slug']}{fleche}"
                )
            if not reponse["resultats"]:
                print(f"        (aucun résultat — {reponse.get('message', '')})")
            print()

    hors_sujet_json = []
    faux_positifs = 0
    for question in HORS_SUJET:
        reponse = bs.rechercher(question, limite=args.limite)
        # On exige que RIEN ne soit retenu comme pertinent : des résultats de
        # score résiduel sont acceptables (l'endpoint les renvoie), une
        # injection dans la conversation ne l'est pas.
        pertinents = [r["slug"] for r in reponse["resultats"] if r["pertinent"]]
        faux_positifs += len(pertinents)
        hors_sujet_json.append(
            {"question": question, "resultats": reponse["resultats"], "pertinents": pertinents}
        )
        if not args.json:
            verdict = "OK " if not pertinents else "ÉCHEC"
            print(
                f"{verdict}  hors sujet : {question} → {len(reponse['resultats'])} brut(s), "
                f"{len(pertinents)} pertinent(s)"
            )

    sans_article_json = []
    for question in SANS_ARTICLE_PUBLIE:
        reponse = bs.rechercher(question, limite=args.limite)
        pertinents = [r["slug"] for r in reponse["resultats"] if r["pertinent"]]
        sans_article_json.append(
            {"question": question, "resultats": reponse["resultats"], "pertinents": pertinents}
        )
        if not args.json:
            verdict = "OK " if not pertinents else "à revoir"
            print(f"{verdict}  sans article publié : {question} → {len(pertinents)} pertinent(s)")

    total = len(QUESTIONS)
    if args.json:
        print(
            json.dumps(
                {
                    "index": etat,
                    "questions": resultats_json,
                    "hors_sujet": hors_sujet_json,
                    "sans_article_publie": sans_article_json,
                    "top1_correct": succes,
                    "total": total,
                    "faux_positifs": faux_positifs,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print("=" * 78)
        print(f"TOP-1 CORRECT        : {succes}/{total}")
        print(f"FAUX POSITIFS        : {faux_positifs} (attendu : 0)")
        print("=" * 78)

    # Le banc échoue si un article attendu n'est pas trouvé, ou si une question
    # hors sujet est jugée pertinente. Les questions sans article publié ne
    # font pas échouer le banc : elles documentent une limite du corpus.
    return 0 if (succes == total and faux_positifs == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())

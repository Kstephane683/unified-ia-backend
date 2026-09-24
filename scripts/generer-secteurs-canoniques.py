#!/usr/bin/env python3
"""
Génère `backend/chatbot/secteurs_canoniques.json` depuis la source canonique
du noyau (`agent-ia-web/eperf_core/sectors.py`) — chantier G du lot du 24/09.

Règle « une seule source, des références » : les données d'intention, les
thèmes FAQ et le vocabulaire produit VIENNENT du noyau, jamais réécrits à la
main. Ce script EST la traçabilité : il importe `sectors.py`, n'ajoute rien,
et date le fichier produit.

Périmètre : les 12 secteurs clients (`blog` et `email` sont exclus — décision
consignée au journal de coordination le 19/09, audit préalable app Mia).

Usage :
    python3 scripts/generer-secteurs-canoniques.py [chemin/vers/agent-ia-web]
"""

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SECTEURS_EXCLUS = {"blog", "email"}  # non clients (éditorial / bibliothèque)

CIBLE = Path(__file__).resolve().parent.parent / "backend" / "chatbot" / "secteurs_canoniques.json"


def generer(racine_noyau: str) -> dict:
    sys.path.insert(0, racine_noyau)
    try:
        from eperf_core import sectors
    finally:
        sys.path.pop(0)

    sorties = {}
    for slug, secteur in sectors.SECTEURS.items():
        if slug in SECTEURS_EXCLUS:
            continue
        d = dataclasses.asdict(secteur)
        item = d.get("item") or {}
        sorties[slug] = {
            "nom": d.get("nom"),
            "intention": d.get("intention"),
            "faq_themes": d.get("faq_themes") or [],
            "vocabulaire_produit": {
                "objet": item.get("nom"),
                "objet_pluriel": item.get("nom_pluriel"),
                "champs": item.get("champs") or {},
            },
            "cta_primaire": d.get("cta_primaire"),
            "cta_secondaire": d.get("cta_secondaire"),
        }
    return sorties


def main() -> int:
    racine = sys.argv[1] if len(sys.argv) > 1 else "/home/ballo/OX6A/agent-ia-web"
    sorties = generer(racine)
    document = {
        "_source": (
            "agent-ia-web/eperf_core/sectors.py — SECTEURS (source canonique, "
            "importée par ce script, jamais réécrite à la main)"
        ),
        "_genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "_script": "scripts/generer-secteurs-canoniques.py",
        "_exclus": sorted(SECTEURS_EXCLUS),
        "secteurs": sorties,
    }
    CIBLE.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[secteurs] {len(sorties)} secteurs écrits -> {CIBLE.name} (source: {racine})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

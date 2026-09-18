#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Purge des conversations au-delà de la rétention (12 mois par défaut).

USAGE
    python3 scripts/purge_conversations.py                # dry-run (défaut)
    python3 scripts/purge_conversations.py --execute      # supprime
    python3 scripts/purge_conversations.py --mois 6       # autre rétention

SOURCE DE VÉRITÉ : la page cookies d'eperformance.pro annonce « 12 mois ».
Si cette durée change côté site, elle doit changer ici (et inversement) —
c'est un engagement public, pas un réglage interne.

NÉCESSITE DATABASE_URL dans l'environnement. En local, la base Railway est en
réseau interne : ouvrir un tunnel (`railway connect postgres --tunnel-only`)
puis exporter l'URL, ou exécuter depuis un conteneur Railway.
"""
import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(message)s")

from backend.core.database import SessionLocal  # noqa: E402
from backend.chatbot.retention import (  # noqa: E402
    purge_expired_conversations,
    RETENTION_MONTHS_DEFAULT,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--execute", action="store_true",
                    help="supprime réellement (sans ce drapeau : dry-run)")
    ap.add_argument("--mois", type=int, default=RETENTION_MONTHS_DEFAULT,
                    help=f"ancienneté de rétention en mois (défaut {RETENTION_MONTHS_DEFAULT})")
    ap.add_argument("--lot", type=int, default=500,
                    help="nombre maximal de conversations par exécution")
    args = ap.parse_args()

    if not os.getenv("DATABASE_URL"):
        print("ERREUR : DATABASE_URL absente de l'environnement", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        rapport = purge_expired_conversations(
            db,
            retention_months=args.mois,
            dry_run=not args.execute,
            batch_limit=args.lot,
        )
    finally:
        db.close()

    print(json.dumps(rapport, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Rétention des conversations — purge automatique à 12 mois.

POURQUOI CE MODULE
------------------
La page cookies d'eperformance.pro affirme : « Les conversations sont
conservées 12 mois, puis supprimées automatiquement. » Cette affirmation était
FAUSSE : aucun mécanisme de purge n'existait (demande de l'agent SITE, journal
COORDINATION-AGENTS.md — priorité haute, engagement de conformité).

RÈGLES
------
- Une conversation est purgée si son dernier message (ou sa création) date de
  plus de `RETENTION_MONTHS` mois (12 par défaut, surchargeable).
- Les messages suivent (FK ON DELETE CASCADE).
- `dry_run=True` par défaut : on ne supprime RIEN sans `--execute` explicite.
  C'est volontaire : un script de purge qui s'exécute par accident ne doit pas
  pouvoir détruire des données.
- Chaque exécution écrit une ligne de journal : date, mode, conversations
  trouvées, supprimées, messages supprimés. La conformité exige la TRACE.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

RETENTION_MONTHS_DEFAULT = 12
# Bornes de sécurité : jamais moins de 1 mois, jamais plus de 10 ans
RETENTION_MONTHS_MIN = 1
RETENTION_MONTHS_MAX = 120


def _cutoff(months: int) -> datetime:
    """Date limite : tout ce qui est antérieur est purgé.

    `relativedelta` n'est pas disponible sans dépendance : on calcule par
    soustraction de jours (365,25 j/mois en moyenne) — l'écart d'un ou deux
    jours sur 12 mois est sans conséquence pour une politique de rétention.
    """
    return datetime.utcnow() - timedelta(days=int(months * 30.44))


def purge_expired_conversations(
    db: Session,
    retention_months: int = RETENTION_MONTHS_DEFAULT,
    dry_run: bool = True,
    batch_limit: int = 500,
) -> Dict[str, Any]:
    """Purge les conversations dont le dernier message dépasse la rétention.

    Args:
        db: session SQLAlchemy
        retention_months: ancienneté au-delà de laquelle on purge (défaut 12)
        dry_run: True (défaut) = compte seulement, ne supprime rien
        batch_limit: nombre maximal de conversations traitées par exécution
                     (évite une transaction géante sur une base ancienne)

    Returns:
        Rapport : mode, seuil, conversations candidates, supprimées, messages.
    """
    months = max(RETENTION_MONTHS_MIN, min(retention_months, RETENTION_MONTHS_MAX))
    seuil = _cutoff(months)

    # « Dernier message » = COALESCE(last_message_at, created_at) : une
    # conversation jamais relue mais ancienne doit partir aussi.
    candidates = db.execute(
        text(
            """
            SELECT conversation_id
            FROM chatbot_conversations
            WHERE COALESCE(last_message_at, created_at) < :seuil
            ORDER BY COALESCE(last_message_at, created_at) ASC
            LIMIT :limite
            """
        ),
        {"seuil": seuil, "limite": batch_limit},
    ).fetchall()

    ids = [row[0] for row in candidates]

    rapport: Dict[str, Any] = {
        "date": datetime.utcnow().isoformat() + "Z",
        "mode": "dry-run" if dry_run else "execute",
        "retention_mois": months,
        "seuil": seuil.isoformat() + "Z",
        "conversations_candidates": len(ids),
        "conversations_supprimees": 0,
        "messages_supprimes": 0,
    }

    if not ids or dry_run:
        if dry_run and ids:
            logger.info(
                "[retention] dry-run : %d conversation(s) antérieure(s) à %s seraient purgées",
                len(ids),
                seuil.date(),
            )
        return rapport

    # Comptage des messages AVANT suppression (pour la trace de conformité).
    # NB : on passe par une SOUS-REQUÊTE plutôt qu'un tableau lié — psycopg2
    # n'accepte pas `ANY(:liste)` sans typage explicite du tableau.
    critere = """
        SELECT conversation_id FROM chatbot_conversations
        WHERE COALESCE(last_message_at, created_at) < :seuil
        ORDER BY COALESCE(last_message_at, created_at) ASC
        LIMIT :limite
    """
    messages = db.execute(
        text(f"SELECT COUNT(*) FROM chatbot_messages WHERE conversation_id IN ({critere})"),
        {"seuil": seuil, "limite": batch_limit},
    ).scalar() or 0

    # Suppression : les messages partent par ON DELETE CASCADE
    db.execute(
        text(f"DELETE FROM chatbot_conversations WHERE conversation_id IN ({critere})"),
        {"seuil": seuil, "limite": batch_limit},
    )
    db.commit()

    rapport["conversations_supprimees"] = len(ids)
    rapport["messages_supprimes"] = int(messages)

    # TRACE OBLIGATOIRE (engagement de conformité) — une ligne par exécution
    logger.warning(
        "[retention] PURGE EXÉCUTÉE : %d conversation(s) et %d message(s) supprimés "
        "(antérieurs au %s, rétention %d mois)",
        len(ids),
        messages,
        seuil.date(),
        months,
    )
    return rapport

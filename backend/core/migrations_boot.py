"""
Migration idempotente appliquée AU BOOT — refonte app Mia (B1-B4).

LE PIÈGE QUE CE MODULE RÉPARE
-----------------------------
`init_db()` appelle `Base.metadata.create_all()`, qui crée les tables ABSENTES
mais n'ajoute JAMAIS une colonne à une table existante. Les colonnes ci-dessous
ont donc été ajoutées au modèle (`backend/core/models.py`, `backend/chatbot/
models.py`) alors que les tables `users` et `chatbot_sites` existent déjà en
production : sans ALTER TABLE explicite, l'ORM aurait annoncé des colonnes que
la base n'a pas, et toute lecture/écriture de ces colonnes serait tombée en
erreur au premier accès.

COMMENT LA MIGRATION EST APPLIQUÉE
----------------------------------
Au démarrage, APRÈS `init_db()` (voir `backend/api/app.py`) :
  1. si la table n'existe pas encore, on n'y touche pas — create_all vient de
     (ou va) la créer complète, colonnes incluses ;
  2. sinon, l'inspecteur SQLAlchemy liste les colonnes RÉELLES de la table
     (aucune hypothèse sur le dialecte) et les colonnes manquantes sont
     ajoutées par ALTER TABLE — donc ré-exécuter ne fait RIEN (idempotent).

Le même travail existe sous forme SQL manuelle pour Railway :
`migrations/postgresql/005_refonte_app_mia.sql` (contrat IMPORT_MIGRATIONS_RAILWAY.sh).

DIALECTES
---------
Les DDL choisis passent sur PostgreSQL (production) comme sur SQLite (tests) :
VARCHAR(n), TEXT, BOOLEAN DEFAULT FALSE, JSON. Aucun `IF NOT EXISTS` de
dialecte propriétaire : la vérification de présence est faite côté Python.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from sqlalchemy import inspect, text

from backend.core.database import engine

logger = logging.getLogger(__name__)

# table -> [(nom_colonne, DDL SQL), ...]
PLAN_COLONNES: Dict[str, List[Tuple[str, str]]] = {
    "users": [
        ("nom", "VARCHAR(200)"),
        ("site_id", "VARCHAR(100)"),
        ("role_client", "VARCHAR(20)"),
        ("must_change_password", "BOOLEAN DEFAULT FALSE"),
        ("totp_secret", "TEXT"),
        ("totp_enabled", "BOOLEAN DEFAULT FALSE"),
    ],
    "chatbot_sites": [
        ("sector", "VARCHAR(50)"),
        ("horaires", "JSON"),
        ("notification_settings", "JSON"),
    ],
}

# Index utiles (CREATE INDEX IF NOT EXISTS passe sur PostgreSQL et SQLite).
PLAN_INDEX: List[Tuple[str, str, str]] = [
    ("idx_users_site_id", "users", "site_id"),
    ("idx_users_role_client", "users", "role_client"),
]


def appliquer_migrations() -> Dict[str, List[str]]:
    """
    Ajoute les colonnes manquantes. Idempotent, ne lève pas pour une table
    absente. Renvoie un rapport lisible pour le journal de démarrage.

    Toute exception PROPAGE (l'appelant, dans app.py, absorbe comme il le fait
    déjà pour init_db) : un boot sans la colonne `must_change_password` serait
    pire qu'un boot en échec — les routes client refuseraient tout le monde.
    """
    rapport: Dict[str, List[str]] = {"colonnes_ajoutees": [], "index_crees": []}

    with engine.connect() as connexion:
        inspecteur = inspect(connexion)
        tables = set(inspecteur.get_table_names())

        for table, colonnes in PLAN_COLONNES.items():
            if table not in tables:
                # Table inexistante : create_all la créera COMPLÈTE (colonnes
                # du modèle incluses). Rien à faire ici.
                continue
            existantes = {c["name"] for c in inspecteur.get_columns(table)}
            for nom, ddl in colonnes:
                if nom in existantes:
                    continue
                connexion.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {nom} {ddl}")
                )
                rapport["colonnes_ajoutees"].append(f"{table}.{nom}")

        for nom_index, table, colonne in PLAN_INDEX:
            if table not in tables:
                continue
            existants = {
                i["name"] for i in inspecteur.get_indexes(table)
            }
            if nom_index in existants:
                continue
            connexion.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {nom_index} "
                    f"ON {table} ({colonne})"
                )
            )
            rapport["index_crees"].append(nom_index)

        connexion.commit()

    if rapport["colonnes_ajoutees"] or rapport["index_crees"]:
        logger.info("[migration-boot] %s", rapport)
    return rapport

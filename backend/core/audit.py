"""
Journal d'audit — refonte app Mia (chantier B2).

POURQUOI CETTE TABLE
--------------------
L'app Mia donne à un tiers (le propriétaire du site) accès aux conversations de
ses visiteurs — des données personnelles. Chaque action sensible doit laisser
une trace indépendante du bon vouloir de l'appelant : création d'un compte
client, changement de configuration, export RGPD, suppression de conversation,
activation/désactivation de la 2FA. C'est la réponse à la question « qui a fait
quoi, sur quel site, quand, depuis quelle IP » — celle qu'on ne sait pas poser
après coup si rien n'a été écrit.

CE QUI EST TRACÉ (et ce qui ne l'est JAMAIS)
--------------------------------------------
· action : identifiant stable en snake_case (ex. creation_compte_client) ;
· details : JSON borné — identifiants et motifs, jamais le contenu des
  conversations, jamais un mot de passe, jamais un secret TOTP ;
· ip : adresse de l'appelant, telle qu'arrivée (X-Forwarded-Or client.host).

NIVEAU DE TRANSACTION
---------------------
`tracer_audit` fait `db.add(...)` SANS commit : la trace est commise (ou
annulée) DANS LA MÊME TRANSACTION que l'action qu'elle décrit — un export RGPD
qui échoue ne laisse pas une trace de succès derrière lui. Les routes qui en
dépendent committent explicitement. La fonction ne lève jamais : une trace
impossible ne doit pas transformer une action réussie en erreur 500.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy import Column, Integer, String, JSON, TIMESTAMP
from sqlalchemy.sql import func

from backend.core.database import Base

logger = logging.getLogger(__name__)

# Actions tracées — liste fermée, documentée dans API-CLIENT-V1.md §10.
ACTIONS_AUDIT = (
    "creation_compte_client",          # provisionnement d'un propriétaire
    "changement_mot_de_passe",         # POST /api/client/v1/password
    "activation_2fa",                  # POST /api/client/v1/2fa/activate
    "desactivation_2fa",               # POST /api/client/v1/2fa/disable
    "configuration_site",              # PUT /api/client/v1/sites/{id}/settings
    "export_rgpd_conversation",        # GET  .../rgpd/conversations/{id}/export
    "suppression_rgpd_conversation",   # DELETE .../rgpd/conversations/{id}
)


class AuditLog(Base):
    """Une ligne par action sensible. Jamais de contenu de conversation."""

    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True, index=True,
                     comment='Compte ayant agi (peut avoir été supprimé depuis)')
    user_email = Column(String(255), nullable=True,
                        comment='E-mail du compte à l\'instant de l\'action')
    site_id = Column(String(100), nullable=True, index=True,
                     comment='Site concerné, s\'il y en a un')
    action = Column(String(100), nullable=False, index=True,
                    comment='Identifiant de l\'action (cf. ACTIONS_AUDIT)')
    details = Column(JSON, nullable=True,
                     comment='Détails bornés : identifiants, motifs. Jamais '
                             'de contenu de conversation ni de secret')
    ip = Column(String(100), nullable=True, comment='Adresse de l\'appelant')
    date = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True,
                  comment='Moment de l\'action')

    def __repr__(self):
        return f"<AuditLog(id={self.id}, action={self.action}, site={self.site_id})>"


def tracer_audit(
    db,
    action: str,
    user_id: Optional[int] = None,
    user_email: Optional[str] = None,
    site_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip: Optional[str] = None,
) -> None:
    """
    Écrit une ligne d'audit dans la transaction courante (pas de commit ici).

    Ne lève jamais : une panne d'audit est journalisée, pas propagée — mais
    elle est LOUD (logger.error) parce qu'une trace manquante est un défaut de
    conformité, pas du bruit.
    """
    try:
        ligne = AuditLog(
            user_id=user_id,
            user_email=(user_email or "")[:255] or None,
            site_id=(site_id or "")[:100] or None,
            action=(action or "")[:100],
            details=details or None,
            ip=(ip or "")[:100] or None,
        )
        db.add(ligne)
    except Exception as exc:  # pragma: no cover - filet
        logger.error("Audit : trace non écrite pour %s (%s)", action, exc)
        try:
            db.rollback()
        except Exception:
            pass

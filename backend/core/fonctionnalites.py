"""
Fondations d'extensibilité — feature flags, plans et abonnement (Mission 1).

CE QUE CE MODULE PORTE
----------------------
· La hiérarchie des plans (free < premium < pro) — les valeurs premium/pro
  EXISTENT mais rien ne les active encore : aucun paiement n'est branché ;
· le catalogue des fonctionnalités (flags) et sa seed IDEMPOTENTE au boot :
  la table `fonctionnalites` est remplie avec les flags connus, les canaux
  WhatsApp / RCS / Jeko y sont INACTIFS par défaut (principe : les fondations
  maintenant, l'activation plus tard) ;
· la dépendance FastAPI `exiger_fonctionnalite(cle)` : une route marquée par
  elle refuse 403 avec une RAISON EXPLICITE (jamais d'erreur silencieuse) ;
· la vue des fonctionnalités du compte, servie par GET /api/client/v1/me.

CONTRAT D'EXTENSION
-------------------
Ajouter une fonctionnalité premium = ajouter une entrée à
`FONCTIONNALITES_DEPART` (seed idempotente) + marquer la route avec
`exiger_fonctionnalite(...)`. L'app la voit automatiquement via /me
(fonctionnalites_actives / fonctionnalites_verrouillees). Recette complète :
docs/refonte-app-mia/EXTENSIBILITE.md.

AUCUNE CLÉ ICI : ce module ne contient aucune valeur de secret, aucune URL de
fournisseur en dur — tout passe par des variables d'environnement vides par
défaut (dépôt public, scripts/verifier-secrets.py au pre-push).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from backend.core.auth import compte_client_authentifie
from backend.core.database import get_db

# ============================================================
# PLANS
# ============================================================

PLAN_FREE = "free"
PLAN_PREMIUM = "premium"
PLAN_PRO = "pro"

#: Niveau de chaque plan. La valeur numérique sert aux comparaisons
#: « plan_minimum requis vs plan du compte ». Un plan inconnu en base est
#: traité comme free (1) pour la LECTURE (/me), et refusé à l'écriture
#: (POST /subscribe n'accepte que les plans connus).
HIERARCHIE_PLANS: Dict[str, int] = {
    PLAN_FREE: 1,
    PLAN_PREMIUM: 2,
    PLAN_PRO: 3,
}

#: Plans que POST /subscribe peut demander. `free` n'est PAS souscriptible :
#: il est le défaut de tout compte (refus explicite, cf. route).
PLANS_SOUSCRIPTIBLES = (PLAN_PREMIUM, PLAN_PRO)


def niveau_plan(plan: Optional[str]) -> int:
    """Niveau d'un plan, tolérant (None / vide / inconnu = free)."""
    return HIERARCHIE_PLANS.get((plan or "").strip().lower(), HIERARCHIE_PLANS[PLAN_FREE])


# ============================================================
# CATALOGUE DES FONCTIONNALITÉS (seed au boot)
# ============================================================

#: Les flags connus du produit. LA SEED EST IDEMPOTENTE : une ligne absente
#: est créée, une ligne présente n'est JAMAIS écrasée — l'activation d'un
#: canal ou d'une fonctionnalité par ePerformance (champ `active`) survit aux
#: redéploiements. Les trois flags premium sont créés INACTIFS : leur route
#: existe (pré-implémentée), leur activation est une décision du propriétaire.
FONCTIONNALITES_DEPART: List[Dict[str, Any]] = [
    {
        "cle": "notifications_push",
        "plan_minimum": PLAN_FREE,
        "active": True,
        "description": (
            "Notifications push de l'app (webpush) — inclus dans tous les plans ; "
            "canal opérationnel dès que les clés VAPID sont posées"
        ),
    },
    {
        "cle": "analytics_export",
        "plan_minimum": PLAN_FREE,
        "active": True,
        "description": (
            "Export des données de l'app (analytics du site) — inclus dans tous "
            "les plans ; sert d'exemple end-to-end du verrou par fonctionnalité"
        ),
    },
    {
        "cle": "ia_en_direct",
        "plan_minimum": PLAN_FREE,
        "active": True,
        "description": (
            "Mia en direct : conversation de test avec sa propre Mia "
            "(écran 10 de l'app)"
        ),
    },
    {
        "cle": "whatsapp_notifications",
        "plan_minimum": PLAN_PREMIUM,
        "active": False,
        "description": (
            "Notifications WhatsApp (Meta Cloud API) — pré-implémenté dans "
            "backend/chatbot/notifications.py, canal INACTIF tant que "
            "WHATSAPP_ENABLED n'est pas à true (décision du propriétaire)"
        ),
    },
    {
        "cle": "rcs_messages",
        "plan_minimum": PLAN_PREMIUM,
        "active": False,
        "description": (
            "Messages riches RCS — pré-implémenté (interface abstraite texte + "
            "cartes), canal INACTIF tant que RCS_ENABLED n'est pas à true ; "
            "fallback SMS déclaratif"
        ),
    },
    {
        "cle": "abonnement_jeko",
        "plan_minimum": PLAN_PREMIUM,
        "active": False,
        "description": (
            "Abonnement Jeko (sandbox) — flux prêt (souscription + webhook "
            "signé), INACTIF tant que les clés JEKO_* ne sont pas posées ; "
            "sans clés, POST /subscribe répond un état explicite et enregistre "
            "l'intention"
        ),
    },
]

_CLAIRES_CONNUES = {spec["cle"] for spec in FONCTIONNALITES_DEPART}


def seed_fonctionnalites(db: Optional[Session] = None) -> Dict[str, Any]:
    """
    Insère les flags manquants. IDEMPOTENT : exécuter deux fois ne fait rien.

    N'écrase JAMAIS une ligne existante : `active` et `plan_minimum` sont des
    décisions de gestion qui doivent survivre au redéploiement — la seed ne
    comble que les absences. Ouvre sa session si aucune n'est fournie (boot).
    """
    from backend.chatbot.models import Fonctionnalite

    fermer = False
    if db is None:
        from backend.core.database import SessionLocal

        db = SessionLocal()
        fermer = True
    try:
        existantes = {ligne.cle for ligne in db.query(Fonctionnalite).all()}
        ajoutees: List[str] = []
        for spec in FONCTIONNALITES_DEPART:
            if spec["cle"] in existantes:
                continue
            db.add(Fonctionnalite(**spec))
            ajoutees.append(spec["cle"])
        if ajoutees:
            db.commit()
        return {"ajoutees": ajoutees, "connues": sorted(_CLAIRES_CONNUES)}
    finally:
        if fermer:
            db.close()


# ============================================================
# VERROU — exception + réponse 403 explicite
# ============================================================


class FonctionnaliteVerrouillee(Exception):
    """
    Levée par le verrou quand une route exige une fonctionnalité inactive ou
    au-delà du plan du compte. Convertie par un gestionnaire d'exception
    (backend/api/app.py) en 403 dont le corps est EXPLICITE et PLAT :

        {"detail": "fonctionnalité verrouillée",
         "fonctionnalite": cle, "plan_requis": ..., "plan_actuel": ...,
         "raison": ...}

    Le corps plat (et non imbriqué sous `detail`) est le contrat de l'app :
    elle affiche l'écran d'upgrade avec le plan requis, sans parser un texte.
    """

    def __init__(self, cle: str, plan_requis: str, plan_actuel: str, raison: str):
        self.cle = cle
        self.plan_requis = plan_requis
        self.plan_actuel = plan_actuel
        self.raison = raison
        super().__init__(f"{cle} verrouillée : {raison}")


def _verifier_fonctionnalite(db: Session, cle: str, utilisateur) -> None:
    """Applique le verrou. Lève FonctionnaliteVerrouillee, jamais silencieux."""
    from backend.chatbot.models import Fonctionnalite

    plan_actuel = (utilisateur.plan or PLAN_FREE).strip().lower()
    fonctionnalite = db.query(Fonctionnalite).filter(Fonctionnalite.cle == cle).first()
    if fonctionnalite is None:
        # La table existe mais la seed n'a pas tourné (démarrage dégradé) :
        # on REFUSE fermé avec la raison — un refus clair vaut mieux qu'un
        # accès accordé par défaut.
        raise FonctionnaliteVerrouillee(
            cle=cle,
            plan_requis="?",
            plan_actuel=plan_actuel,
            raison="catalogue des fonctionnalités non initialisé (seed absente) — "
                   "redémarrage requis",
        )
    if not fonctionnalite.active:
        raise FonctionnaliteVerrouillee(
            cle=cle,
            plan_requis=fonctionnalite.plan_minimum,
            plan_actuel=plan_actuel,
            raison="fonctionnalité inactive (non activée par ePerformance)",
        )
    if niveau_plan(plan_actuel) < niveau_plan(fonctionnalite.plan_minimum):
        raise FonctionnaliteVerrouillee(
            cle=cle,
            plan_requis=fonctionnalite.plan_minimum,
            plan_actuel=plan_actuel,
            raison=f"plan {fonctionnalite.plan_minimum} requis (plan actuel : {plan_actuel})",
        )


def exiger_fonctionnalite(cle: str):
    """
    Dépendance FastAPI : verrou par fonctionnalité (compte-level).

    Usage sur une route de site — l'isolation DOIT passer avant le verrou
    (un étranger reçoit 404, pas la raison du verrou) ; utiliser alors
    `exiger_fonctionnalite_site(cle)` qui chaîne require_site_owner :

        @router.get("/sites/{site_id}/…")
        async def …(
            utilisateur: User = Depends(require_site_owner()),
            _verrou: None = Depends(exiger_fonctionnalite("…")),
        ):

    Une clé INCONNUE du catalogue est un défaut de code : la fabrique lève
    DÈS L'IMPORT (ValueError) — le smoke test pre-push et le démarrage
    l'affichent immédiatement, jamais en production sans rien dire.
    """
    if cle not in _CLAIRES_CONNUES:
        raise ValueError(
            f"exiger_fonctionnalite : clé inconnue « {cle} » — ajoutez-la à "
            f"FONCTIONNALITES_DEPART (backend/core/fonctionnalites.py). Clés "
            f"connues : {', '.join(sorted(_CLAIRES_CONNUES))}"
        )

    async def dependance(
        db: Session = Depends(get_db),
        utilisateur=Depends(compte_client_authentifie),
    ) -> None:
        _verifier_fonctionnalite(db, cle, utilisateur)

    return dependance


def exiger_fonctionnalite_site(cle: str, role_min: str):
    """
    Variante scoppée : ISOLATION MULTI-TENANT d'abord (require_site_owner),
    verrou ensuite. L'ordre fait partie du contrat : un compte qui demande un
    site étranger reçoit 404, quel que soit l'état du flag.
    """
    from backend.core.auth import require_site_owner

    if cle not in _CLAIRES_CONNUES:  # même échec d'import que la version simple
        raise ValueError(
            f"exiger_fonctionnalite_site : clé inconnue « {cle} » — ajoutez-la à "
            f"FONCTIONNALITES_DEPART (backend/core/fonctionnalites.py)."
        )

    proprietataire = require_site_owner(role_min)

    async def dependance(
        site_id: str,
        db: Session = Depends(get_db),
        utilisateur=Depends(proprietataire),
    ) -> None:
        # Ici, l'isolation a déjà été appliquée (404 avant toute autre réponse).
        _verifier_fonctionnalite(db, cle, utilisateur)

    return dependance


# ============================================================
# VUE DU COMPTE — servie par GET /api/client/v1/me
# ============================================================


def vue_fonctionnalites(db: Session, utilisateur) -> Dict[str, Any]:
    """
    Ce que le compte peut voir : son plan, les fonctionnalités ACTIVES pour
    lui (actives ET plan suffisant), les verrouillées avec leur plan requis.

    La forme retournée est celle du contrat /me (clés au premier niveau) :
    `plan`, `fonctionnalites_actives` (liste de clés),
    `fonctionnalites_verrouillees` ({cle, plan_requis, raison}).

    Ne lève pas : un problème de lecture renvoie un état explicite, /me doit
    rester disponible pendant le changement forcé du mot de passe.
    """
    from backend.chatbot.models import Fonctionnalite

    plan_actuel = (utilisateur.plan or PLAN_FREE).strip().lower()
    actives: List[str] = []
    verrouillees: List[Dict[str, str]] = []
    try:
        lignes = (
            db.query(Fonctionnalite).order_by(Fonctionnalite.cle).all()
        )
    except Exception:
        # /me ne doit jamais tomber à cause du catalogue : état lisible.
        return {
            "plan": plan_actuel,
            "fonctionnalites_actives": [],
            "fonctionnalites_verrouillees": [],
            "catalogue": "indisponible",
        }

    for ligne in lignes:
        if ligne.active and niveau_plan(plan_actuel) >= niveau_plan(ligne.plan_minimum):
            actives.append(ligne.cle)
        else:
            verrouillees.append(
                {
                    "cle": ligne.cle,
                    "plan_requis": ligne.plan_minimum,
                    "raison": (
                        "fonctionnalité inactive"
                        if not ligne.active
                        else f"plan {ligne.plan_minimum} requis"
                    ),
                }
            )
    return {
        "plan": plan_actuel,
        "fonctionnalites_actives": actives,
        "fonctionnalites_verrouillees": verrouillees,
    }

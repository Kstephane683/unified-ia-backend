"""
Webhooks fournisseurs — fondations d'extensibilité (Missions 1 et 3).

CE QUE CE ROUTER PORTE
----------------------
· POST /api/webhooks/jeko        — webhook d'abonnement du fournisseur Jeko
                                   (public, signature HMAC OBLIGATOIRE : sans
                                   JEKO_WEBHOOK_SECRET posé, TOUT appel
                                   reçoit 400 — un webhook non signé n'est
                                   jamais accepté) ;
· GET  /api/webhooks/whatsapp    — vérification Meta (hub.challenge, motif
                                   connu du projet) pour l'enregistrement du
                                   webhook dans Meta Business Manager ;
· POST /api/webhooks/whatsapp    — réception des statuts de livraison Meta
                                   (sent, delivered, read, failed) avec trace ;
                                   signature X-Hub-Signature-256 validée si
                                   WHATSAPP_APP_SECRET est posé.

RÈGLES DU PROJET APPLIQUÉES ICI
-------------------------------
· Aucune clé en dur : tout passe par des variables d'environnement, VIDES par
  défaut (dépôt public, verifier-secrets.py au pre-push) ;
· jamais d'exception qui remonte vers le fournisseur : toute erreur de
  contenu devient 400/422 explicite, toute trace est écrite même en cas de
  référence inconnue (200 — pas de tempête de relances) ;
· les traces ne contiennent jamais de secret ni de contenu de conversation.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

from backend.chatbot.models import Abonnement, ChatbotNotificationLog
from backend.core.audit import tracer_audit
from backend.core.database import get_db
from backend.core.fonctionnalites import PLAN_PREMIUM, PLAN_PRO

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["Webhooks fournisseurs"])


def _variable(nom: str) -> str:
    import os

    return (os.getenv(nom) or "").strip()


def _signature_valide(secret: str, corps: bytes, entete: Optional[str]) -> bool:
    """
    Vérifie HMAC-SHA256 du corps BRUT. Formats d'en-tête acceptés :
    `<hex>` et `sha256=<hex>` (les deux sont documentés dans le contrat
    EXTENSIBILITE.md). Comparaison à temps constant.
    """
    if not entete:
        return False
    recue = entete.strip()
    if recue.lower().startswith("sha256="):
        recue = recue[len("sha256="):].strip()
    calculee = hmac.new(secret.encode("utf-8"), corps, hashlib.sha256).hexdigest()
    return hmac.compare_digest(recue.lower(), calculee.lower())


# ============================================================
# Jeko — abonnements (Mission 1.7)
# ============================================================

_STATUTS_JEKO = ("en_attente", "actif", "annule", "echec")


@router.post("/jeko")
async def webhook_jeko(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Webhook du fournisseur d'abonnement Jeko (PUBLIC, signature OBLIGATOIRE).

    CONTRAT DE SIGNATURE : en-tête `X-Jeko-Signature: sha256=<hex>` où `<hex>`
    est le HMAC-SHA256 du corps brut avec JEKO_WEBHOOK_SECRET.

    · JEKO_WEBHOOK_SECRET absent → 400 (un webhook non signé n'est pas
      accepté, même pour « tester ») ;
    · signature invalide → 400 ;
    · corps non JSON → 400 ;
    · statut inconnu → 422 ;
    · référence d'abonnement inconnue → 200 `{"ok": false, ...}` (pas de
      tempête de relances), TRACÉE en audit ;
    · statut `actif` → le plan du compte est ÉLEVÉ au plan de l'abonnement
      (c'est le SEUL endroit où un plan est activé aujourd'hui).

    Toute transition est tracée dans le journal d'audit (jamais de secret).
    """
    corps = await request.body()
    secret = _variable("JEKO_WEBHOOK_SECRET")

    if not secret:
        return JSONResponse(
            status_code=400,
            content={
                "detail": "webhook non configuré : JEKO_WEBHOOK_SECRET absent — "
                          "un webhook non signé n'est pas accepté",
            },
        )
    if not _signature_valide(secret, corps, request.headers.get("x-jeko-signature")):
        return JSONResponse(
            status_code=400,
            content={"detail": "signature webhook invalide"},
        )

    try:
        donnees: Dict[str, Any] = json.loads(corps.decode("utf-8"))
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"detail": "corps non JSON"},
        )
    if not isinstance(donnees, dict):
        return JSONResponse(
            status_code=400,
            content={"detail": "corps JSON attendu : objet"},
        )

    reference = str(donnees.get("reference") or "").strip()
    statut = str(donnees.get("statut") or "").strip().lower()
    if not reference or not statut:
        return JSONResponse(
            status_code=422,
            content={"detail": "champs requis manquants : reference, statut"},
        )
    if statut not in _STATUTS_JEKO:
        return JSONResponse(
            status_code=422,
            content={
                "detail": f"statut inconnu : {statut} "
                          f"(acceptés : {', '.join(_STATUTS_JEKO)})",
            },
        )

    abonnement = (
        db.query(Abonnement)
        .filter(Abonnement.reference_fournisseur == reference)
        .first()
    )
    if abonnement is None:
        tracer_audit(
            db,
            "webhook_jeko",
            details={"reference": reference, "statut": statut,
                     "abonnement": "reference_inconnue"},
        )
        db.commit()
        return {
            "ok": False,
            "raison": "référence d'abonnement inconnue (aucune ligne mise à jour)",
        }

    ancien = abonnement.statut
    abonnement.statut = statut

    # SEUL endroit du backend où un plan est activé : le webhook signé du
    # fournisseur qui confirme l'abonnement.
    plan_eleve = None
    if statut == "actif" and abonnement.plan in (PLAN_PREMIUM, PLAN_PRO):
        from backend.core.models import User

        utilisateur = (
            db.query(User).filter(User.id == abonnement.user_id).first()
        )
        if utilisateur is not None:
            utilisateur.plan = abonnement.plan
            plan_eleve = utilisateur.plan

    tracer_audit(
        db,
        "webhook_jeko",
        user_id=abonnement.user_id,
        details={
            "reference": reference,
            "statut_avant": ancien,
            "statut": statut,
            "plan": abonnement.plan,
            "plan_eleve": plan_eleve,
        },
    )
    db.commit()

    return {"ok": True, "reference": reference, "statut": statut}


# ============================================================
# WhatsApp — vérification Meta + statuts de livraison (Mission 3.3)
# ============================================================


@router.get("/whatsapp")
async def verifier_webhook_whatsapp(request: Request):
    """
    Vérification de l'URL de webhook par Meta (motif connu du projet) :
    GET avec `hub.mode=subscribe`, `hub.verify_token`, `hub.challenge`.
    Répond le challenge EN BRUT si le jeton correspond à
    WHATSAPP_WEBHOOK_VERIFY_TOKEN, 403 sinon. Aucune écriture.
    """
    attendu = _variable("WHATSAPP_WEBHOOK_VERIFY_TOKEN")
    mode = request.query_params.get("hub.mode") or ""
    jeton = request.query_params.get("hub.verify_token") or ""
    challenge = request.query_params.get("hub.challenge") or ""

    if attendu and mode == "subscribe" and jeton and challenge and jeton == attendu:
        return PlainTextResponse(challenge)
    return JSONResponse(
        status_code=403,
        content={"detail": "vérification de webhook refusée (jeton absent ou incorrect)"},
    )


@router.post("/whatsapp")
async def statuts_whatsapp(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Réception des statuts de livraison Meta (sent, delivered, read, failed).

    SIGNATURE : si WHATSAPP_APP_SECRET est posé, l'en-tête
    `X-Hub-Signature-256: sha256=<hex>` (HMAC-SHA256 du corps brut) est
    VALIDÉ — 403 sinon. Sans secret, la réception est acceptée ET tracée
    comme non vérifiable : le canal est inactif par défaut, l'appel n'a
    aucun effet sur un envoi réel tant que WHATSAPP_ENABLED n'est pas à true.

    TRACE : chaque statut écrit une ligne `chatbot_notification_logs`
    (`sujet` préfixé `statut_fournisseur:`) — le diagnostic « ce message a-t-il
    été livré ? » reste possible après coup, c'est la vocation de la table.
    """
    corps = await request.body()
    secret = _variable("WHATSAPP_APP_SECRET")

    if secret:
        entete = request.headers.get("x-hub-signature-256")
        if not _signature_valide(secret, corps, entete):
            logger.warning("Webhook WhatsApp : signature X-Hub-Signature-256 invalide")
            return JSONResponse(
                status_code=403,
                content={"detail": "signature webhook invalide"},
            )

    try:
        donnees: Dict[str, Any] = json.loads(corps.decode("utf-8"))
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "corps non JSON"})

    recus = 0
    try:
        for entree in donnees.get("entry") or []:
            for changement in entree.get("changes") or []:
                valeur = changement.get("value") or {}
                destinataires = valeur.get("contacts") or [{}]
                numero_dest = str(
                    (destinataires[0] or {}).get("wa_id") or ""
                )
                for statut_obj in valeur.get("statuses") or []:
                    recus += 1
                    _tracer_statut_whatsapp(
                        db,
                        wamid=str(statut_obj.get("id") or ""),
                        statut=str(statut_obj.get("status") or ""),
                        destinataire=numero_dest,
                        erreur=(
                            ((statut_obj.get("errors") or [{}])[0]).get("message")
                            if statut_obj.get("errors")
                            else None
                        ),
                    )
    except Exception as exc:  # pragma: no cover - filet : jamais de 500 vers Meta
        logger.warning("Webhook WhatsApp : contenu illisible (%s)", exc)
        return JSONResponse(status_code=400, content={"detail": "contenu illisible"})

    return {"ok": True, "statuts_recus": recus}


def _tracer_statut_whatsapp(
    db: Session,
    wamid: str,
    statut: str,
    destinataire: str,
    erreur: Optional[str],
) -> None:
    """
    Écrit la trace d'un statut fournisseur. NE LÈVE JAMAIS (une trace
    impossible ne doit pas renvoyer une erreur à Meta).
    """
    try:
        succes = statut in ("sent", "delivered", "read")
        db.add(
            ChatbotNotificationLog(
                canal="whatsapp",
                statut="envoye" if succes else "echec",
                succes=succes,
                destinataire=destinataire or None,
                sujet=f"statut_fournisseur: {statut or 'inconnu'}",
                corps=None,
                code_erreur=None if succes else "fournisseur",
                erreur=(erreur or None) if not succes else None,
                identifiant_fournisseur=wamid or None,
                auteur="webhook_meta",
            )
        )
        db.commit()
    except Exception as exc:  # pragma: no cover - filet
        logger.error("Webhook WhatsApp : trace non écrite (%s)", exc)
        try:
            db.rollback()
        except Exception:
            pass

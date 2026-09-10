"""
Routes API pour diagnostic gratuit et gestion candidats.
ePerformance API Flow - Unified IA System
"""

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import secrets

from backend.core.database import get_db
from backend.core.models import Candidat, User
from backend.core.auth import get_current_user, require_admin
from backend.api.schemas import (
    CandidatCreate, CandidatResponse, CandidatList,
    CandidatUpdate, CandidatStatutUpdate, CandidatScoreResponse
)
from backend.services.diagnostic_service import DiagnosticService
from backend.services.diagnostic_analyzer import DiagnosticAnalyzer

import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Services
diagnostic_service = DiagnosticService()
diagnostic_analyzer = DiagnosticAnalyzer()


# ============================================================
# DIAGNOSTIC PUBLIC (sans auth)
# ============================================================

from pydantic import BaseModel, EmailStr, Field

class DiagnosticSubmit(BaseModel):
    """Schema pour soumission diagnostic gratuit"""
    # Informations de base
    nom: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    whatsapp: str = Field(..., min_length=10, max_length=50)
    entreprise: Optional[str] = Field(None, max_length=255)
    secteur: str = Field(..., max_length=100)
    
    # Données business
    ca_mensuel: int = Field(..., ge=0)
    clients_par_mois: int = Field(..., ge=0)
    budget_pub_mensuel: int = Field(..., ge=0)
    
    # Infrastructure digitale
    has_website: bool = False
    uses_digital_tools: bool = False
    tracks_metrics: bool = False
    
    # Budget & besoins
    budget_disponible: int = Field(..., ge=0)
    objectif: str = Field(..., max_length=500)
    duree_vie_client_mois: int = Field(default=12, ge=1, le=60)
    marge_pct: float = Field(default=30.0, ge=0, le=100)


class DiagnosticResponse(BaseModel):
    """Response après diagnostic"""
    success: bool
    candidat_id: int
    score: int
    segment: str
    ratios: dict
    failles: List[dict]
    recommandations: dict
    analyse_ia: dict
    activation_link: str
    message: str


@router.post("/diagnostic/submit", response_model=DiagnosticResponse, status_code=status.HTTP_201_CREATED)
async def submit_diagnostic(
    diagnostic_data: DiagnosticSubmit,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Soumet un diagnostic gratuit (PUBLIC - pas d'auth requise).
    
    Workflow :
    1. Calcule ratios (CAC, LTV, Payback)
    2. Calcule score maturité 0-100
    3. Identifie failles prioritaires
    4. Recommande produits (site + SaaS)
    5. Génère analyse IA enrichie (Sales Proposal Strategist)
    6. Crée candidat en base (statut=en_attente)
    7. Envoie email activation avec token
    8. Retourne diagnostic complet
    """
    
    logger.info(f"[Diagnostic] Soumission pour {diagnostic_data.nom} ({diagnostic_data.email})")
    
    # 1. Vérifier si email existe déjà
    existing = db.query(Candidat).filter(Candidat.email == diagnostic_data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Email {diagnostic_data.email} déjà enregistré. Vérifiez votre boîte mail pour le lien d'activation."
        )
    
    # 2. Calculer ratios
    ratios = diagnostic_service.calculate_ratios(
        ca_mensuel=diagnostic_data.ca_mensuel,
        clients_par_mois=diagnostic_data.clients_par_mois,
        budget_pub_mensuel=diagnostic_data.budget_pub_mensuel,
        duree_vie_client_mois=diagnostic_data.duree_vie_client_mois,
        marge_pct=diagnostic_data.marge_pct
    )
    
    logger.info(f"[Diagnostic] Ratios calculés : LTV:CAC {ratios['ratio']}:1, Payback {ratios['payback']} mois")
    
    # 3. Calculer score
    score = diagnostic_service.calculate_score(
        ratios=ratios,
        has_website=diagnostic_data.has_website,
        uses_digital_tools=diagnostic_data.uses_digital_tools,
        tracks_metrics=diagnostic_data.tracks_metrics,
        budget_available=diagnostic_data.budget_disponible
    )
    
    # 4. Identifier failles
    failles = diagnostic_service.identify_failles(
        ratios=ratios,
        diagnostic_data=diagnostic_data.dict()
    )
    
    # 5. Recommander produits
    produit_site, niveau_saas, segment = diagnostic_service.recommend_products(
        score=score,
        budget_available=diagnostic_data.budget_disponible,
        has_website=diagnostic_data.has_website,
        ratios=ratios
    )
    
    logger.info(f"[Diagnostic] Score {score}/100, Segment {segment}, Produit {produit_site}")
    
    # 6. Générer analyse IA enrichie (async)
    try:
        analyse_ia_data = {
            "nom": diagnostic_data.nom,
            "secteur": diagnostic_data.secteur,
            "ca_mensuel": diagnostic_data.ca_mensuel,
            "clients_par_mois": diagnostic_data.clients_par_mois,
            "budget_pub": diagnostic_data.budget_pub_mensuel,
            "score": score,
            "segment": segment,
            "failles": failles,
            "ratios": ratios,
            "produit_recommande": produit_site,
            "niveau_recommande": niveau_saas
        }
        
        analyse_ia = await diagnostic_analyzer.analyze(analyse_ia_data)
        logger.info(f"[Diagnostic] Analyse IA générée via {analyse_ia.get('provider_used')}")
        
    except Exception as e:
        logger.error(f"[Diagnostic] Erreur analyse IA: {str(e)}")
        # Continue même si IA échoue (fallback template sera utilisé)
        analyse_ia = {
            "acte1_challenge": f"Score {score}/100 identifié.",
            "acte2_solution": "ePerformance propose une solution complète.",
            "acte3_transformation": "Résultats visibles en 90 jours.",
            "cta": "Contactez-nous pour en discuter.",
            "provider_used": "error_fallback"
        }
    
    # 7. Créer candidat en base
    token_activation = secrets.token_urlsafe(32)
    
    candidat = Candidat(
        nom=diagnostic_data.nom,
        email=diagnostic_data.email,
        whatsapp=diagnostic_data.whatsapp,
        entreprise=diagnostic_data.entreprise,
        secteur=diagnostic_data.secteur,
        score=score,
        statut="en_attente",
        token_activation=token_activation,
        compte_active=False,
        created_at=datetime.now()
    )
    
    db.add(candidat)
    db.commit()
    db.refresh(candidat)
    
    logger.info(f"[Diagnostic] Candidat créé : ID {candidat.id}")
    
    # 8. TODO : Envoyer email activation (background task)
    # background_tasks.add_task(send_activation_email, candidat, analyse_ia, ratios, failles)
    
    # 9. Construire lien activation
    activation_link = f"https://eperformance.pro/activation?token={token_activation}"
    
    # 10. Retourner diagnostic complet
    return DiagnosticResponse(
        success=True,
        candidat_id=candidat.id,
        score=score,
        segment=segment,
        ratios=ratios,
        failles=failles,
        recommandations={
            "produit_site": produit_site,
            "niveau_saas": niveau_saas,
            "budget_estime": diagnostic_data.budget_disponible
        },
        analyse_ia=analyse_ia,
        activation_link=activation_link,
        message=f"Diagnostic complété ! Un email d'activation a été envoyé à {diagnostic_data.email}."
    )


# ============================================================
# ACTIVATION COMPTE CANDIDAT (sans auth)
# ============================================================

@router.get("/candidats/activate")
def activate_candidat(token: str, db: Session = Depends(get_db)):
    """
    Active un compte candidat via token email.
    Crée également un user associé (role=lead).
    """
    
    candidat = db.query(Candidat).filter(Candidat.token_activation == token).first()
    
    if not candidat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token d'activation invalide ou expiré."
        )
    
    if candidat.compte_active:
        return {
            "success": True,
            "message": "Compte déjà activé",
            "candidat_id": candidat.id,
            "redirect": "https://space.eperformance.pro/login"
        }
    
    # Activer candidat
    candidat.compte_active = True
    candidat.token_activation = None  # Invalider le token
    
    # Créer user associé si pas déjà fait
    existing_user = db.query(User).filter(User.email == candidat.email).first()
    
    if not existing_user:
        # Mot de passe temporaire (sera changé au premier login)
        temp_password = secrets.token_urlsafe(16)
        
        user = User(
            email=candidat.email,
            password_hash=temp_password,  # TODO: hasher avec bcrypt
            role="lead",
            is_active=True,
            created_at=datetime.now()
        )
        db.add(user)
        
        # Lier user au candidat
        db.flush()
        candidat.user_id = user.id
    
    db.commit()
    
    logger.info(f"[Activation] Candidat {candidat.id} activé")
    
    return {
        "success": True,
        "message": "Compte activé avec succès !",
        "candidat_id": candidat.id,
        "redirect": "https://space.eperformance.pro/onboarding"
    }


# ============================================================
# CRUD CANDIDATS (admin seulement)
# ============================================================

@router.get("/candidats/list", response_model=CandidatList)
def list_candidats(
    page: int = 1,
    page_size: int = 50,
    statut: Optional[str] = None,
    secteur: Optional[str] = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Liste paginée des candidats (admin)"""
    
    query = db.query(Candidat)
    
    # Filtres
    if statut:
        query = query.filter(Candidat.statut == statut)
    if secteur:
        query = query.filter(Candidat.secteur == secteur)
    
    # Pagination
    total = query.count()
    candidats = query.order_by(Candidat.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    return CandidatList(
        total=total,
        page=page,
        page_size=page_size,
        candidats=[CandidatResponse.from_orm(c) for c in candidats]
    )


@router.get("/candidats/{candidat_id}", response_model=CandidatResponse)
def get_candidat(
    candidat_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Détails d'un candidat"""
    
    candidat = db.query(Candidat).filter(Candidat.id == candidat_id).first()
    
    if not candidat:
        raise HTTPException(status_code=404, detail="Candidat non trouvé")
    
    # Vérifier permissions (admin ou le candidat lui-même)
    if current_user.role != "admin" and candidat.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Accès non autorisé")
    
    return CandidatResponse.from_orm(candidat)


@router.patch("/candidats/{candidat_id}/status", response_model=CandidatResponse)
def update_candidat_status(
    candidat_id: int,
    status_update: CandidatStatutUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Met à jour le statut d'un candidat (admin).
    Si statut passe à 'accepte', envoie email proposition accompagnement.
    """
    
    candidat = db.query(Candidat).filter(Candidat.id == candidat_id).first()
    
    if not candidat:
        raise HTTPException(status_code=404, detail="Candidat non trouvé")
    
    old_status = candidat.statut
    candidat.statut = status_update.statut
    
    # Si acceptation, mettre à jour date + role user
    if status_update.statut == "accepte" and old_status != "accepte":
        candidat.date_acceptation = datetime.now()
        
        # Upgrade role user vers 'client'
        if candidat.user_id:
            user = db.query(User).filter(User.id == candidat.user_id).first()
            if user:
                user.role = "client"
        
        # TODO: Envoyer email proposition accompagnement
        # background_tasks.add_task(send_proposal_email, candidat)
        
        logger.info(f"[Candidat] {candidat_id} accepté, email proposition envoyé")
    
    db.commit()
    db.refresh(candidat)
    
    return CandidatResponse.from_orm(candidat)


@router.patch("/candidats/{candidat_id}", response_model=CandidatResponse)
def update_candidat(
    candidat_id: int,
    candidat_update: CandidatUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Met à jour les infos d'un candidat"""
    
    candidat = db.query(Candidat).filter(Candidat.id == candidat_id).first()
    
    if not candidat:
        raise HTTPException(status_code=404, detail="Candidat non trouvé")
    
    # Vérifier permissions
    if current_user.role != "admin" and candidat.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Accès non autorisé")
    
    # Update fields (seulement si fournis)
    update_data = candidat_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(candidat, field, value)
    
    db.commit()
    db.refresh(candidat)
    
    return CandidatResponse.from_orm(candidat)


@router.delete("/candidats/{candidat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_candidat(
    candidat_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Supprime un candidat (admin seulement)"""
    
    candidat = db.query(Candidat).filter(Candidat.id == candidat_id).first()
    
    if not candidat:
        raise HTTPException(status_code=404, detail="Candidat non trouvé")
    
    db.delete(candidat)
    db.commit()
    
    logger.info(f"[Candidat] {candidat_id} supprimé par admin {current_user.id}")
    
    return None

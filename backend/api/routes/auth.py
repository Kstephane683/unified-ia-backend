"""
Authentication routes - ePerformance API Flow

Endpoints:
- POST /api/auth/register - Register new user
- POST /api/auth/login - Login (return JWT)
- POST /api/auth/refresh - Refresh JWT token
- GET /api/auth/me - Get current user details
"""

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime, timedelta

from backend.core.database import get_db
from backend.core.models import User, Candidat, FormationInscrit
from backend.core.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_user,
    verifier_secret_totp,
    ChiffrementIndisponible,
)

router = APIRouter()

#: Durée d'un jeton « rappel » (remember_me) — refonte app Mia, B1.
#: Session longue demandée par le plan (§3.3 : « session 30 jours »). Le
#: raccourcissement futur par ré-authentification (passkey après inactivité)
#: est une évolution côté app, pas backend.
JETON_RAPPEL_JOURS = 30


# ============================================================
# Pydantic Schemas
# ============================================================

class UserRegister(BaseModel):
    """Schema for user registration."""
    email: EmailStr
    password: str
    nom: str
    # SÉCURITÉ: le rôle est forcé côté serveur (jamais accepté du client)
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "password": "SecurePassword123",
                "nom": "John Doe",
                "role": "client"
            }
        }


class UserLogin(BaseModel):
    """Schema for user login."""
    email: EmailStr
    password: str
    # Refonte app Mia (B1/B2) — facultatifs, rétrocompatibles :
    remember_me: bool = False          # jeton « rappel » 30 jours
    totp_code: Optional[str] = None    # code 2FA si activée sur le compte


class Token(BaseModel):
    """Schema for JWT token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 86400  # 24h in seconds


class TokenConnexion(Token):
    """
    Réponse du login (refonte app Mia, B1).

    `must_change_password` : vrai tant que le mot de passe temporaire fourni à
    la livraison n'a pas été changé — l'app doit forcer l'écran de changement.
    Champ ADDITIF : les consommateurs existants (widget, console) l'ignorent
    sans aucune régression.
    """
    must_change_password: bool = False


class UserResponse(BaseModel):
    """Schema for user data response."""
    id: int
    email: str
    role: str
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None
    
    class Config:
        from_attributes = True


# ============================================================
# Routes
# ============================================================

def _verifier_2fa_si_requise(user: User, totp_code: Optional[str]) -> None:
    """
    Vérifie le second facteur si la 2FA est active sur le compte (B2).

    · 2FA active + code absent        → 401 `2fa_requise` (raison explicite ;
      l'app affiche alors le champ code, pas une erreur générique) ;
    · 2FA active + code invalide      → 401 « code 2FA invalide » ;
    · secret illisible (SECRET_KEY changée) → 403, échec FERMÉ : jamais de
      validation par défaut quand le second facteur ne peut pas être vérifié ;
    · bibliothèque pyotp absente      → 403, même échec fermé (état géré, pas
      une panne de démarrage : l'import est paresseux, règle du projet).
    """
    if not user.totp_enabled:
        return

    import pyotp  # import paresseux volontaire (règle du projet)

    if not (totp_code or "").strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="2fa_requise",
        )
    try:
        if not verifier_secret_totp(user.totp_secret, totp_code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="code 2FA invalide",
            )
    except ChiffrementIndisponible as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"2FA non vérifiable côté serveur : {exc}",
        )


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register_user(user_data: UserRegister, db: Session = Depends(get_db)):
    """
    Register a new user.
    
    Creates a new user account with hashed password.
    Returns JWT token for immediate login.
    
    Raises:
        HTTPException 400: If email already exists
    """
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create new user
    new_user = User(
        email=user_data.email,
        password_hash=get_password_hash(user_data.password),
        role='lead',  # SÉCURITÉ: whitelist serveur — les admins sont créés via SQL/CLI uniquement
        is_active=True,
        created_at=datetime.now(),
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # Create JWT token
    access_token = create_access_token(
        data={"sub": new_user.email, "role": new_user.role}
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": 86400,
    }


@router.post("/login", response_model=TokenConnexion)
def login_user(
    form_data: OAuth2PasswordRequestForm = Depends(),
    remember_me: bool = Form(False),
    totp_code: str = Form(""),
    db: Session = Depends(get_db),
):
    """
    Login user with email and password.

    Returns JWT token on success.

    OAuth2 compatible endpoint (username = email).

    Refonte app Mia (B1/B2) :
    - `remember_me` (formulaire, facultatif) → jeton « rappel » de 30 jours
      au lieu de la durée standard (ACCESS_TOKEN_EXPIRE_MINUTES) ;
    - si la 2FA est active sur le compte, un `totp_code` valide est exigé —
      sans code, la réponse est 401 avec la raison `2fa_requise` ;
    - la réponse expose `must_change_password` (changement forcé du mot de
      passe temporaire après provisionnement).

    Raises:
        HTTPException 401: If credentials are invalid / code 2FA absent
        HTTPException 403: If account disabled / 2FA invérifiable
    """
    # Find user by email (username field in OAuth2)
    user = db.query(User).filter(User.email == form_data.username).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify password
    if not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if account is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled"
        )

    # Second facteur (2FA TOTP) si activé sur le compte
    _verifier_2fa_si_requise(user, totp_code)

    # Update last login
    user.last_login = datetime.now()
    db.commit()

    # Jeton « rappel » : 30 jours si remember_me, sinon durée configurable
    if remember_me:
        duree = timedelta(days=JETON_RAPPEL_JOURS)
        expires_in = JETON_RAPPEL_JOURS * 86400
    else:
        from backend.core.auth import ACCESS_TOKEN_EXPIRE_MINUTES
        duree = None
        expires_in = ACCESS_TOKEN_EXPIRE_MINUTES * 60

    # Create JWT token
    access_token = create_access_token(
        data={"sub": user.email, "role": user.role},
        expires_delta=duree,
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "must_change_password": bool(user.must_change_password),
    }


@router.post("/login/json", response_model=TokenConnexion)
def login_user_json(login_data: UserLogin, db: Session = Depends(get_db)):
    """
    Login user with JSON body (alternative to OAuth2 form).

    Useful for frontend applications that prefer JSON.
    Mêmes évolutions B1/B2 que /login (remember_me, 2FA, must_change_password).

    Raises:
        HTTPException 401: If credentials are invalid / code 2FA absent
    """
    # Find user
    user = db.query(User).filter(User.email == login_data.email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )

    # Verify password
    if not verify_password(login_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )

    # Check if active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled"
        )

    # Second facteur (2FA TOTP) si activé sur le compte
    _verifier_2fa_si_requise(user, login_data.totp_code)

    # Update last login
    user.last_login = datetime.now()
    db.commit()

    # Jeton « rappel » : 30 jours si remember_me, sinon durée configurable
    if login_data.remember_me:
        duree = timedelta(days=JETON_RAPPEL_JOURS)
        expires_in = JETON_RAPPEL_JOURS * 86400
    else:
        from backend.core.auth import ACCESS_TOKEN_EXPIRE_MINUTES
        duree = None
        expires_in = ACCESS_TOKEN_EXPIRE_MINUTES * 60

    # Create token
    access_token = create_access_token(
        data={"sub": user.email, "role": user.role},
        expires_delta=duree,
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "must_change_password": bool(user.must_change_password),
    }


@router.get("/me", response_model=UserResponse)
def get_current_user_info(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get current authenticated user details.
    
    Requires valid JWT token in Authorization header.
    
    Raises:
        HTTPException 404: If user not found in database
    """
    user = db.query(User).filter(User.email == current_user["email"]).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return user


@router.post("/refresh", response_model=Token)
def refresh_token(current_user: dict = Depends(get_current_user)):
    """
    Refresh JWT token.
    
    Requires valid (non-expired) JWT token.
    Returns new token with extended expiration.
    """
    # Create new token
    access_token = create_access_token(
        data={"sub": current_user["email"], "role": current_user["role"]}
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": 86400,
    }


@router.post("/logout")
def logout_user():
    """
    Logout user (client-side token deletion).
    
    JWT tokens are stateless, so logout is handled client-side
    by deleting the token from storage.
    
    This endpoint is mainly for consistency and future token blacklisting.
    """
    return {
        "message": "Logged out successfully",
        "action": "Delete token from client storage"
    }

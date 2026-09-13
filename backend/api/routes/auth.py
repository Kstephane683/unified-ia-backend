"""
Authentication routes - ePerformance API Flow

Endpoints:
- POST /api/auth/register - Register new user
- POST /api/auth/login - Login (return JWT)
- POST /api/auth/refresh - Refresh JWT token
- GET /api/auth/me - Get current user details
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

from backend.core.database import get_db
from backend.core.models import User, Candidat, FormationInscrit
from backend.core.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_user,
)

router = APIRouter()


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


class Token(BaseModel):
    """Schema for JWT token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 86400  # 24h in seconds


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


@router.post("/login", response_model=Token)
def login_user(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Login user with email and password.
    
    Returns JWT token on success.
    
    OAuth2 compatible endpoint (username = email).
    
    Raises:
        HTTPException 401: If credentials are invalid
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
    
    # Update last login
    user.last_login = datetime.now()
    db.commit()
    
    # Create JWT token
    access_token = create_access_token(
        data={"sub": user.email, "role": user.role}
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": 86400,
    }


@router.post("/login/json", response_model=Token)
def login_user_json(login_data: UserLogin, db: Session = Depends(get_db)):
    """
    Login user with JSON body (alternative to OAuth2 form).
    
    Useful for frontend applications that prefer JSON.
    
    Raises:
        HTTPException 401: If credentials are invalid
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
    
    # Update last login
    user.last_login = datetime.now()
    db.commit()
    
    # Create token
    access_token = create_access_token(
        data={"sub": user.email, "role": user.role}
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": 86400,
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

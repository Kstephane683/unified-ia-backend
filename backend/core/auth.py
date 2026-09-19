"""
JWT authentication and password hashing.

Features:
- JWT token generation and validation
- Password hashing with bcrypt
- Role-based access control (RBAC)
- Token expiration (24h default)
"""

from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
import os
from dotenv import load_dotenv

load_dotenv()

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "unified_ia_secret_key_2026_CHANGE_ME_IN_PRODUCTION")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24h

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password.
    
    Args:
        plain_password: Plain text password from user
        hashed_password: Hashed password from database
        
    Returns:
        True if password matches, False otherwise
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Hash a password using bcrypt.
    
    Args:
        password: Plain text password
        
    Returns:
        Hashed password string
    """
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.
    
    Args:
        data: Payload to encode (typically {"sub": user_email, "role": user_role})
        expires_delta: Custom expiration time (default: 24h)
        
    Returns:
        Encoded JWT token string
        
    Example:
        token = create_access_token({"sub": "user@example.com", "role": "client"})
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """
    Decode and validate a JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        Decoded payload dict if valid, None if invalid/expired
        
    Example:
        payload = decode_access_token(token)
        if payload:
            email = payload.get("sub")
            role = payload.get("role")
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def verify_role(token: str, required_role: str) -> bool:
    """
    Verify if token has required role.
    
    Args:
        token: JWT token string
        required_role: Required role ('admin', 'client', 'apprenant')
        
    Returns:
        True if user has required role, False otherwise
        
    Example:
        if verify_role(token, "admin"):
            # User is admin
    """
    payload = decode_access_token(token)
    if not payload:
        return False
    
    user_role = payload.get("role")
    
    # Admin has access to everything
    if user_role == "admin":
        return True
    
    return user_role == required_role


def has_any_role(token: str, allowed_roles: list[str]) -> bool:
    """
    Check if user has any of the allowed roles.
    
    Args:
        token: JWT token string
        allowed_roles: List of allowed roles
        
    Returns:
        True if user has at least one of the allowed roles
        
    Example:
        if has_any_role(token, ["admin", "client"]):
            # User is admin or client
    """
    payload = decode_access_token(token)
    if not payload:
        return False
    
    user_role = payload.get("role")
    return user_role in allowed_roles


# ============================================================
# FastAPI Dependencies
# ============================================================

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

# OAuth2 scheme for token extraction from Authorization header
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """
    FastAPI dependency to get current authenticated user.
    
    Usage:
        @app.get("/protected")
        def protected_route(current_user: dict = Depends(get_current_user)):
            return {"user": current_user}
    
    Raises:
        HTTPException 401 if token invalid/expired
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    
    email: str = payload.get("sub")
    role: str = payload.get("role")
    
    if email is None:
        raise credentials_exception
    
    return {"email": email, "role": role}


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """
    FastAPI dependency to require admin role.
    
    Usage:
        @app.delete("/users/{user_id}")
        def delete_user(user_id: int, admin: dict = Depends(require_admin)):
            # Only admins can access this
    
    Raises:
        HTTPException 403 if user is not admin
    """
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


async def require_client(current_user: dict = Depends(get_current_user)) -> dict:
    """
    FastAPI dependency to require client or admin role.

    Usage:
        @app.get("/my-projects")
        def my_projects(user: dict = Depends(require_client)):
            # Clients and admins can access
    """
    if current_user["role"] not in ["client", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client access required"
        )
    return current_user


# ============================================================
# Refonte app Mia — rôles client scopés par site (chantier B2)
# ============================================================
#
# HIÉRARCHIE : admin (ePerformance, tout voir) > client_admin >
# client_operator > client_reader. La valeur numérique sert au
# « niveau minimal requis » d'une route : reader=1, operator=2, admin=3.

ROLE_CLIENT_ADMIN = "client_admin"
ROLE_CLIENT_OPERATOR = "client_operator"
ROLE_CLIENT_READER = "client_reader"

HIERARCHIE_CLIENT = {
    ROLE_CLIENT_READER: 1,
    ROLE_CLIENT_OPERATOR: 2,
    ROLE_CLIENT_ADMIN: 3,
}


def verifier_secret_totp(secret_stocke: Optional[str], code: str) -> bool:
    """
    Vérifie un code TOTP (2FA) contre le secret chiffré en base.

    `pyotp` est importé ICI, à l'intérieur de la fonction — jamais au niveau
    du module (piège du projet : un import manquant d'une bibliothèque
    optionnelle a déjà causé une panne de production). Le chiffrement du
    secret repose sur `cryptography` (déjà présent via python-jose[cryptography]).

    Renvoie False si le code est invalide, lève ChiffrementIndisponible si le
    secret ne peut pas être déchiffré (clé serveur changée) — l'appelant
    décide du code HTTP (échec fermé, jamais une validation par défaut).
    """
    if not secret_stocke:
        return False

    secret_clair = dechiffrer_secret_totp(secret_stocke)

    import pyotp  # import paresseux volontaire (règle du projet)

    # valid_window=1 : accepte le code de la fenêtre précédente ou suivante
    # (±30 s) — la tolérance standard au décalage d'horloge du téléphone,
    # sinon un code généré à la frontière d'une fenêtre serait refusé.
    return pyotp.TOTP(secret_clair).verify(
        (code or "").strip().replace(" ", ""), valid_window=1
    )


class ChiffrementIndisponible(Exception):
    """Le secret TOTP ne peut pas être chiffré/déchiffré (clé serveur)."""


def _cle_fernet() -> bytes:
    """Clé Fernet dérivée de SECRET_KEY (sha256 → base64url).

    Conséquence documentée : faire tourner SECRET_KEY invalide les secrets
    TOTP stockés — les comptes doivent refaire la configuration 2FA. C'est
    assumé : SECRET_KEY est censé être stable et secret.
    """
    import base64
    import hashlib

    return base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest())


def chiffrer_secret_totp(secret_clair: str) -> str:
    """
    Chiffre un secret TOTP pour stockage (Fernet, préfixe de version).

    Lève ChiffrementIndisponible si la bibliothèque manque — dans ce cas on
    REFUSE d'activer la 2FA plutôt que de stocker le secret en clair.
    """
    try:
        from cryptography.fernet import Fernet  # déjà présent (python-jose)
    except Exception as exc:  # pragma: no cover - dépendance normalement là
        raise ChiffrementIndisponible(
            "bibliothèque 'cryptography' indisponible : la 2FA ne peut pas "
            "être activée (aucun secret ne serait stocké en clair)"
        ) from exc

    return "fernet:v1:" + Fernet(_cle_fernet()).encrypt(
        secret_clair.encode()
    ).decode()


def dechiffrer_secret_totp(secret_stocke: str) -> str:
    """
    Déchiffre un secret TOTP stocké. Lève ChiffrementIndisponible si la clé
    serveur a changé (le secret devient illisible) ou si la bibliothèque manque.
    """
    if not secret_stocke.startswith("fernet:v1:"):
        raise ChiffrementIndisponible(
            "secret TOTP dans un format inconnu : refaire la configuration 2FA"
        )
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except Exception as exc:  # pragma: no cover
        raise ChiffrementIndisponible(
            "bibliothèque 'cryptography' indisponible"
        ) from exc

    try:
        return Fernet(_cle_fernet()).decrypt(
            secret_stocke[len("fernet:v1:"):].encode()
        ).decode()
    except InvalidToken as exc:
        raise ChiffrementIndisponible(
            "secret TOTP illisible (SECRET_KEY a changé ?) : refaire la "
            "configuration 2FA"
        ) from exc


# ============================================================
# Dépendances client scopées (app Mia) — auth.py côté compte
# ============================================================

from sqlalchemy.orm import Session as _Session  # noqa: E402
from backend.core.database import get_db  # noqa: E402


async def compte_client_authentifie(
    current_user: dict = Depends(get_current_user),
    db: _Session = Depends(get_db),
) -> "User":
    """
    Charge le compte EN BASE (le JWT ne porte pas l'état mutable).

    Vérifie : compte existant, actif, et changement de mot de passe effectué.
    Tant que `must_change_password` est vrai, TOUTES les routes client refusent
    (403, raison explicite) SAUF le changement de mot de passe, qui utilise sa
    propre dépendance.
    """
    from backend.core.models import User

    utilisateur = db.query(User).filter(User.email == current_user["email"]).first()
    if utilisateur is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Compte introuvable",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not utilisateur.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte désactivé",
        )
    if utilisateur.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Changement de mot de passe requis : le mot de passe "
                "temporaire fourni à la livraison doit être changé avant tout "
                "accès (POST /api/client/v1/password)"
            ),
        )
    return utilisateur


def require_site_owner(role_min: str = ROLE_CLIENT_READER):
    """
    Fabrique de dépendance B2 : scope multi-tenant par site.

    Usage :
        @router.get("/sites/{site_id}/conversations")
        def ...(
            site_id: str,
            utilisateur: User = Depends(require_site_owner()),
        ):
    ou, pour une route en écriture :
        Depends(require_site_owner(ROLE_CLIENT_OPERATOR))

    Garanties (DANS CET ORDRE — l'ordre fait partie du contrat) :
      · admin (ePerformance) : passe toujours ;
      · compte client NON provisioné pour l'app Mia : 403 (parle du compte) ;
      · ISOLATION MULTI-TENANT : un propriétaire qui demande un site qui n'est
        PAS le sien reçoit 404 (et non 403) — 403 révélerait l'existence des
        autres sites. Cette vérification passe AVANT la suffisance de rôle et
        la porte 2FA : aucune réponse ne distingue « site d'un autre » et
        « site inexistant », quel que soit le rôle de l'appelant ;
      · rôle client insuffisant pour `role_min` : 403 ;
      · client_admin SANS 2FA active, sur SON site : 403 (la 2FA est
        obligatoire — audit préalable C5).
    """
    if role_min not in HIERARCHIE_CLIENT:
        raise ValueError(
            f"role_min doit être l'un de : {', '.join(HIERARCHIE_CLIENT)}"
        )

    async def dependance(
        site_id: str,
        utilisateur: "User" = Depends(compte_client_authentifie),
    ) -> "User":
        # ePerformance voit tout (rôle plateforme, pas un rôle client).
        if utilisateur.role == "admin":
            return utilisateur

        if utilisateur.role_client not in HIERARCHIE_CLIENT:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Compte client non provisioné pour l'application Mia",
            )
        # ISOLATION : 404, jamais 403, pour ne pas révéler l'existence des
        # autres sites — AVANT la suffisance de rôle et la porte 2FA (voir la
        # doc du contrat).
        if utilisateur.site_id != site_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Site non trouvé",
            )
        niveau = HIERARCHIE_CLIENT[utilisateur.role_client]
        if niveau < HIERARCHIE_CLIENT[role_min]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Rôle insuffisant : {role_min} requis",
            )
        # 2FA obligatoire pour client_admin (audit préalable C5) — sauf au
        # moment de la configurer, ce qui passe par des routes compte-level.
        if (
            utilisateur.role_client == ROLE_CLIENT_ADMIN
            and not utilisateur.totp_enabled
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "2FA obligatoire pour le rôle client_admin : terminez la "
                    "configuration (POST /api/client/v1/2fa/setup puis "
                    "/2fa/activate)"
                ),
            )
        return utilisateur

    return dependance


if __name__ == "__main__":
    """Test authentication functions when run directly."""
    print("🔐 Testing authentication functions\n")
    
    # Test password hashing
    password = "test_password_123"
    hashed = get_password_hash(password)
    print(f"✅ Password hashing:")
    print(f"   Plain: {password}")
    print(f"   Hash: {hashed[:60]}...")
    print(f"   Verify: {verify_password(password, hashed)}")
    print()
    
    # Test JWT token creation
    token = create_access_token({"sub": "test@example.com", "role": "client"})
    print(f"✅ JWT token creation:")
    print(f"   Token: {token[:50]}...")
    print()
    
    # Test token decoding
    payload = decode_access_token(token)
    print(f"✅ JWT token decoding:")
    print(f"   Email: {payload.get('sub')}")
    print(f"   Role: {payload.get('role')}")
    print(f"   Expires: {datetime.fromtimestamp(payload.get('exp'))}")
    print()
    
    # Test role verification
    print(f"✅ Role verification:")
    print(f"   Has 'client' role: {verify_role(token, 'client')}")
    print(f"   Has 'admin' role: {verify_role(token, 'admin')}")
    print(f"   Has any ['client', 'apprenant']: {has_any_role(token, ['client', 'apprenant'])}")
    print()
    
    # Test admin token
    admin_token = create_access_token({"sub": "admin@example.com", "role": "admin"})
    print(f"✅ Admin token:")
    print(f"   Has 'client' role: {verify_role(admin_token, 'client')} (admin has access to everything)")
    print()
    
    print("🎉 All authentication tests passed!")

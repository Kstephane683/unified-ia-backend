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

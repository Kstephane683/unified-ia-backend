"""
FastAPI main application.

Unified IA System - Backend API
"""

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import os
from dotenv import load_dotenv

from backend.core.database import get_db, check_connection
from backend.core.auth import get_current_user

load_dotenv()

# Configuration
ENV = os.getenv("ENV", "development")
DEBUG = os.getenv("DEBUG", "True").lower() == "true"

# CORS origins - inclure les domaines du site ePerformance
DEFAULT_ORIGINS = [
    "http://localhost:8080",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:4173",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:4173",
    "https://kstephane683.github.io",
    "https://eperformance.pro",
    "https://www.eperformance.pro",
    "https://api.eperformance.pro",
]
CORS_ORIGINS = os.getenv("CORS_ORIGINS", ",".join(DEFAULT_ORIGINS)).split(",")

# FastAPI app
app = FastAPI(
    title="ePerformance API Flow",
    description="Plateforme IA unifiée - Backend API pour l'écosystème ePerformance",
    version="1.0.0",
    docs_url="/docs" if DEBUG else None,  # Disable docs in production
    redoc_url="/redoc" if DEBUG else None,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Health & Status
# ============================================================

@app.get("/")
def root():
    """Root endpoint - API info."""
    return {
        "name": "ePerformance API Flow",
        "version": "1.0.0",
        "status": "operational",
        "environment": ENV,
        "docs": "/docs" if DEBUG else "disabled",
        # SHA du commit déployé (observabilité déploiements Railway)
        "commit": os.getenv("RAILWAY_GIT_COMMIT_SHA", "local")[:10],
    }


@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint.
    Tests database connectivity.
    """
    from sqlalchemy import text
    
    db_status = "ok"
    try:
        # Simple query to test DB
        db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    return {
        "status": "healthy" if db_status == "ok" else "unhealthy",
        "database": db_status,
        "environment": ENV,
    }


@app.get("/api/status")
def api_status():
    """
    API status with more details (no DB query).
    """
    return {
        "api": "operational",
        "version": "1.0.0",
        "environment": ENV,
        "debug": DEBUG,
        "cors_origins": CORS_ORIGINS,
    }


# ============================================================
# Protected example route
# ============================================================

@app.get("/api/me")
def get_me(current_user: dict = Depends(get_current_user)):
    """
    Get current authenticated user info.
    Requires valid JWT token in Authorization header.
    
    Example:
        curl -H "Authorization: Bearer <token>" http://localhost:8000/api/me
    """
    return {
        "email": current_user["email"],
        "role": current_user["role"],
    }


# ============================================================
# Startup & Shutdown Events
# ============================================================

@app.on_event("startup")
async def startup_event():
    """Run on application startup."""
    print("\n" + "="*60)
    print("🚀 ePerformance API Flow - Démarrage...")
    print("="*60)
    print(f"📊 Environment: {ENV}")
    print(f"🐛 Debug mode: {DEBUG}")
    print(f"🌐 CORS origins: {CORS_ORIGINS}")
    
    # Check database connection
    if check_connection():
        print("✅ Database connection: OK")
    else:
        print("❌ Database connection: FAILED")
        print("⚠️  API will start but database operations will fail")
    
    print("="*60)
    print("📖 API Documentation: http://localhost:8000/docs")
    print("🔍 Health check: http://localhost:8000/health")
    print("="*60 + "\n")


@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown."""
    print("\n🛑 ePerformance API Flow - Arrêt...")


# ============================================================
# Import route modules
# ============================================================

from backend.api.routes import auth, diagnostic, subscriptions_legacy, products_legacy, chatbot
from backend.api.routes import admin_chatbot

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(diagnostic.router, prefix="/api", tags=["Diagnostic & Candidats"])
app.include_router(subscriptions_legacy.router, tags=["Subscriptions"])  # Prefix already in router
app.include_router(products_legacy.router, tags=["Products"])  # Prefix already in router

# Phase 1-S1.4 : Chatbot IA (Deep Chat + 29 agents)
app.include_router(chatbot.router, tags=["Chatbot IA"])  # Prefix already in router (/api/chatbot)
app.include_router(admin_chatbot.router, tags=["Chatbot IA"])  # Prefix already in router (/api/chatbot/admin)


# ============================================================
# Création idempotente des tables manquantes (au boot)
# ============================================================
# Les tables chatbot avaient été créées par script, mais jamais les tables
# core (users…) → login 500 "relation users does not exist" en production.
# create_all n'ajoute QUE les tables absentes — aucune migration destructrice.
try:
    from backend.core.database import init_db

    init_db()
    print("[startup] init_db OK — tables vérifiées/créées")
except Exception as _db_init_error:  # l'app doit démarrer même si la DB tarde
    print(f"[startup] init_db ÉCHEC (non bloquant): {_db_init_error}")


if __name__ == "__main__":
    """
    Run directly for development (not recommended for production).
    Use uvicorn command instead:
        uvicorn backend.api.app:app --reload --host 0.0.0.0 --port 8000
    """
    import uvicorn
    
    uvicorn.run(
        "backend.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=DEBUG,
        log_level="info" if DEBUG else "warning",
    )

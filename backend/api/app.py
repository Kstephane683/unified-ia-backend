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
    "https://mia.eperformance.pro",
]
CORS_ORIGINS = os.getenv("CORS_ORIGINS", ",".join(DEFAULT_ORIGINS)).split(",")

# FastAPI app
app = FastAPI(
    title="ePerformance API Flow",
    description="Plateforme IA unifiée - Backend API pour l'écosystème ePerformance",
    version="1.0.0",
    docs_url="/docs" if DEBUG else None,  # Disable docs in production
    redoc_url=None,  # Disable redoc in production
    openapi_url="/openapi.json" if DEBUG else None,  # Disable openapi schema in production
)


# ============================================================
# Rate limiting simple (in-memory, par instance) — P1 sécurité
# ============================================================
import time as _time
from collections import defaultdict, deque

from fastapi.responses import JSONResponse

# chemin → (max requêtes, fenêtre secondes)
_RATE_LIMITS = {
    "/api/chatbot/message": (12, 60),      # coût LLM
    "/api/auth/register": (5, 300),        # spam de comptes
    "/api/auth/login": (10, 300),          # brute force
    # Recherche blog (tâche 6.8) : aucun coût LLM, mais l'index est en mémoire
    # et la route est publique — la limite borne l'abus sans gêner une saisie
    # au fil de la frappe (1 requête par seconde en moyenne).
    "/api/chatbot/search": (60, 60),
    # Abonnement push (P3-PUSH) : route PUBLIQUE qui ÉCRIT en base, sans jeton —
    # un visiteur n'a pas de compte, il ne peut donc pas s'authentifier. La
    # limite borne l'insertion en masse ; un navigateur, lui, s'abonne une fois
    # et ne réessaie qu'après un changement de clés.
    "/api/chatbot/push/subscribe": (20, 60),
    # Désabonnement : même logique, et la route n'écrit que si l'endpoint exact
    # est connu — le seul effet d'un balayage est une lecture sans résultat.
    "/api/chatbot/push/unsubscribe": (30, 60),
    # App Mia (refonte, B1/B2) : routes de CREANCE du compte client. Le
    # changement de mot de passe et la bascule 2FA sont exactement les cibles
    # d'une attaque par force brute sur un compte provisioné — bornées.
    "/api/client/v1/password": (5, 300),
    "/api/client/v1/2fa/setup": (10, 300),
    "/api/client/v1/2fa/activate": (10, 300),
    "/api/client/v1/2fa/disable": (5, 300),
    # Fondations d'extensibilité : la souscription déclenche un appel au
    # fournisseur (coût réel) — bornée comme une route de créance.
    "/api/client/v1/subscribe": (5, 300),
    # Tracking applicatif : batch au retour du réseau (une app sainement
    # configurée envoie un batch par session, pas par frappe) — la limite
    # borne l'insertion en masse sans gêner l'usage réel.
    "/api/client/v1/analytics/event": (30, 60),
    # Webhooks PUBLICS : la limite borne le balayage ; les fournisseurs
    # légitimes (Jeko, Meta) ne rejouent pas à ce rythme.
    "/api/webhooks/jeko": (30, 60),
    "/api/webhooks/whatsapp": (60, 60),
}
_rate_bucket: dict = defaultdict(deque)


@app.middleware("http")
async def rate_limit_middleware(request, call_next):
    rule = _RATE_LIMITS.get(request.url.path)
    if rule:
        client_ip = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown")
        )
        now = _time.time()
        key = (request.url.path, client_ip)
        bucket = _rate_bucket[key]
        while bucket and bucket[0] < now - rule[1]:
            bucket.popleft()
        if len(bucket) >= rule[0]:
            return JSONResponse(
                {"detail": "Trop de requêtes. Réessayez dans un instant."},
                status_code=429,
            )
        bucket.append(now)
    return await call_next(request)

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
from backend.api.routes import client as client_routes
from backend.api.routes import webhooks as webhooks_routes

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(diagnostic.router, prefix="/api", tags=["Diagnostic & Candidats"])
app.include_router(subscriptions_legacy.router, tags=["Subscriptions"])  # Prefix already in router
app.include_router(products_legacy.router, tags=["Products"])  # Prefix already in router

# Phase 1-S1.4 : Chatbot IA (Deep Chat + 29 agents)
app.include_router(chatbot.router, tags=["Chatbot IA"])  # Prefix already in router (/api/chatbot)
app.include_router(admin_chatbot.router, tags=["Chatbot IA"])  # Prefix already in router (/api/chatbot/admin)
# Refonte app Mia (B1-B4) : API client v1, scopée par site (require_site_owner).
app.include_router(client_routes.router, tags=["Client v1 (app Mia)"])  # Prefix /api/client/v1
# Fondations d'extensibilité : webhooks fournisseurs (Jeko signé, statuts
# WhatsApp) — publics, avec signature obligatoire/validée (cf. routes/webhooks.py).
app.include_router(webhooks_routes.router, tags=["Webhooks fournisseurs"])  # Prefix /api/webhooks


# ============================================================
# Verrou par fonctionnalité — 403 EXPLICITE (fondations, Mission 1)
# ============================================================
from fastapi.requests import Request as _Request  # noqa: E402

from backend.core.fonctionnalites import FonctionnaliteVerrouillee  # noqa: E402


@app.exception_handler(FonctionnaliteVerrouillee)
async def fonctionnalite_verrouillee_handler(
    request: _Request, exc: FonctionnaliteVerrouillee
):
    """Corps PLAT du 403, contrat de l'app : l'écran d'upgrade lit
    plan_requis sans parser un texte. Jamais d'erreur silencieuse."""
    return JSONResponse(
        status_code=403,
        content={
            "detail": "fonctionnalité verrouillée",
            "fonctionnalite": exc.cle,
            "plan_requis": exc.plan_requis,
            "plan_actuel": exc.plan_actuel,
            "raison": exc.raison,
        },
    )


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
    # Migration idempotente des COLONNES ajoutées par la refonte app Mia :
    # create_all ne modifie JAMAIS une table existante (piège du projet) —
    # les nouvelles colonnes de users et chatbot_sites exigent un
    # ALTER TABLE explicite, cf. backend/core/migrations_boot.py.
    from backend.core.migrations_boot import appliquer_migrations

    rapport = appliquer_migrations()
    if rapport["colonnes_ajoutees"] or rapport["index_crees"]:
        print(f"[startup] migration colonnes : {rapport}")
    else:
        print("[startup] migration colonnes : rien à faire (schéma à jour)")

    # Seed IDEMPOTENTE du catalogue des fonctionnalités (fondations,
    # Mission 1) : crée les flags manquants, n'écrase JAMAIS une ligne
    # existante — les activations décidées par ePerformance survivent aux
    # redéploiements. Non bloquant : un échec de seed est affiché, l'app
    # démarre (les routes verrouillées répondront un refus explicite).
    from backend.core.fonctionnalites import seed_fonctionnalites

    try:
        rapport_seed = seed_fonctionnalites()
        print(f"[startup] seed fonctionnalités : {rapport_seed}")
    except Exception as _seed_error:
        print(f"[startup] seed fonctionnalités ÉCHEC (non bloquant): {_seed_error}")
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

#!/bin/bash
# ePerformance — Smoke test OBLIGATOIRE avant push (leçon de l'incident du 17/09)
# Vérifie que le module FastAPI s'importe — aurait détecté le NameError en 2 s.
set -e
cd "$(dirname "$0")/.."
echo "[smoke-test] Import du module backend..."
python3 - << 'PYEOF'
import sys
sys.path.insert(0, '.')
try:
    from backend.api.routes import chatbot, admin_chatbot
    from backend.api import app as app_module
    assert app_module.app is not None
    print("[smoke-test] OK — application FastAPI importable")
except Exception as e:
    print(f"[smoke-test] ECHEC: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
echo "[smoke-test] Compilation py_compile de tous les fichiers modifiés..."
python3 -m compileall -q backend/ > /dev/null
echo "[smoke-test] Recherche de secrets dans les fichiers suivis..."
python3 scripts/verifier-secrets.py
echo "[smoke-test] Parité avec la copie Docker (contrat C12)..."
if [ -d /home/ballo/OX6A/docker-unified/unified-ia-backend ]; then
  python3 scripts/verifier-parite-docker.py
else
  echo "[smoke-test] ATTENTION — copie Docker absente sur cette machine : parité NON VÉRIFIÉE."
  echo "[smoke-test] Le dossier docker-unified/ est le backend de remplacement de Railway :"
  echo "[smoke-test] si tu travailles sur une autre machine, la parité doit être vérifiée sur celle qui l'héberge."
fi
echo "[smoke-test] PASS — push autorisé"

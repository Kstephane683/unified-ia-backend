#!/usr/bin/env python3
"""Verificateur de secrets — bloque un push qui exposerait une cle.

Lecon de l'incident du 18/09 : deux cles de production (DeepSeek et passerelle
Claude) etaient ecrites en clair dans trois fichiers versionnes d'un depot
GitHub PUBLIC. La fuite est active tant que les cles ne sont pas revoquees, et
un fichier reecrit ne repare rien — l'historique conserve la valeur.

Ce controle ne remplace donc pas la rotation : il empeche la recidive.

Usage:
    python3 scripts/verifier-secrets.py                  # tous les fichiers suivis
    python3 scripts/verifier-secrets.py fichier1 fichier2 # fichiers cibles
"""

from __future__ import annotations

import re
import subprocess
import sys

# Motifs de secrets reels. Les prefixes sont decoupes pour que ce fichier ne
# declenche pas son propre controle.
MOTIFS: list[tuple[str, re.Pattern[str]]] = [
    ("cle OpenAI / compatible", re.compile(r"\bsk" + r"-[A-Za-z0-9_-]{24,}")),
    ("jeton GitHub", re.compile(r"\bgh[pousr]" + r"_[A-Za-z0-9]{30,}")),
    ("jeton Slack", re.compile(r"\bxox[baprs]" + r"-[A-Za-z0-9-]{10,}")),
    ("cle AWS", re.compile(r"\bAKIA" + r"[0-9A-Z]{16}\b")),
    ("cle Google", re.compile(r"\bAIza" + r"[A-Za-z0-9_-]{35}\b")),
    ("jeton Telegram", re.compile(r"\b[0-9]{8,12}:" + r"AA[A-Za-z0-9_-]{30,}")),
    ("cle privee PEM", re.compile(r"-----BEGIN [A-Z ]*" + r"PRIVATE KEY-----")),
    # Mot de passe dans une URL de connexion. On exclut les hotes locaux et les
    # mots de passe courts : ce sont des identifiants de developpement, pas des
    # secrets — un garde-fou qui crie au loup finit par etre contourne.
    (
        "mot de passe en URL",
        re.compile(r"://[^/\s:@]+:[^/\s:@]{8,}@(?!(?:localhost|127\.0\.0\.1)\b)"),
    ),
]

# Fichiers ou un motif est legitime (documentation, exemples, ce script).
EXCLUSIONS = {
    "scripts/verifier-secrets.py",
    ".env.example",
}

EXTENSIONS_TEXTE = {
    ".md", ".py", ".sh", ".json", ".yml", ".yaml", ".txt", ".js", ".ts",
    ".tsx", ".jsx", ".vue", ".css", ".html", ".ini", ".cfg", ".conf", ".toml",
    ".env", ".sql", ".php",
}


def fichiers_suivis() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    )
    return [ligne for ligne in out.stdout.splitlines() if ligne.strip()]


def fichier_texte(chemin: str) -> bool:
    """Un fichier sans extension connue est ignore (binaires, images, archives)."""
    nom = chemin.rsplit("/", 1)[-1]
    if "." not in nom:
        return False
    return f".{nom.rsplit('.', 1)[-1].lower()}" in EXTENSIONS_TEXTE


def masquer(valeur: str) -> str:
    """Ne jamais recracher un secret en clair, meme dans un message d'erreur."""
    return valeur[:6] + "." * 8 + f"({len(valeur)} car.)"


def analyser(chemin: str) -> list[tuple[int, str, str]]:
    """Retourne [(numero_ligne, nom_du_motif, valeur_masquee)]."""
    try:
        contenu = open(chemin, encoding="utf-8", errors="ignore").read()
    except (OSError, IsADirectoryError):
        return []
    trouves = []
    for numero, ligne in enumerate(contenu.splitlines(), 1):
        for nom, motif in MOTIFS:
            for correspondance in motif.finditer(ligne):
                trouves.append((numero, nom, masquer(correspondance.group(0))))
    return trouves


def main() -> int:
    cibles = sys.argv[1:] or fichiers_suivis()
    cibles = [c for c in cibles if c not in EXCLUSIONS and fichier_texte(c)]

    alertes: list[tuple[str, int, str, str]] = []
    for chemin in cibles:
        for numero, nom, valeur in analyser(chemin):
            alertes.append((chemin, numero, nom, valeur))

    if not alertes:
        print(f"[secrets] PASS — aucun secret detecte ({len(cibles)} fichier(s))")
        return 0

    print("[secrets] ECHEC — secret(s) en clair dans un fichier versionne :", file=sys.stderr)
    for chemin, numero, nom, valeur in alertes:
        print(f"  {chemin}:{numero}  {nom}  {valeur}", file=sys.stderr)
    print(
        "\n[secrets] Un secret ecrit dans un depot PUBLIC doit etre considere comme"
        "\n[secrets] compromis : reecrire le fichier ne repare rien, l'historique le"
        "\n[secrets] conserve. Revoquez la cle chez le fournisseur, puis referencez-la"
        "\n[secrets] par variable d'environnement.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

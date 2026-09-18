#!/usr/bin/env python3
"""Verificateur de parite : backend Railway (source) <-> copie Docker.

`docker-unified/unified-ia-backend/` n'est pas un bac a sable : c'est le backend
qui remplacera Railway sur un serveur dedie. Un ecart est un defaut de
production — le jour du basculement, ce qui manque est perdu. C'est l'objet du
contrat C12 : toute modification du backend Railway doit etre repliquee dans
Docker dans le meme cycle.

Sortie :
    0 = parite
    1 = ecart (liste des divergences)
    2 = erreur de mesure (jamais un succes)

Usage :
    python3 scripts/verifier-parite-docker.py
    python3 scripts/verifier-parite-docker.py --source /chemin --cible /chemin
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

SOURCE_DEFAUT = "/home/ballo/OX6A/unified-ia-backend"
CIBLE_DEFAUT = "/home/ballo/OX6A/docker-unified/unified-ia-backend"

# Artefacts regeneres : jamais compares.
EXCLUS_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".mypy_cache"}
EXCLUS_SUFFIXES = {".pyc", ".pyo"}

# Fichiers qui n'existent QUE dans la copie Docker et ne doivent jamais
# disparaitre. Une copie naive de la source les effacerait.
PROPRES_A_DOCKER = ("Dockerfile", ".dockerignore", "docker-compose.yml", ".env")


def empreintes(racine: Path) -> dict[str, str]:
    """Chemin relatif -> md5, en ignorant les artefacts regeneres."""
    resultat: dict[str, str] = {}
    for chemin, dirs, fichiers in os.walk(racine):
        dirs[:] = [d for d in dirs if d not in EXCLUS_DIRS]
        for nom in fichiers:
            if Path(nom).suffix in EXCLUS_SUFFIXES:
                continue
            complet = Path(chemin) / nom
            relatif = str(complet.relative_to(racine))
            try:
                resultat[relatif] = hashlib.md5(complet.read_bytes()).hexdigest()
            except OSError as erreur:
                print(f"[parite] ERREUR DE MESURE — {relatif}: {erreur}", file=sys.stderr)
                sys.exit(2)
    return resultat


def variables_lues_par_le_code(source: Path) -> set[str]:
    """Variables d'environnement que le code lit reellement."""
    variables: set[str] = set()
    backend = source / "backend"
    if not backend.exists():
        return variables
    motifs = (
        re.compile(r"os\.getenv\(\s*['\"]([A-Z_][A-Z0-9_]*)['\"]"),
        re.compile(r"os\.environ(?:\.get)?[\[(]\s*['\"]([A-Z_][A-Z0-9_]*)['\"]"),
        re.compile(r"self\.get\(\s*['\"]([A-Z_][A-Z0-9_]*)['\"]"),
        re.compile(r"config\.get\(\s*['\"]([A-Z_][A-Z0-9_]*)['\"]"),
    )
    for chemin, dirs, fichiers in os.walk(backend):
        dirs[:] = [d for d in dirs if d not in EXCLUS_DIRS]
        for nom in fichiers:
            if not nom.endswith(".py"):
                continue
            try:
                contenu = (Path(chemin) / nom).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for motif in motifs:
                variables |= set(motif.findall(contenu))
    return variables


def variables_declarees(env: Path) -> set[str]:
    if not env.exists():
        return set()
    declarees = set()
    for ligne in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        correspondance = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=", ligne)
        if correspondance:
            declarees.add(correspondance.group(1))
    return declarees


def main() -> int:
    analyseur = argparse.ArgumentParser(description="Parite backend Railway <-> copie Docker")
    analyseur.add_argument("--source", default=SOURCE_DEFAUT)
    analyseur.add_argument("--cible", default=CIBLE_DEFAUT)
    options = analyseur.parse_args()

    source, cible = Path(options.source), Path(options.cible)
    for nom, chemin in (("source", source), ("cible", cible)):
        if not chemin.is_dir():
            print(f"[parite] ERREUR DE MESURE — {nom} introuvable : {chemin}", file=sys.stderr)
            return 2

    empreintes_source = empreintes(source)
    empreintes_cible = empreintes(cible)

    # Les fichiers propres a Docker sont retires de la comparaison, mais leur
    # presence est verifiee juste apres : leur disparition est un incident.
    for nom in PROPRES_A_DOCKER:
        empreintes_cible.pop(nom, None)

    # Une comparaison sur zero fichier est une erreur de mesure, jamais un
    # succes : un garde-fou qui valide le vide ne garde rien.
    if not empreintes_source:
        print(f"[parite] ERREUR DE MESURE — 0 fichier trouve dans {source}", file=sys.stderr)
        return 2

    manquants = sorted(set(empreintes_source) - set(empreintes_cible))
    superflus = sorted(set(empreintes_cible) - set(empreintes_source))
    divergents = sorted(
        f for f in set(empreintes_source) & set(empreintes_cible)
        if empreintes_source[f] != empreintes_cible[f]
    )

    echec = False

    for nom in PROPRES_A_DOCKER:
        if not (cible / nom).exists():
            print(f"[parite] ECHEC — fichier propre a Docker disparu : {nom}", file=sys.stderr)
            echec = True

    if manquants or superflus or divergents:
        echec = True
        print("[parite] ECHEC — ecart entre le backend Railway et la copie Docker :", file=sys.stderr)
        for f in manquants:
            print(f"[parite]   MANQUANT dans Docker      : {f}", file=sys.stderr)
        for f in divergents:
            print(f"[parite]   DIVERGENT                : {f}", file=sys.stderr)
        for f in superflus:
            print(f"[parite]   ABSENT DE LA SOURCE      : {f}", file=sys.stderr)
        print(
            "[parite] Replique la modification dans docker-unified/ dans le MEME cycle"
            " (contrat C12). Le dossier est le backend de remplacement de Railway.",
            file=sys.stderr,
        )

    # Couverture des variables d'environnement : le .env est propre a chaque
    # environnement (URL de base de donnees differente), il ne peut donc pas
    # etre identique. Ce qui doit etre identique, c'est la CONNAISSANCE : toute
    # variable lue par le code doit etre declaree, sinon l'ecart de comportement
    # ne se voit qu'au premier symptome.
    lues = variables_lues_par_le_code(source)
    declarees = variables_declarees(cible / ".env")
    non_declarees = sorted(lues - declarees)
    if non_declarees:
        echec = True
        print(
            f"[parite] ECHEC — {len(non_declarees)} variable(s) lue(s) par le code"
            " et absente(s) du .env Docker :",
            file=sys.stderr,
        )
        for v in non_declarees:
            print(f"[parite]   NON DECLAREE : {v}", file=sys.stderr)

    if echec:
        return 1

    print(
        f"[parite] PASS — arborescences identiques ({len(empreintes_source)} fichiers, md5)"
        f" · {len(lues)} variables lues par le code, toutes declarees"
    )
    print("[parite] PASS — Dockerfile, .dockerignore, docker-compose.yml, .env presents")
    return 0


if __name__ == "__main__":
    sys.exit(main())

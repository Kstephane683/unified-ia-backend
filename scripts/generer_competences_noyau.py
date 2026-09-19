#!/usr/bin/env python3
"""
Génère le snapshot des compétences sectorielles consommé par le backend.

SOURCE DE VÉRITÉ : le NOYAU `agent-ia-web/eperf_core/sectors.py` (lecture
seule). Le backend Railway ne contient PAS le noyau — un import runtime est
donc impossible en production. Ce script est exécuté À LA MAIN quand le noyau
évolue : il lit `sectors.py`, en extrait les données de référence (intention,
faq_themes, item) et réécrit `backend/chatbot/competences_noyau.py` (fichier
VERSIONNÉ, importable partout, jamais édité à la main).

Contrat (audit préalable C1, plan §6 B3) : la landing et l'app consomment le
contenu sectoriel du noyau, jamais le réécrivent. Le snapshot porte la date de
génération et l'empreinte du fichier source — une divergence entre les deux
se voit immédiatement.

Usage :
    python3 scripts/generer_competences_noyau.py
    python3 scripts/generer_competences_noyau.py --noyau /chemin/agent-ia-web
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
DEFAUT_NOYAU = RACINE.parent / "agent-ia-web"
CIBLE = RACINE / "backend" / "chatbot" / "competences_noyau.py"


def charger_secteurs(chemin_sectors: Path):
    """Charge `sectors.py` SANS l'installer : le noyau reste lecture seule."""
    spec = importlib.util.spec_from_file_location("eperf_core_sectors", chemin_sectors)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"sectors.py illisible : {chemin_sectors}")
    module = importlib.util.module_from_spec(spec)
    # Les dataclasses du noyau résolvent leur module via sys.modules —
    # enregistrement requis avant exec (sinon AttributeError dans
    # dataclasses._is_type).
    sys.modules.setdefault(spec.name, module)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module.SECTEURS


def formatter(valeur: str) -> str:
    return repr(valeur)


def main() -> int:
    parseur = argparse.ArgumentParser()
    parseur.add_argument("--noyau", default=str(DEFAUT_NOYAU))
    arguments = parseur.parse_args()

    chemin_sectors = Path(arguments.noyau) / "eperf_core" / "sectors.py"
    if not chemin_sectors.is_file():
        print(f"ERREUR : {chemin_sectors} introuvable", file=sys.stderr)
        return 2

    secteurs = charger_secteurs(chemin_sectors)
    empreinte = hashlib.sha256(chemin_sectors.read_bytes()).hexdigest()[:16]

    lignes = [
        '"""',
        "Compétences sectorielles de Mia — SNAPSHOT GÉNÉRÉ, NE PAS ÉDITER.",
        "",
        f"Source : agent-ia-web/eperf_core/sectors.py (sha256:{empreinte}).",
        "Régénérer par : python3 scripts/generer_competences_noyau.py",
        "",
        "POURQUOI UN SNAPSHOT ET PAS UN IMPORT",
        "-------------------------------------",
        "Le noyau (agent-ia-web) n'est pas déployé sur Railway : importer",
        "`sectors.py` au runtime planterait la production. Ce fichier est la",
        "copie versionnée des données de référence (contenu PUBLIC du noyau :",
        "nom du secteur, intention, thèmes FAQ, item). Le noyau reste la source",
        "de vérité : toute évolution passe par lui, puis par une régénération.",
        "",
        "Ces données alimentent GET /api/client/v1/sites/{site_id}/competences",
        "(écran 8 de l'app Mia : ce que Mia sait faire dans le métier du site).",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "SECTEURS_CORE: dict[str, dict] = {",
    ]

    for slug in sorted(secteurs):
        s = secteurs[slug]
        item = s.item
        lignes.append(f'    {slug!r}: {{')
        lignes.append(f'        "nom": {formatter(s.nom)},')
        lignes.append(f'        "intention": {formatter(s.intention)},')
        lignes.append('        "faq_themes": (')
        for theme in s.faq_themes:
            lignes.append(f'            {formatter(theme)},')
        lignes.append('        ),')
        if item is not None:
            lignes.append('        "item": {')
            lignes.append(f'            "nom": {formatter(item.nom)},')
            lignes.append(f'            "nom_pluriel": {formatter(item.nom_pluriel)},')
            lignes.append(f'            "unite": {formatter(item.unite)},')
            lignes.append('        },')
        else:
            lignes.append('        "item": None,')
        lignes.append('    },')

    lignes.append("}")
    lignes.append("")

    CIBLE.write_text("\n".join(lignes), encoding="utf-8")
    print(f"Snapshot écrit : {CIBLE}")
    print(f"Secteurs générés : {len(secteurs)} ({', '.join(sorted(secteurs))})")
    print(f"Source : {chemin_sectors} (sha256:{empreinte})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

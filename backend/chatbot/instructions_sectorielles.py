"""
Instructions sectorielles du chatbot (chantier G du lot du 24/09).

Chaque site client peut déclarer son secteur (`chatbot_sites.sector` — colonne
posée par la migration boot). Quand il l'est, Mia reçoit un bloc d'instructions
adapté : le ton du métier, l'intention, les thèmes de questions fréquentes et
le vocabulaire produit.

SOURCE CANONIQUE — règle G.2, « ne pas inventer » :
- l'**intention**, les **thèmes FAQ** et le **vocabulaire produit** viennent de
  `agent-ia-web/eperf_core/sectors.py` via le fichier généré
  `secteurs_canoniques.json` (script : `scripts/generer-secteurs-canoniques.py`,
  qui est la traçabilité : aucune donnée n'y est réécrite à la main) ;
- le **ton** n'est pas porté par `sectors.py` : c'est une décision produit,
  assumée et documentée ici — un mappage fermé de 12 secteurs, sans invention
  de capacité (« Mia répond », jamais « Mia exécute » — règle C2).
"""

import json
from pathlib import Path
from typing import Optional

# Ton par secteur — décision produit (le noyau ne porte pas cette donnée).
# Court, opérationnel, sans promesse d'exécution.
TONS: dict = {
    "vitrine": "professionnel et clair",
    "beaute": "chaleureux et attentionné",
    "restauration": "convivial, avec un vocabulaire de carte et de service",
    "hotellerie": "hospitalier et rassurant",
    "sante": "sobre, précis et prudent — jamais de conseil médical",
    "education": "pédagogue et encourageant",
    "immobilier": "professionnel, avec le vocabulaire de la visite et du financement",
    "evenementiel": "enthousiaste et organisé",
    "ecommerce": "commercial et orienté produit",
    "mlm": "motivant, avec le vocabulaire du réseau et du parrainage",
    "tourisme": "évocateur et pratique",
    "artisan": "concret et de proximité",
}

_CIBLE = Path(__file__).resolve().parent / "secteurs_canoniques.json"
_cache: Optional[dict] = None


def charger() -> Optional[dict]:
    """Charge le fichier canonique une fois. None si absent ou illisible."""
    global _cache
    if _cache is not None:
        return _cache
    try:
        document = json.loads(_CIBLE.read_text(encoding="utf-8"))
        _cache = document.get("secteurs") or {}
    except Exception:
        _cache = {}
    return _cache


def bloc_instructions(sector: Optional[str]) -> Optional[str]:
    """Bloc d'instructions sectorielles pour le prompt de Mia, ou None.

    Le secteur inconnu ne produit RIEN (comportement inchangé) — jamais une
    instruction générique inventée.
    """
    if not sector:
        return None
    secteurs = charger()
    donnees = secteurs.get((sector or "").strip().lower())
    if not donnees:
        return None

    ton = TONS.get((sector or "").strip().lower())
    lignes = ["# SECTEUR DU SITE", ""]
    if ton:
        lignes.append(f"Ton de conversation : {ton}.")
    lignes.append(f"Métier du site : {donnees.get('nom')} — {donnees.get('intention')}")

    themes = donnees.get("faq_themes") or []
    if themes:
        lignes.append(
            "Questions fréquentes du métier, celles que les visiteurs posent : "
            + ", ".join(themes) + "."
        )
    vocab = donnees.get("vocabulaire_produit") or {}
    objet = vocab.get("objet")
    if objet:
        pluriel = vocab.get("objet_pluriel") or objet
        lignes.append(
            f"Le contenu principal du site : {objet.lower()} (au pluriel : "
            f"{pluriel.lower()}). Parlez du contenu du site avec ses mots."
        )
    cta = donnees.get("cta_primaire")
    if cta:
        lignes.append(f"Action proposée par le site : « {cta} » — orientez le visiteur vers elle.")

    lignes.append("")
    return "\n".join(lignes)

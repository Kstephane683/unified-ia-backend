"""
Liens directs du site dans le chat (lot D du 24/09) — DÉTERMINISTE, ZÉRO CRÉDIT LLM.

Quand le message du visiteur exprime une intention de navigation ou d'achat
(« faire un diagnostic », « combien ça coûte », « je veux acheter »), le chatbot
attache à sa réponse les liens cliquables des pages réelles du site du client,
accompagnés d'une phrase qui dit pourquoi on y va. Objectif économique annoncé
par le propriétaire : rediriger vers des pages qui existent au lieu de laisser
le LLM régénérer une prose à chaque fois.

Règles de conception :
- **Aucun appel LLM** : déclencheurs lexicaux et intents classifiés uniquement.
- **Aucun lien mort** : le catalogue ne référence que des pages du gabarit
  eperformance (vérifiées dans le dépôt du site) ; si `site_url` est absent
  pour ce tenant, aucun lien n'est produit — un lien relatif pointerait vers
  le domaine du widget (iframe), jamais vers le site hôte.
- **Multi-tenant** : les liens sont composés depuis `ChatbotSite.site_url` du
  site appelant. Chaque site obtient ses propres liens.
- **Additif et jamais levant** : toute erreur renvoie une liste vide — la
  réponse du chatbot ne dépend jamais de ce module.
"""

from typing import Dict, List, Optional
from urllib.parse import urljoin

# Catalogue des liens candidats. `chemin` : page réelle du gabarit eperformance
# (site-eperformance/ — vérifiées au 24/09) ; `mots` : déclencheurs lexicaux
# (sous-chaînes, minuscules, accents inclus) ; `intents` : intents classifiés
# qui suffisent à eux seuls à produire le lien.
CATALOGUE: List[Dict] = [
    {
        "cle": "diagnostic",
        "chemin": "diagnostic_eperformance.html",
        "label": "Faire un diagnostic gratuit",
        "phrase": "Le diagnostic analyse votre présence en ligne et vous est envoyé sous 48 h.",
        "mots": ["diagnostic", "audit", "bilan", "evaluation", "évaluation", "gratuit"],
        "intents": ["diagnostic_request", "lead_qualification"],
    },
    {
        "cle": "ia",
        "chemin": "ia.html",
        "label": "Découvrir l'assistante IA Mia",
        "phrase": "La page présente ce que l'assistante IA peut faire pour un site comme le vôtre.",
        "mots": ["chatbot", "assistant", "mia", "intelligence artificielle", "ia pour"],
        "intents": ["chatbot_inquiry"],
    },
    {
        "cle": "site-web",
        "chemin": "site-web.html",
        "label": "Voir la création de site web",
        "phrase": "La page détaille les sites vitrine et les délais de mise en ligne.",
        "mots": ["site web", "site vitrine", "création de site", "creation de site", "site internet"],
        "intents": ["web_design"],
    },
    {
        "cle": "automatisation",
        "chemin": "automatisation.html",
        "label": "Voir les automatisations",
        "phrase": "La page montre ce qui peut être automatisé : relances, suivis, publications.",
        "mots": ["automatis", "relance", "workflow"],
        "intents": ["automation"],
    },
    {
        "cle": "formation",
        "chemin": "formation.html",
        "label": "Voir les formations IA",
        "phrase": "Les formations existent en présentiel et à distance, pour équipes et indépendants.",
        "mots": ["formation", "formation ia", "apprendre ia", "atelier"],
        "intents": ["training_inquiry"],
    },
    {
        "cle": "ebook",
        "chemin": "ebook.html",
        "label": "Voir les guides (ebooks)",
        "phrase": "Les guides sont téléchargeables immédiatement après achat.",
        "mots": ["ebook", "guide", "livre", "télécharger", "telecharger"],
        "intents": ["ebook_inquiry"],
    },
]

# Intention d'achat (D.3) : mots qui, sans réponse du LLM, signifient que le
# visiteur veut agir — le diagnostic est l'étape d'achat standard du gabarit
# (il n'existe PAS de page tarifs publique : proposer une page inexistante
# serait un lien mort, et inventer des prix une violation de la règle C2).
MOTS_ACHAT = [
    "acheter", "achat", "prix", "tarif", "coût", "cout", "combien",
    "devis", "commander", "souscrire", "payer", "boucler", "ça coûte", "ca coute",
]

# Le lien produit pour une intention d'achat : le diagnostic (qualifie et
# débouche sur une offre chiffrée). Le produit « Mia » accompagne si pertinent.
LIEN_ACHAT = "diagnostic"


def _normaliser(texte: str) -> str:
    return (texte or "").lower()


def liens_pour(
    site_url: Optional[str],
    message: str,
    intent: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Renvoie les liens à attacher à la réponse — liste vide si rien ne joue.

    Chaque lien : {url, label, phrase}. `url` est absolu (site du tenant) ;
    sans `site_url`, la fonction renvoie [] — jamais de lien relatif.
    """
    try:
        if not site_url:
            return []
        base = site_url if site_url.endswith("/") else site_url + "/"
        texte = _normaliser(message)
        intent_n = _normaliser(intent)

        selection: List[Dict] = []
        vues = set()

        def ajouter(item: Dict) -> None:
            if item["cle"] in vues:
                return
            vues.add(item["cle"])
            selection.append(
                {
                    "url": urljoin(base, item["chemin"]),
                    "label": item["label"],
                    "phrase": item["phrase"],
                }
            )

        # 1. Les intents classifiés suffisent (détection gratuite, déjà faite).
        for item in CATALOGUE:
            if intent_n and intent_n in [_normaliser(i) for i in item["intents"]]:
                ajouter(item)

        # 2. Intention d'achat (D.3) : toujours au moins le diagnostic.
        if any(m in texte for m in MOTS_ACHAT):
            for item in CATALOGUE:
                if item["cle"] == LIEN_ACHAT:
                    ajouter(item)

        # 3. Déclencheurs lexicaux par page.
        for item in CATALOGUE:
            if any(m in texte for m in item["mots"]):
                ajouter(item)

        # Garde de volume : au-delà de 3 liens, le message devient un annuaire.
        return selection[:3]
    except Exception:  # pragma: no cover — jamais lever (contrat du module)
        return []

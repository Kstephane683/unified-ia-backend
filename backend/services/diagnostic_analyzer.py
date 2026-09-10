"""
Service Diagnostic avec analyse IA enrichie.
Utilise Sales Proposal Strategist + Email Marketing Strategist.

ePerformance API Flow - Unified IA System
"""

import json
import logging
from typing import Dict, Any, Tuple, Optional
from datetime import datetime
from backend.core.ai_client import get_ai_client

logger = logging.getLogger(__name__)


class DiagnosticAnalyzer:
    """
    Analyse diagnostic avec agents IA experts.
    Agent: Sales Proposal Strategist (win themes + 3 actes)
    """
    
    def __init__(self):
        self.ai_client = get_ai_client()
    
    async def analyze(self, diagnostic_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyse complète diagnostic avec IA.
        
        Args:
            diagnostic_data: {
                "nom": "...",
                "secteur": "...",
                "ca_mensuel": 2500000,
                "clients_par_mois": 40,
                "budget_pub": 300000,
                "score": 65,
                "segment": "tiede",
                "failles": [...],
                "ratios": {...}
            }
        
        Returns:
            {
                "acte1_challenge": "...",
                "acte2_solution": "...",
                "acte3_transformation": "...",
                "win_themes": ["...", "...", "..."],
                "cta": "...",
                "roi_projected": {...},
                "provider_used": "claude_gateway"
            }
        """
        
        prompt = self._build_proposal_prompt(diagnostic_data)
        system = self._build_system_prompt()
        
        try:
            content, provider = await self.ai_client.generate(
                prompt=prompt,
                system_prompt=system,
                response_format="json",
                diagnostic_data=diagnostic_data
            )
            
            # Parser JSON response
            analysis = self._parse_analysis(content, diagnostic_data)
            analysis["provider_used"] = provider
            
            logger.info(f"[DiagnosticAnalyzer] Analyse générée via {provider}")
            return analysis
            
        except Exception as e:
            logger.error(f"[DiagnosticAnalyzer] Erreur: {str(e)}")
            # Fallback vers analyse template
            return self._generate_template_analysis(diagnostic_data)
    
    def _build_proposal_prompt(self, data: Dict[str, Any]) -> str:
        """Construit le prompt Sales Proposal Strategist"""
        
        nom = data.get("nom", "Prospect")
        secteur = data.get("secteur", "votre secteur")
        score = data.get("score", 0)
        segment = data.get("segment", "tiede")
        
        ratios = data.get("ratios", {})
        cac = ratios.get("cac", 0)
        ltv = ratios.get("ltv", 0)
        ratio_ltv_cac = ratios.get("ratio", 0)
        payback = ratios.get("payback", 0)
        marge = ratios.get("marge", 30)
        
        failles = data.get("failles", [])
        faille1 = failles[0] if len(failles) > 0 else {"titre": "Non identifiée", "description": ""}
        faille2 = failles[1] if len(failles) > 1 else {"titre": "Non identifiée", "description": ""}
        faille3 = failles[2] if len(failles) > 2 else {"titre": "Non identifiée", "description": ""}
        
        produit = data.get("produit_recommande", "Site Web Professionnel 250k FCFA")
        niveau = data.get("niveau_recommande", "Essentielle 75k/mois")
        
        return f"""Tu es Sales Proposal Strategist expert, architecte de propositions gagnantes.

## Contexte Prospect
- Nom : {nom}
- Secteur : {secteur}
- CA mensuel : {data.get('ca_mensuel', 0):,} FCFA
- Clients/mois : {data.get('clients_par_mois', 0)}
- Score maturité : {score}/100
- Segment : {segment} (chaud 75-100 / tiède 50-74 / froid 25-49)

## Données Calculées
- CAC : {cac:,} FCFA
- LTV : {ltv:,} FCFA
- Ratio LTV:CAC : {ratio_ltv_cac}:1
- Payback : {payback} mois
- Marge : {marge}%

## Failles Identifiées
1. {faille1['titre']} - {faille1['description'][:200]}
2. {faille2['titre']} - {faille2['description'][:200]}
3. {faille3['titre']} - {faille3['description'][:200]}

## Mission
Génère une analyse stratégique structurée en 3 actes pour convaincre {nom} d'acheter {produit} puis de souscrire à {niveau}.

### Acte I : Comprendre le Challenge (120-150 mots)
Reflète la situation actuelle de {nom} avec leurs propres mots. Montre que tu comprends {secteur} et leurs défis spécifiques. Nomme précisément la faille principale ({faille1['titre']}) et son impact financier chiffré.

### Acte II : Solution Journey (180-220 mots)
Explique comment ePerformance résout leurs 3 failles avec actions concrètes :
- Faille 1 → {produit} avec chatbot IA 24/7
- Faille 2 → Accompagnement {niveau} avec coaching stratégique
- Faille 3 → SaaS automation (posts, SEO, analytics)

Utilise des métriques réelles : économie temps, leads additionnels, ROI projeté. Cite des chiffres précis.

### Acte III : État Transformé (120-150 mots)
Projette leurs résultats dans 90 jours avec chiffres précis :
- Nouveau CAC cible (réduction %)
- Nouveau ratio LTV:CAC (objectif 5:1 minimum)
- Leads/mois projetés (augmentation +%)
- CA mensuel projeté (+% croissance)

Termine par UN appel à l'action clair adapté au segment :
- Chaud : "Commandez votre site maintenant sur eperformance.pro"
- Tiède : "Réservez un appel stratégique 30 min : +225 01 51 17 06 66"
- Froid : "Téléchargez notre guide gratuit '5 Erreurs Pub Facebook'"

## Contraintes
- Ton direct, expert, orienté résultats (K. STÉPHANE parle en "je")
- Chiffres précis (pas de "environ", "plusieurs")
- Zero jargon, français accessible PME africaines
- Zero markdown, zero asterisques, texte brut HTML-ready

IMPORTANT : Réponds UNIQUEMENT en JSON valide (pas de ``` autour) :
{{
  "acte1_challenge": "...",
  "acte2_solution": "...",
  "acte3_transformation": "...",
  "win_themes": ["theme1", "theme2", "theme3"],
  "cta": "...",
  "roi_projected": {{
    "nouveau_cac": 180000,
    "nouveau_ratio": 5.2,
    "leads_mois": 60,
    "ca_mensuel_projete": 3500000,
    "croissance_pct": 40
  }}
}}"""
    
    def _build_system_prompt(self) -> str:
        """System prompt pour Sales Proposal Strategist"""
        return """Tu es Sales Proposal Strategist, expert en propositions commerciales gagnantes pour PME africaines.

Ton rôle : transformer des diagnostics business en narratives convaincantes qui créent l'urgence et poussent à l'action.

Principes :
- Client-centric : parle de LEURS problèmes, pas de tes features
- Quantifié : chaque affirmation a un chiffre
- Actionnable : le prospect sait exactement quoi faire après
- Authentique : ton de K. STÉPHANE (consultant indépendant, pas agence)

Format de sortie : JSON valide SANS balises markdown."""
    
    def _parse_analysis(self, content: str, fallback_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse la réponse IA en JSON"""
        try:
            # Nettoyer le contenu (enlever ```json si présent)
            cleaned = content.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            
            analysis = json.loads(cleaned)
            
            # Valider structure minimale
            required_keys = ["acte1_challenge", "acte2_solution", "acte3_transformation", "cta"]
            if not all(k in analysis for k in required_keys):
                raise ValueError("Structure JSON incomplète")
            
            return analysis
            
        except Exception as e:
            logger.warning(f"[DiagnosticAnalyzer] Parse JSON échoué, fallback template: {str(e)}")
            return self._generate_template_analysis(fallback_data)
    
    def _generate_template_analysis(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyse template si IA échoue"""
        
        nom = data.get("nom", "Prospect")
        score = data.get("score", 0)
        secteur = data.get("secteur", "votre secteur")
        segment = data.get("segment", "tiede")
        failles = data.get("failles", [])
        faille1 = failles[0] if failles else {"titre": "des opportunités d'amélioration"}
        
        cta_map = {
            "chaud": "Commandez votre site web sur eperformance.pro",
            "tiede": "Réservez un appel stratégique 30 min : +225 01 51 17 06 66",
            "froid": "Téléchargez notre guide gratuit sur eperformance.pro/ebook"
        }
        
        return {
            "acte1_challenge": f"Votre diagnostic révèle un score de {score}/100 dans {secteur}. La faille principale identifiée est : {faille1['titre']}. Cette situation limite actuellement votre capacité à scaler votre acquisition de manière rentable.",
            
            "acte2_solution": f"ePerformance propose une approche structurée en 3 volets : un site web professionnel avec chatbot IA qui capte vos leads 24/7, un accompagnement stratégique personnalisé pour optimiser vos campagnes, et des outils SaaS d'automation qui vous font gagner 15-20h/mois sur la création de contenu et le suivi.",
            
            "acte3_transformation": f"Dans 90 jours, votre système d'acquisition sera structuré et rentable. Vous aurez un flux de leads qualifiés constant, des ratios CAC/LTV optimisés au-dessus de 3:1, et une visibilité complète sur vos performances. Plus besoin de deviner : vous pilotez avec des chiffres.",
            
            "win_themes": [
                "Site web + IA = leads automatiques 24/7",
                "Accompagnement expert = stratégie rentable",
                "Automation SaaS = gain temps + cohérence"
            ],
            
            "cta": cta_map.get(segment, cta_map["tiede"]),
            
            "roi_projected": {
                "nouveau_cac": int(data.get("ratios", {}).get("cac", 200000) * 0.7),
                "nouveau_ratio": 5.0,
                "leads_mois": int(data.get("clients_par_mois", 30) * 1.5),
                "ca_mensuel_projete": int(data.get("ca_mensuel", 2000000) * 1.4),
                "croissance_pct": 40
            },
            
            "provider_used": "template"
        }

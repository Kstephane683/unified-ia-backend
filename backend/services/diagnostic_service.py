"""
Service Diagnostic - Calcul ratios, scoring et recommandations.
Logique métier basée sur le système Netlify Function existant.

ePerformance API Flow - Unified IA System
"""

import math
from typing import Dict, Any, List, Tuple
from datetime import datetime


class DiagnosticService:
    """Service principal pour traitement diagnostic"""
    
    # Seuils optimaux (benchmarks industrie)
    RATIO_LTV_CAC_MIN = 3.0
    RATIO_LTV_CAC_OPTIMAL = 5.0
    PAYBACK_MAX_MOIS = 12
    PAYBACK_OPTIMAL_MOIS = 6
    MARGE_MIN_PCT = 25
    
    def calculate_ratios(
        self,
        ca_mensuel: int,
        clients_par_mois: int,
        budget_pub_mensuel: int,
        duree_vie_client_mois: int = 12,
        marge_pct: float = 30.0
    ) -> Dict[str, Any]:
        """
        Calcule les ratios clés d'acquisition.
        
        Returns:
            {
                "cac": 250000,
                "ltv": 900000,
                "ratio": 3.6,
                "payback": 8.3,
                "marge": 30,
                "ca_par_client": 62500,
                "profit_par_client": 18750
            }
        """
        
        # Éviter division par zéro
        if clients_par_mois == 0:
            clients_par_mois = 1
        
        # CAC (Coût d'Acquisition Client)
        cac = budget_pub_mensuel / clients_par_mois if clients_par_mois > 0 else budget_pub_mensuel
        
        # CA par client
        ca_par_client = ca_mensuel / clients_par_mois if clients_par_mois > 0 else 0
        
        # Profit par client (avec marge)
        profit_par_client = ca_par_client * (marge_pct / 100)
        
        # LTV (Lifetime Value)
        ltv = profit_par_client * duree_vie_client_mois
        
        # Ratio LTV:CAC
        ratio = round(ltv / cac, 1) if cac > 0 else 0
        
        # Payback period (en mois)
        payback = round(cac / profit_par_client, 1) if profit_par_client > 0 else 99
        
        return {
            "cac": int(cac),
            "ltv": int(ltv),
            "ratio": ratio,
            "payback": payback,
            "marge": marge_pct,
            "ca_par_client": int(ca_par_client),
            "profit_par_client": int(profit_par_client)
        }
    
    def calculate_score(
        self,
        ratios: Dict[str, Any],
        has_website: bool,
        uses_digital_tools: bool,
        tracks_metrics: bool,
        budget_available: int
    ) -> int:
        """
        Calcule le score de maturité 0-100.
        
        Pondération :
        - 40% : Ratios financiers (LTV:CAC, Payback)
        - 25% : Infrastructure digitale (site, outils)
        - 20% : Capacité tracking/mesure
        - 15% : Budget disponible
        """
        
        score = 0
        
        # 1. Ratios financiers (40 points max)
        ratio_ltv_cac = ratios.get("ratio", 0)
        payback = ratios.get("payback", 99)
        
        # LTV:CAC (25 points)
        if ratio_ltv_cac >= self.RATIO_LTV_CAC_OPTIMAL:
            score += 25
        elif ratio_ltv_cac >= self.RATIO_LTV_CAC_MIN:
            score += 15
        elif ratio_ltv_cac >= 2.0:
            score += 10
        elif ratio_ltv_cac >= 1.0:
            score += 5
        
        # Payback (15 points)
        if payback <= self.PAYBACK_OPTIMAL_MOIS:
            score += 15
        elif payback <= self.PAYBACK_MAX_MOIS:
            score += 10
        elif payback <= 18:
            score += 5
        
        # 2. Infrastructure digitale (25 points max)
        if has_website:
            score += 15
        if uses_digital_tools:
            score += 10
        
        # 3. Capacité tracking (20 points max)
        if tracks_metrics:
            score += 20
        
        # 4. Budget disponible (15 points max)
        if budget_available >= 350000:  # Site Croissance
            score += 15
        elif budget_available >= 250000:  # Site Pro
            score += 12
        elif budget_available >= 100000:  # Site Découverte
            score += 8
        elif budget_available >= 50000:  # Formations
            score += 4
        
        return min(score, 100)
    
    def identify_failles(self, ratios: Dict[str, Any], diagnostic_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Identifie les 3 failles prioritaires.
        
        Returns:
            [
                {"titre": "...", "description": "...", "priorite": 1, "impact": "high"},
                ...
            ]
        """
        
        failles = []
        
        ratio_ltv_cac = ratios.get("ratio", 0)
        payback = ratios.get("payback", 99)
        has_website = diagnostic_data.get("has_website", False)
        tracks_metrics = diagnostic_data.get("tracks_metrics", False)
        budget_pub = diagnostic_data.get("budget_pub_mensuel", 0)
        
        # Faille 1 : Ratio LTV:CAC insuffisant
        if ratio_ltv_cac < self.RATIO_LTV_CAC_MIN:
            failles.append({
                "titre": f"Ratio LTV:CAC {ratio_ltv_cac}:1 insuffisant (min 3:1)",
                "description": f"Chaque client vous coûte trop cher par rapport à ce qu'il rapporte. Avec un ratio de {ratio_ltv_cac}:1, vous brûlez du cash sur l'acquisition. L'objectif est d'atteindre minimum 3:1, idéalement 5:1.",
                "priorite": 1,
                "impact": "high",
                "solution": "Optimiser CAC (ciblage pub) et augmenter LTV (upsell, rétention)"
            })
        
        # Faille 2 : Payback trop long
        if payback > self.PAYBACK_MAX_MOIS:
            failles.append({
                "titre": f"Payback de {payback} mois trop long (max 12 mois)",
                "description": f"Vous mettez {payback} mois à récupérer votre investissement client. C'est trop long et risqué pour votre trésorerie. L'objectif est de descendre sous 12 mois, idéalement 6 mois.",
                "priorite": 2,
                "impact": "high",
                "solution": "Augmenter panier moyen et marge, réduire coût acquisition"
            })
        
        # Faille 3 : Pas de site web
        if not has_website:
            failles.append({
                "titre": "Absence de site web professionnel",
                "description": "Sans site web, vous perdez 70% de vos prospects qui cherchent en ligne avant d'acheter. Vous manquez de crédibilité face à la concurrence et ne pouvez pas automatiser votre génération de leads.",
                "priorite": 1,
                "impact": "high",
                "solution": "Site web avec chatbot IA pour capturer leads 24/7"
            })
        
        # Faille 4 : Pas de tracking
        if not tracks_metrics:
            failles.append({
                "titre": "Aucun tracking des performances",
                "description": "Vous pilotez à l'aveugle. Sans données précises (CAC, conversion, ROI), impossible d'optimiser vos campagnes. Vous perdez probablement 30-40% de budget en canaux non-rentables.",
                "priorite": 2,
                "impact": "medium",
                "solution": "Dashboard analytics + tracking pixels (Meta, Google)"
            })
        
        # Faille 5 : Budget pub trop faible
        if budget_pub > 0 and budget_pub < 100000:
            failles.append({
                "titre": f"Budget pub {budget_pub:,} FCFA/mois insuffisant",
                "description": f"Avec moins de 100k FCFA/mois en pub, difficile d'avoir assez de data pour optimiser. Vous êtes en phase test perpétuel sans atteindre la masse critique pour scaler.",
                "priorite": 3,
                "impact": "medium",
                "solution": "Augmenter budget ou focuser sur 1 seul canal bien optimisé"
            })
        
        # Trier par priorité et retourner top 3
        failles.sort(key=lambda x: x["priorite"])
        return failles[:3]
    
    def recommend_products(
        self,
        score: int,
        budget_available: int,
        has_website: bool,
        ratios: Dict[str, Any]
    ) -> Tuple[str, str, str]:
        """
        Recommande produit site + niveau SaaS + segment.
        
        Returns:
            (produit_site, niveau_saas, segment)
            
        Exemples:
            ("Site Découverte 100k", "Freemium 0 FCFA", "froid")
            ("Site Professionnel 250k", "Essentielle 75k/mois", "tiede")
            ("Site Croissance 350k", "Croissance 120k/mois", "chaud")
        """
        
        # Déterminer segment selon score
        if score >= 75:
            segment = "chaud"
        elif score >= 50:
            segment = "tiede"
        elif score >= 25:
            segment = "froid"
        else:
            segment = "tres_froid"
        
        # Recommander produit site selon budget + besoin
        if not has_website:
            if budget_available >= 350000:
                produit_site = "Site Croissance 350k FCFA"
            elif budget_available >= 250000:
                produit_site = "Site Professionnel 250k FCFA"
            elif budget_available >= 100000:
                produit_site = "Site Découverte 100k FCFA"
            else:
                produit_site = "Formation + eBook (attendre budget site)"
        else:
            produit_site = "Amélioration site existant (audit offert)"
        
        # Recommander niveau SaaS selon score + budget
        ratio_ltv_cac = ratios.get("ratio", 0)
        
        if segment == "chaud" and ratio_ltv_cac >= 3.0:
            niveau_saas = "Croissance 120k FCFA/mois"
        elif segment in ["chaud", "tiede"] and ratio_ltv_cac >= 2.0:
            niveau_saas = "Essentielle 75k FCFA/mois"
        elif segment == "tiede":
            niveau_saas = "Freemium 0 FCFA (puis upgrade)"
        else:
            niveau_saas = "Freemium 0 FCFA"
        
        return produit_site, niveau_saas, segment
    
    def generate_summary(
        self,
        score: int,
        ratios: Dict[str, Any],
        failles: List[Dict[str, Any]],
        produit_site: str,
        niveau_saas: str,
        segment: str
    ) -> str:
        """Génère un résumé textuel du diagnostic"""
        
        faille_principale = failles[0]["titre"] if failles else "Opportunités d'optimisation"
        
        summary = f"""Score : {score}/100 ({segment.upper()})
        
Ratio LTV:CAC : {ratios['ratio']}:1 (objectif 3:1 minimum)
Payback : {ratios['payback']} mois (objectif 12 mois max)

Faille principale : {faille_principale}

Recommandation :
1. {produit_site}
2. {niveau_saas}
"""
        
        return summary.strip()

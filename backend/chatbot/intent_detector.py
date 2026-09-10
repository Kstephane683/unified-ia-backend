"""
IntentDetector - Détection d'intent utilisateur
Phase 1-S1.4 : 3 niveaux de détection (Regex → ML → LLM fallback)

Intents supportés (15+) :
- diagnostic_request : Demande de diagnostic business
- product_inquiry : Questions sur produits/services
- order_intent : Intention d'achat/commande
- objection_handling : Objections à traiter
- support_question : Questions support technique
- mlm_advice : Conseils MLM/parrainage
- content_strategy : Stratégies contenu réseaux sociaux
- ia_trends : Veille IA et tendances
- technical_seo : Questions SEO technique
- growth_hacking : Growth hacking et acquisition
- pricing_question : Questions tarifs
- partnership_inquiry : Partenariats/collaborations
- testimonial_request : Demande de témoignages
- complaint : Réclamation
- general_question : Question générale
"""
import re
from typing import Dict, Tuple, Optional
from datetime import datetime


class IntentDetector:
    """
    Détecteur d'intent avec 3 niveaux :
    1. Regex patterns (80% des cas, rapide)
    2. ML classifier (si patterns ambigus) - TODO Phase 2
    3. LLM fallback (cas complexes) - TODO Phase 2
    """
    
    # Patterns regex par intent (niveau 1 : rapide, 80% des cas)
    INTENT_PATTERNS = {
        'diagnostic_request': [
            r'\b(diagnostic|audit|analyse|évaluation|bilan)\b',
            r'\b(cac|ltv|coût.*acquisition|valeur.*vie)\b',
            r'\b(performance|rentabilité|kpi|métriques)\b',
            r'\b(problème|difficulté|blocage|faille)\b',
            r'\b(améliorer|optimiser|augmenter).*\b(résultats|ventes|conversions)\b',
        ],
        'order_intent': [
            r'\b(commander|acheter|souscrire|prendre)\b',
            r'\b(tarif|prix|coût|combien).*\b(formation|service|produit)\b',
            r'\bje veux\b',
            r'\b(intéressé|intéresse).*\b(par|à)\b',
            r'\b(démarrer|commencer|lancer)\b.*\b(formation|accompagnement)\b',
        ],
        'product_inquiry': [
            r'\b(formation|programme|cours|académie)\b',
            r'\b(service|offre|produit|solution)\b',
            r'\b(qu\'est-ce que|c\'est quoi|expliquer|présenter)\b',
            r'\b(différence|comparer|comparaison)\b.*\b(entre|versus)\b',
            r'\b(inclus|contenu|durée|accès)\b',
        ],
        'objection_handling': [
            r'\b(cher|coûteux|prix élevé|trop cher)\b',
            r'\b(pas le temps|manque de temps|occupé)\b',
            r'\b(pas sûr|hésit|doute|réfléchir)\b',
            r'\b(déjà essayé|ça ne marche pas|pas pour moi)\b',
            r'\b(concurrent|alternative|ailleurs)\b',
        ],
        'support_question': [
            r'\b(aide|aidez-moi|besoin d\'aide|support)\b',
            r'\b(problème|erreur|bug|ne fonctionne pas)\b',
            r'\b(comment|où|quand|qui).*\b(accès|connexion|utiliser)\b',
            r'\b(mot de passe|login|compte|profil)\b',
            r'\b(facturation|paiement|remboursement)\b',
        ],
        'mlm_advice': [
            r'\b(mlm|marketing.*réseau|marketing de réseau|network marketing)\b',
            r'\b(parrain|recrutement|équipe|downline)\b',
            r'\b(sponsor|filleul|réseau)\b',
            r'\b(dupliquer|système de vente)\b',
        ],
        'content_strategy': [
            r'\b(contenu|publication|post|stories)\b',
            r'\b(instagram|facebook|linkedin|tiktok|réseaux sociaux)\b',
            r'\b(engagement|reach|portée|algorithme)\b',
            r'\b(calendrier.*éditorial|planning.*contenu)\b',
            r'\b(viral|viralité|tendance)\b',
        ],
        'ia_trends': [
            r'\b(intelligence artificielle|ia|ai|chatgpt|gpt)\b',
            r'\b(automatisation|automatiser|automation)\b',
            r'\b(deepseek|claude|gemini|mistral)\b',
            r'\b(prompt|prompting|prompt engineering)\b',
            r'\b(tendance|actualité|nouveauté).*\bia\b',
        ],
        'technical_seo': [
            r'\b(seo|référencement|positionnement)\b',
            r'\b(google|moteur.*recherche|serp)\b',
            r'\b(mots-clés|keywords|backlinks)\b',
            r'\b(indexation|crawl|sitemap)\b',
            r'\b(meta|title|description)\b',
        ],
        'growth_hacking': [
            r'\b(growth.*hack|croissance.*rapide|acquisition)\b',
            r'\b(viral.*loop|référencement viral)\b',
            r'\b(ab.*test|test.*ab|split.*test)\b',
            r'\b(funnel|tunnel.*conversion|parcours)\b',
            r'\b(activation|rétention|churn)\b',
        ],
        'pricing_question': [
            r'\b(prix|tarif|coût|combien|€|euro)\b',
            r'\b(gratuit|payant|abonnement|forfait)\b',
            r'\b(paiement|carte.*bancaire|virement)\b',
            r'\b(réduction|promo|remise|offre)\b',
        ],
        'partnership_inquiry': [
            r'\b(partenariat|collaboration|partenaire)\b',
            r'\b(affilié|affiliation|commission)\b',
            r'\b(revendeur|distributeur|agence)\b',
            r'\b(white.*label|marque blanche)\b',
        ],
        'testimonial_request': [
            r'\b(témoignage|avis|retour.*expérience)\b',
            r'\b(résultat|success.*story|cas.*client)\b',
            r'\b(preuve|garantie|satisfait)\b',
        ],
        'complaint': [
            r'\b(mécontent|insatisfait|déçu|énervé)\b',
            r'\b(arnaque|escroc|remboursement)\b',
            r'\b(inadmissible|inacceptable|honteux)\b',
            r'\b(avocat|plainte|signaler)\b',
        ],
    }
    
    # Scores de confiance par méthode
    CONFIDENCE_REGEX = 0.85
    CONFIDENCE_ML = 0.92
    CONFIDENCE_LLM = 0.95
    CONFIDENCE_DEFAULT = 0.50
    
    def __init__(self):
        """Initialiser le détecteur d'intent"""
        self.stats = {
            'total_detections': 0,
            'method_regex': 0,
            'method_ml': 0,
            'method_llm': 0,
            'method_default': 0
        }
    
    def detect(self, message: str, context: Optional[Dict] = None) -> Tuple[str, float, Dict]:
        """
        Détecter l'intent d'un message utilisateur
        
        Args:
            message: Message utilisateur
            context: Contexte additionnel (historique, user info, etc.)
        
        Returns:
            (intent, confidence, metadata)
        """
        self.stats['total_detections'] += 1
        
        # Nettoyer le message
        message_clean = message.lower().strip()
        
        # Niveau 1 : Regex patterns (rapide, 80% des cas)
        intent, confidence = self._detect_with_regex(message_clean)
        
        if confidence >= 0.7:
            self.stats['method_regex'] += 1
            return intent, confidence, {
                'method': 'regex',
                'timestamp': datetime.utcnow().isoformat()
            }
        
        # Niveau 2 : ML classifier (TODO Phase 2)
        # Si patterns ambigus, utiliser un classifier ML
        # Pour l'instant, on garde le résultat regex
        
        # Niveau 3 : LLM fallback (TODO Phase 2)
        # Pour les cas vraiment complexes
        
        # Par défaut : general_question si aucun pattern détecté
        if intent is None:
            self.stats['method_default'] += 1
            return 'general_question', self.CONFIDENCE_DEFAULT, {
                'method': 'default',
                'timestamp': datetime.utcnow().isoformat()
            }
        
        return intent, confidence, {
            'method': 'regex',
            'timestamp': datetime.utcnow().isoformat()
        }
    
    def _detect_with_regex(self, message: str) -> Tuple[Optional[str], float]:
        """
        Détecter l'intent avec regex patterns
        
        Returns:
            (intent, confidence) ou (None, 0.0) si aucun match
        """
        scores = {}
        
        for intent, patterns in self.INTENT_PATTERNS.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, message, re.IGNORECASE):
                    score += 1
            
            if score > 0:
                # Normaliser le score (0.0 - 1.0)
                # Plus il y a de patterns matchés, plus la confiance est élevée
                normalized_score = min(score / len(patterns), 1.0)
                scores[intent] = normalized_score * self.CONFIDENCE_REGEX
        
        if not scores:
            return None, 0.0
        
        # Retourner l'intent avec le score le plus élevé
        best_intent = max(scores.items(), key=lambda x: x[1])
        return best_intent[0], best_intent[1]
    
    def get_stats(self) -> Dict:
        """Retourner les statistiques de détection"""
        return self.stats.copy()
    
    def get_intent_description(self, intent: str) -> str:
        """Retourner une description lisible de l'intent"""
        descriptions = {
            'diagnostic_request': 'Demande de diagnostic business (CAC, LTV, performances)',
            'product_inquiry': 'Questions sur les produits et services',
            'order_intent': 'Intention d\'achat ou de commande',
            'objection_handling': 'Objections ou hésitations à traiter',
            'support_question': 'Question de support technique',
            'mlm_advice': 'Conseils MLM et marketing de réseau',
            'content_strategy': 'Stratégie de contenu réseaux sociaux',
            'ia_trends': 'Veille et tendances IA',
            'technical_seo': 'Questions SEO et référencement',
            'growth_hacking': 'Growth hacking et acquisition',
            'pricing_question': 'Questions sur les tarifs',
            'partnership_inquiry': 'Demande de partenariat',
            'testimonial_request': 'Demande de témoignages',
            'complaint': 'Réclamation ou mécontentement',
            'general_question': 'Question générale'
        }
        return descriptions.get(intent, 'Intent inconnu')

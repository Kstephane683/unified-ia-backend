"""
ContextBuilder - Construction du contexte conversationnel
Phase 1-S1.4 : Agrégation du contexte depuis multiples sources

Sources de contexte :
1. Historique conversation (10 derniers messages)
2. User profile (candidats table si connecté)
3. Diagnostics précédents (diagnostics table)
4. Site configuration (chatbot_sites table)
5. Metadata session (visitor_info, utm_data, etc.)
"""
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta
import json


class ContextBuilder:
    """
    Constructeur de contexte conversationnel
    Agrège les données depuis : historique, DB user, diagnostics, site config
    """
    
    def __init__(self, db: Session):
        """
        Initialiser le context builder
        
        Args:
            db: Session SQLAlchemy
        """
        self.db = db
    
    def build_context(
        self,
        conversation_id: str,
        site_id: str,
        user_id: Optional[int] = None,
        message_history: Optional[List[Dict]] = None,
        visitor_info: Optional[Dict] = None
    ) -> Dict:
        """
        Construire le contexte complet pour la génération de réponse
        
        Args:
            conversation_id: ID de la conversation
            site_id: ID du site (multi-tenant)
            user_id: ID utilisateur si connecté
            message_history: Historique des messages (peut être fourni par le client)
            visitor_info: Infos visiteur (browser, device, etc.)
        
        Returns:
            Contexte complet sous forme de dict
        """
        context = {
            'conversation_id': conversation_id,
            'site_id': site_id,
            'timestamp': datetime.utcnow().isoformat(),
            'sources': []
        }
        
        # 1. Site configuration (multi-tenant)
        site_config = self._load_site_config(site_id)
        if site_config:
            context['site'] = site_config
            context['sources'].append('site_config')
        
        # 2. Historique conversation (10 derniers messages)
        if message_history:
            # Si l'historique est fourni par le client (widget)
            context['history'] = message_history[-10:]  # Garder les 10 derniers
        else:
            # Sinon, charger depuis la DB
            history = self._load_conversation_history(conversation_id, limit=10)
            if history:
                context['history'] = history
                context['sources'].append('db_history')
        
        # 3. User profile (si connecté)
        if user_id:
            user_profile = self._load_user_profile(user_id)
            if user_profile:
                context['user'] = user_profile
                context['sources'].append('user_profile')
        
        # 4. Diagnostics précédents (si user connecté ou conversation a un lead)
        diagnostics = self._load_previous_diagnostics(user_id, conversation_id)
        if diagnostics:
            context['diagnostics'] = diagnostics
            context['sources'].append('diagnostics')
        
        # 5. Visitor info (metadata session)
        if visitor_info:
            context['visitor'] = visitor_info
            context['sources'].append('visitor_info')
        
        # 6. Lead capturé dans cette conversation (si existe)
        lead_info = self._load_conversation_lead(conversation_id)
        if lead_info:
            context['lead'] = lead_info
            context['sources'].append('lead_info')
        
        # Stats contexte
        context['stats'] = {
            'history_length': len(context.get('history', [])),
            'user_known': user_id is not None,
            'has_diagnostics': 'diagnostics' in context,
            'sources_count': len(context['sources'])
        }
        
        return context
    
    def _load_site_config(self, site_id: str) -> Optional[Dict]:
        """
        Charger la configuration du site (multi-tenant)
        
        Returns:
            Config site ou None
        """
        try:
            result = self.db.execute(
                text("""
                    SELECT site_name, system_prompt, welcome_message, 
                           features_enabled, theme_config, is_active
                    FROM chatbot_sites
                    WHERE site_id = :site_id AND is_active = 1
                    LIMIT 1
                """),
                {'site_id': site_id}
            ).fetchone()
            
            if result:
                return {
                    'site_id': site_id,
                    'site_name': result[0],
                    'system_prompt': result[1],
                    'welcome_message': result[2],
                    'features_enabled': json.loads(result[3]) if result[3] else {},
                    'theme_config': json.loads(result[4]) if result[4] else {}
                }
            
            return None
        
        except Exception as e:
            self.db.rollback()
            print(f"Error loading site config: {e}")
            return None
    
    def _load_conversation_history(self, conversation_id: str, limit: int = 10) -> List[Dict]:
        """
        Charger l'historique de conversation depuis la DB
        
        Returns:
            Liste de messages [{role, content, intent, timestamp}, ...]
        """
        try:
            results = self.db.execute(
                text("""
                    SELECT role, content, intent, created_at
                    FROM chatbot_messages
                    WHERE conversation_id = :conversation_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {'conversation_id': conversation_id, 'limit': limit}
            ).fetchall()
            
            # Retourner dans l'ordre chronologique (inverse)
            messages = []
            for row in reversed(results):
                messages.append({
                    'role': row[0],
                    'content': row[1],
                    'intent': row[2],
                    'timestamp': row[3].isoformat() if row[3] else None
                })
            
            return messages
        
        except Exception as e:
            self.db.rollback()
            print(f"Error loading conversation history: {e}")
            return []
    
    def _load_user_profile(self, user_id: int) -> Optional[Dict]:
        """
        Charger le profil utilisateur depuis la table candidats
        
        Returns:
            User profile ou None
        """
        try:
            result = self.db.execute(
                text("""
                    SELECT nom, prenom, email, telephone, entreprise, 
                           secteur_activite, budget_pub_mois, created_at
                    FROM candidats
                    WHERE id = :user_id
                    LIMIT 1
                """),
                {'user_id': user_id}
            ).fetchone()
            
            if result:
                return {
                    'user_id': user_id,
                    'name': f"{result[1]} {result[0]}" if result[1] and result[0] else None,
                    'email': result[2],
                    'phone': result[3],
                    'company': result[4],
                    'industry': result[5],
                    'monthly_ad_budget': result[6],
                    'member_since': result[7].isoformat() if result[7] else None
                }
            
            return None
        
        except Exception as e:
            self.db.rollback()
            print(f"Error loading user profile: {e}")
            return None
    
    def _load_previous_diagnostics(
        self, 
        user_id: Optional[int], 
        conversation_id: str
    ) -> Optional[List[Dict]]:
        """
        Charger les diagnostics précédents (soit par user_id, soit par conversation)
        
        Returns:
            Liste de diagnostics ou None
        """
        try:
            # Stratégie : charger les 3 derniers diagnostics (max 90 jours)
            ninety_days_ago = (datetime.utcnow() - timedelta(days=90)).isoformat()
            
            query_params = {'date_limit': ninety_days_ago}
            
            if user_id:
                # Si user connecté, charger ses diagnostics
                query = """
                    SELECT id, cac, ltv, ratio_ltv_cac, budget_pub_mois, 
                           nombre_clients, score_global, created_at
                    FROM diagnostics
                    WHERE candidat_id = :user_id 
                    AND created_at >= :date_limit
                    ORDER BY created_at DESC
                    LIMIT 3
                """
                query_params['user_id'] = user_id
            else:
                # Sinon, essayer de trouver via la conversation (si lead capturé)
                query = """
                    SELECT d.id, d.cac, d.ltv, d.ratio_ltv_cac, d.budget_pub_mois,
                           d.nombre_clients, d.score_global, d.created_at
                    FROM diagnostics d
                    INNER JOIN chatbot_leads l ON l.email = d.email
                    WHERE l.conversation_id = :conversation_id
                    AND d.created_at >= :date_limit
                    ORDER BY d.created_at DESC
                    LIMIT 3
                """
                query_params['conversation_id'] = conversation_id
            
            results = self.db.execute(text(query), query_params).fetchall()
            
            if results:
                diagnostics = []
                for row in results:
                    diagnostics.append({
                        'id': row[0],
                        'cac': float(row[1]) if row[1] else None,
                        'ltv': float(row[2]) if row[2] else None,
                        'ltv_cac_ratio': float(row[3]) if row[3] else None,
                        'total_budget': float(row[4]) if row[4] else None,
                        'client_count': row[5],
                        'global_score': row[6],
                        'created_at': row[7].isoformat() if row[7] else None
                    })
                
                return diagnostics
            
            return None
        
        except Exception as e:
            self.db.rollback()
            print(f"Error loading diagnostics: {e}")
            return None
    
    def _load_conversation_lead(self, conversation_id: str) -> Optional[Dict]:
        """
        Charger le lead capturé dans cette conversation (si existe)
        
        Returns:
            Lead info ou None
        """
        try:
            result = self.db.execute(
                text("""
                    SELECT visitor_name, visitor_email, visitor_phone, 
                           conversation_transcript, captured_at
                    FROM chatbot_leads
                    WHERE conversation_id = :conversation_id
                    ORDER BY captured_at DESC
                    LIMIT 1
                """),
                {'conversation_id': conversation_id}
            ).fetchone()
            
            if result:
                return {
                    'name': result[0],
                    'email': result[1],
                    'phone': result[2],
                    'transcript': result[3],
                    'captured_at': result[4].isoformat() if result[4] else None
                }
            
            return None
        
        except Exception as e:
            self.db.rollback()
            print(f"Error loading conversation lead: {e}")
            return None
            return None
    
    def format_context_for_llm(self, context: Dict) -> str:
        """
        Formater le contexte pour l'utilisation dans un prompt LLM
        
        Returns:
            Contexte formaté en texte
        """
        parts = []
        
        # Site info
        if 'site' in context:
            site = context['site']
            parts.append(f"Site: {site['site_name']} ({site['site_id']})")
        
        # User info
        if 'user' in context:
            user = context['user']
            parts.append(f"\nUtilisateur connecté: {user['name']}")
            if user.get('company'):
                parts.append(f"Entreprise: {user['company']}")
            if user.get('industry'):
                parts.append(f"Secteur: {user['industry']}")
        
        # Lead info
        if 'lead' in context:
            lead = context['lead']
            parts.append(f"\nLead capturé: {lead['name']}")
        
        # Diagnostics
        if 'diagnostics' in context and context['diagnostics']:
            parts.append(f"\n{len(context['diagnostics'])} diagnostic(s) précédent(s):")
            for diag in context['diagnostics'][:2]:  # Max 2 pour ne pas surcharger
                if diag['cac'] and diag['ltv']:
                    parts.append(
                        f"  • CAC: {diag['cac']}€, LTV: {diag['ltv']}€, "
                        f"Ratio: {diag['ltv_cac_ratio']:.2f}, Score: {diag['global_score']}"
                    )
        
        # Historique récent (résumé)
        if 'history' in context and context['history']:
            parts.append(f"\nHistorique: {len(context['history'])} message(s)")
        
        return '\n'.join(parts)

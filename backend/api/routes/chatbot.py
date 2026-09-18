"""
Routes API Chatbot - Compatible Deep Chat
Phase 1-S1.4 : Intégration frontend React 18 + Deep Chat avec backend 29 agents IA

Routes:
- POST /api/chatbot/message - Envoyer message (pipeline complet)
- GET /api/chatbot/conversation/{id} - Historique conversation
- GET /api/chatbot/search - Recherche dans les articles du blog (tâche 6.8)
- POST /api/chatbot/sites/{site_id}/configure - Config multi-tenant (admin)
- GET /api/chatbot/analytics/{site_id} - Métriques par site
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging

from ...core.auth import get_current_user
from ...core.database import get_db
from ...chatbot.service import ChatbotService
from ...chatbot.models import ChatbotConversation, ChatbotMessage, ChatbotSite
from ...chatbot.vision import ImageInvalide, preparer_image, resume_pour_journal
from ...chatbot import blog_search

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chatbot", tags=["chatbot"])


# ============================================================
# REQUEST / RESPONSE MODELS
# ============================================================

class ImagePayload(BaseModel):
    """
    Image jointe au message — extension du contrat V2 (tâche 6.3-BIS A.1).

    Le widget envoie l'image en base64, sans préfixe de type :

    ```json
    {"role": "user", "text": "Que penses-tu de ce visuel ?",
     "image": {"data": "iVBORw0KGgo…", "media_type": "image/png",
               "detail": "auto", "name": "visuel.png"}}
    ```

    Règles (voir `backend/chatbot/vision.py`) :
    - `data` : base64, avec ou sans préfixe `data:image/…;base64,`
    - `media_type` : **documentaire** — le type réel est détecté par les
      magic bytes. Un `.png` qui contient du JPEG est traité comme du JPEG.
    - formats acceptés : JPEG, PNG, GIF, WebP
    - `detail` : `low` | `high` | `auto` (défaut `auto`) — passé au fournisseur
    - limite : 4 Mo décodé, grand côté ramené à 512 px (≈ 384 tokens max)
    """
    data: str = Field(..., description="Image encodée en base64")
    media_type: Optional[str] = Field(None, description="Type MIME déclaré (documentaire)")
    detail: Optional[str] = Field(None, description="low | high | auto")
    name: Optional[str] = Field(None, description="Nom de fichier d'origine (documentaire)")


class DeepChatMessage(BaseModel):
    """Format Deep Chat standard"""
    text: Optional[str] = None
    html: Optional[str] = None
    role: str = Field(..., pattern="^(user|ai)$")
    files: Optional[List[Dict[str, Any]]] = None
    # Extension A.1 : image jointe (dernier message uniquement)
    image: Optional[ImagePayload] = None


class ChatbotMessageRequest(BaseModel):
    """
    Request format compatible Deep Chat
    
    Deep Chat envoie:
    {
      "messages": [
        {"role": "user", "text": "Bonjour"},
        {"role": "ai", "text": "Bonjour ! Comment puis-je vous aider ?"}
      ]
    }
    
    On extrait le dernier message user
    """
    messages: List[DeepChatMessage]
    
    # Context optionnel
    conversationId: Optional[str] = Field(None, alias="conversation_id")
    siteId: str = Field(default="eperformance_vitrine", alias="site_id")
    userId: Optional[int] = Field(None, alias="user_id")
    
    # Visitor info
    visitorInfo: Optional[Dict[str, Any]] = Field(None, alias="visitor_info")
    
    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "messages": [
                    {"role": "user", "text": "Je veux faire le diagnostic gratuit"}
                ],
                "site_id": "eperformance_vitrine",
                "visitor_info": {
                    "user_agent": "Mozilla/5.0...",
                    "referrer": "https://google.com"
                }
            }
        }


class ChatbotMessageResponse(BaseModel):
    """
    Response format compatible Deep Chat
    
    Deep Chat attend:
    {
      "text": "Votre réponse ici",
      "html": "<div>HTML optionnel</div>",  // Alternative à text
      "files": [...]  // Optionnel
    }
    
    On ajoute des métadonnées via le champ `metadata` (conversation_id, intent,
    agent_used, actions, suggestions) — ignoré par Deep Chat, exploité par le widget Vue
    """
    text: Optional[str] = None
    html: Optional[str] = None
    files: Optional[List[Dict[str, Any]]] = None
    
    # Métadonnées pour le widget (conversation_id, intent, agent, suggestions)
    # NB: Deep Chat ignore les champs inconnus — notre widget Vue les exploite
    metadata: Optional[Dict[str, Any]] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "html": """
                    <div>
                        <p>Parfait ! Pour établir votre diagnostic personnalisé, j'ai quelques questions...</p>
                        <div style="margin-top: 16px;">
                            <button onclick="window.deepChatSendMessage('Oui, je distribue des produits')">
                                Oui, je distribue
                            </button>
                            <button onclick="window.deepChatSendMessage('Non, pas encore')">
                                Non, pas encore
                            </button>
                        </div>
                    </div>
                """
            }
        }


class ConversationHistoryResponse(BaseModel):
    """Historique complet conversation"""
    conversation_id: str
    site_id: str
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    messages: List[Dict[str, Any]]
    
    class Config:
        from_attributes = True


class SiteConfigRequest(BaseModel):
    """Configuration site multi-tenant"""
    site_id: str
    site_name: str
    system_prompt: Optional[str] = None
    business_context: Optional[str] = None
    sector: Optional[str] = Field(None, description="restaurant, mlm, ecommerce, salon_beaute, coach_formateur")
    welcome_message: Optional[str] = None
    theme: Optional[Dict[str, Any]] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "site_id": "restaurant_chez_amina",
                "site_name": "Restaurant Chez Amina",
                "sector": "restaurant",
                "business_context": "Restaurant traditionnel ivoirien à Abidjan. Spécialités: attiéké poisson, alloco, etc.",
                "welcome_message": "Bienvenue chez Amina ! 🍽️ Comment puis-je vous aider ?",
                "theme": {
                    "primary_color": "#ff6b35",
                    "avatar_emoji": "🍽️"
                }
            }
        }


class AnalyticsResponse(BaseModel):
    """Métriques chatbot par site"""
    site_id: str
    period_start: datetime
    period_end: datetime
    total_conversations: int
    total_messages: int
    total_leads_captured: int
    top_intents: List[Dict[str, Any]]
    conversion_rate: float
    avg_messages_per_conversation: float


class BlogSearchResult(BaseModel):
    """Un article du blog, avec de quoi comprendre pourquoi il est remonté."""
    slug: str
    titre: str
    description: str
    url: str
    collection: Optional[str] = None
    collection_titre: Optional[str] = None
    date: Optional[str] = None
    tags: List[str] = []
    # `score` et `couverture` sont exposés pour rendre le classement VÉRIFIABLE :
    # sans eux, un résultat vide serait indiscernable d'un bug de classement.
    score: float
    couverture: float
    termes_trouves: List[str] = []
    #: `true` = l'article couvre réellement la question (seuils mesurés, cf.
    #: `blog_search.py`). Le widget peut tout afficher et n'utiliser ce drapeau
    #: que s'il veut distinguer « correspondance forte » et « correspondance
    #: approchante ».
    pertinent: bool = False


class BlogSearchIndexState(BaseModel):
    """État de l'index — date de génération et couverture, pour le diagnostic."""
    disponible: bool
    articles_indexes: Optional[int] = None
    articles_avec_corps: Optional[int] = None
    genere_le: Optional[str] = None
    charge_il_y_a_s: Optional[int] = None
    ttl_s: Optional[int] = None
    source: Optional[str] = None
    derniere_erreur: Optional[str] = None
    raison: Optional[str] = None


class BlogSearchResponse(BaseModel):
    """
    Réponse de recherche dans le blog (tâche 6.8).

    Contrat : cette route répond TOUJOURS 200, même si l'index est absent ou
    si le blog est injoignable. Une recherche indisponible n'est pas une
    erreur du client ; c'est un état, décrit par `index` et par `message`.
    """
    requete: str
    resultats: List[BlogSearchResult] = []
    total: int = 0
    message: Optional[str] = None
    index: BlogSearchIndexState


# ============================================================
# ROUTES
# ============================================================

@router.post("/message", response_model=ChatbotMessageResponse)
async def send_message(
    request: ChatbotMessageRequest,
    db: Session = Depends(get_db)
):
    """
    Traiter un message utilisateur (pipeline complet IA)
    
    Compatible Deep Chat format:
    - Input: {messages: [{role, text}], site_id, visitor_info}
    - Output: {text: "...", html: "..."}
    
    Pipeline:
    1. Extraire dernier message user
    2. Load context (historique, user profile, diagnostics)
    3. Detect intent (57 intents possibles)
    4. Route to agent (29 agents IA spécialisés)
    5. Generate response (LLM avec persona agent)
    6. Execute actions (lead capture, notifications, diagnostic)
    7. Save to DB
    8. Return formatted response
    """
    try:
        # ============================================================
        # 1. EXTRAIRE MESSAGE USER
        # ============================================================
        
        if not request.messages:
            raise HTTPException(status_code=400, detail="No messages provided")
        
        # Dernier message = message utilisateur actuel
        last_message = request.messages[-1]
        
        if last_message.role != "user":
            raise HTTPException(status_code=400, detail="Last message must be from user")
        
        user_message = last_message.text or ""
        
        # ============================================================
        # 1bis. IMAGE JOINTE (extension A.1) — validée AVANT tout appel LLM
        # ============================================================
        image = None
        if last_message.image is not None:
            try:
                image = preparer_image(
                    data=last_message.image.data,
                    media_type_declare=last_message.image.media_type,
                    detail=last_message.image.detail,
                    nom=last_message.image.name,
                )
            except ImageInvalide as exc:
                # 400 explicite : le widget affiche le message tel quel, et le
                # visiteur comprend ce qui ne va pas (format, poids).
                raise HTTPException(status_code=400, detail=str(exc))
            # Journal SANS contenu : type, taille, mesures. Jamais l'image.
            logger.info(f"Image jointe: {resume_pour_journal(image)}")
        
        if not user_message.strip() and image is None:
            raise HTTPException(status_code=400, detail="Empty message")
        
        # ============================================================
        # 2. CONSTRUIRE HISTORIQUE
        # ============================================================
        
        # Convertir messages Deep Chat en format backend
        message_history = []
        for msg in request.messages[:-1]:  # Tous sauf le dernier (déjà traité)
            message_history.append({
                "role": msg.role,
                "content": msg.text or msg.html or "",
                "timestamp": datetime.utcnow().isoformat()
            })
        
        # ============================================================
        # 3. APPEL CHATBOT SERVICE (PIPELINE COMPLET)
        # ============================================================
        
        chatbot_service = ChatbotService(db)
        
        result = await chatbot_service.process_message(
            site_id=request.siteId,
            message=user_message,
            conversation_id=request.conversationId,
            user_id=request.userId,
            visitor_info=request.visitorInfo or {},
            message_history=message_history,
            image=image
        )
        
        # ============================================================
        # 4. FORMATTER RÉPONSE DEEP CHAT
        # ============================================================
        
        metadata = {
            "conversation_id": result.get('conversation_id'),
            "intent": result.get('intent'),
            # `agent_used` est VOLONTAIREMENT ABSENT (DÉCISION Ballo + règle A.6) :
            # aucun nom d'agent ne doit être lisible côté visiteur, y compris en
            # inspectant le trafic réseau. Le dashboard admin l'obtient par ses
            # propres endpoints protégés (`/api/chatbot/admin/*`).
            "actions": result.get('actions', []),
            "suggestions": result.get('suggestions', []),
            "processing_time": result.get('processing_time_ms', 0),
            "human_active": result.get('human_active', False),
        }

        # Articles du blog utilisés pour construire cette réponse (tâche 6.8).
        # Champ ADDITIF et FACULTATIF : absent quand la recherche n'a rien
        # trouvé de pertinent — le widget qui l'ignore ne voit aucune
        # différence avec avant. Il ne contient que des données publiques
        # (slug, titre, URL d'article) ; jamais de nom d'agent.
        blog = result.get('blog') or {}
        if blog.get('articles'):
            metadata["blog_sources"] = [
                {
                    "slug": a.get("slug"),
                    "titre": a.get("titre"),
                    "url": a.get("url"),
                }
                for a in blog["articles"]
            ]
        
        # Réponse rendue : `text` seul, `html` toujours null (contrat V2.2).
        # AVANT : un bloc HTML était généré dès qu'il y avait des suggestions —
        # des boutons `onclick="window.deepChatSendMessage(...)"` que le widget
        # ne consomme pas (il rend `metadata.suggestions` en boutons Vue natifs
        # et DOMPurify retire les `onclick`) et des couleurs en dur
        # (`#edeae3`, `#c9a96e`) justes en thème sombre. Le texte part
        # maintenant en clair : le widget le rend en markdown avec les jetons
        # du design system, la forme ne dépend plus du serveur.
        response = ChatbotMessageResponse(
            text=result.get('response', ''),
            metadata=metadata,
        )
        
        # Log success
        logger.info(
            f"Message processed successfully - "
            f"Site: {request.siteId}, "
            f"Intent: {result.get('intent')}, "
            f"Agent: {result.get('agent_used')}, "
            f"Image: {'oui' if image else 'non'}, "
            f"Conv: {result.get('conversation_id')}"
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}", exc_info=True)
        
        # Réponse fallback en cas d'erreur
        return ChatbotMessageResponse(
            text="Désolé, une erreur s'est produite. Notre équipe a été notifiée. Pouvez-vous reformuler votre demande ?",
            metadata={"error": str(e)}        )


#: Attente maximale du premier chargement de l'index, pour cette route
#: uniquement. La conversation, elle, n'attend jamais (elle utilise l'index
#: s'il est là, et s'en passe sinon).
_ATTENTE_PREMIER_APPEL = 8.0


@router.get("/search", response_model=BlogSearchResponse)
async def search_blog(
    q: str = Query(
        "",
        max_length=300,
        description="Mots-clés de recherche (question du visiteur). Vide accepté.",
    ),
    limit: int = Query(
        5, ge=1, le=20, description="Nombre de résultats souhaités (1 à 20)"
    ),
):
    """
    Rechercher dans les articles PUBLIÉS du blog ePerformance (tâche 6.8).

    Sert l'onglet Aide du widget : le visiteur tape une question, on lui rend
    les articles du blog qui y répondent, avec leur URL publique.

    Fonctionnement :
    - l'index est construit une fois puis gardé en mémoire (jamais reconstruit
      à chaque requête) ; `index.genere_le` porte la date de génération de
      `chatbot-index.json` côté blog ;
    - la recherche est lexicale (BM25F, Python pur). Les embeddings ont été
      écartés après mesure : aucun fournisseur d'embeddings n'est joignable
      avec les clés du projet (détail dans `backend/chatbot/blog_search.py`) ;
    - le premier appel peut attendre la construction de l'index quelques
      secondes ; les suivants sont instantanés ;
    - cette route ne renvoie JAMAIS 500 pour un problème d'index : elle
      répond 200 avec `index.disponible = false` et un `message` explicite.

    `q` est FACULTATIF à dessein : une question vide ou sans rapport doit
    produire une réponse lisible (200 + `message`), pas une erreur de
    validation — le widget envoie aussi des requêtes partielles pendant la
    frappe. Aucun paramètre de cette route ne peut donc produire un 4xx.

    Ne consomme aucun jeton LLM.
    """
    try:
        resultat = blog_search.rechercher(
            q, limite=limit, attendre=_ATTENTE_PREMIER_APPEL
        )
        return BlogSearchResponse(**resultat)
    except Exception as exc:  # pragma: no cover - filet de sécurité
        # Une recherche ne doit jamais produire d'erreur visible : on renvoie
        # un état, pas une exception.
        logger.error(f"Recherche blog en échec: {exc}", exc_info=True)
        return BlogSearchResponse(
            requete=q,
            resultats=[],
            total=0,
            message="La recherche est momentanément indisponible.",
            index=BlogSearchIndexState(disponible=False),
        )


@router.get("/conversation/{conversation_id}", response_model=ConversationHistoryResponse)
async def get_conversation_history(
    conversation_id: str,
    db: Session = Depends(get_db)
):
    """
    Récupérer l'historique complet d'une conversation
    
    Utilisé pour:
    - Reprendre conversation après refresh
    - Export conversation pour analytics
    - Debug / support client
    """
    try:
        # Récupérer conversation
        conversation = db.query(ChatbotConversation).filter(
            ChatbotConversation.conversation_id == conversation_id
        ).first()
        
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Récupérer tous les messages
        messages = db.query(ChatbotMessage).filter(
            ChatbotMessage.conversation_id == conversation_id
        ).order_by(ChatbotMessage.created_at.asc()).all()
        
        # Formatter messages
        # NB: colonne = actions_executed (msg.actions n'existe pas → 500)
        # suggestions incluses pour réhydrater les quick replies du widget
        # human_name : nom RÉEL du conseiller quand un humain a écrit (le badge
        # « Conseiller » du widget le consomme). Sans ce champ, la reprise
        # après refresh perdait le nom et retombait sur un libellé générique.
        messages_formatted = [
            {
                "role": msg.role,
                "content": msg.content,
                "intent": msg.intent,
                "actions": msg.actions_executed,
                "suggestions": msg.suggestions,
                "human_name": (msg.context_data or {}).get("human_name"),
                "created_at": msg.created_at.isoformat() if msg.created_at else None
            }
            for msg in messages
        ]

        return ConversationHistoryResponse(
            conversation_id=conversation.conversation_id,
            site_id=conversation.site_id,
            status=conversation.status,
            created_at=conversation.created_at or conversation.started_at,
            updated_at=conversation.updated_at or conversation.last_message_at or conversation.started_at,
            messages=messages_formatted
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving conversation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/sites/{site_id}/configure")
async def configure_site(
    site_id: str,
    config: SiteConfigRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Configurer un site multi-tenant (admin uniquement)
    
    Permet de customiser:
    - System prompt personnalisé
    - Business context (secteur, produits, services)
    - Welcome message
    - Theme (couleurs, avatar)
    
    Exemples:
    - eperformance_vitrine: Nos propres offres (Pack Découverte, Diagnostic)
    - restaurant_chez_amina: Menu, réservations, livraison
    - mlm_marie_longrich: Opportunité MLM, produits Longrich, parrainage
    - salon_beauty_queen: RDV, prestations beauté, tarifs
    """
    # Sécurité (Phase 0) : configuration réservée aux administrateurs
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")

    try:
        # Vérifier si site existe
        site = db.query(ChatbotSite).filter(
            ChatbotSite.site_id == site_id
        ).first()
        
        if site:
            # Update
            site.site_name = config.site_name
            site.system_prompt = config.system_prompt
            site.business_context = config.business_context
            site.sector = config.sector
            site.welcome_message = config.welcome_message
            site.theme = config.theme
            site.updated_at = datetime.utcnow()
        else:
            # Create
            site = ChatbotSite(
                site_id=site_id,
                site_name=config.site_name,
                system_prompt=config.system_prompt,
                business_context=config.business_context,
                sector=config.sector,
                welcome_message=config.welcome_message,
                theme=config.theme,
                is_active=True
            )
            db.add(site)
        
        db.commit()
        db.refresh(site)
        
        logger.info(f"Site configured: {site_id}")
        
        return {
            "status": "success",
            "site_id": site.site_id,
            "message": "Site configuration updated"
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error configuring site: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to configure site")


@router.get("/analytics/{site_id}", response_model=AnalyticsResponse)
async def get_site_analytics(
    site_id: str,
    period_days: int = 30,
    db: Session = Depends(get_db)
):
    """
    Récupérer métriques chatbot pour un site
    
    Métriques:
    - Total conversations
    - Total messages
    - Leads capturés
    - Top intents (intentions utilisateurs)
    - Taux conversion (visiteurs → leads)
    - Moyenne messages par conversation
    
    Utilisé pour:
    - Dashboard admin
    - Optimisation stratégie conversationnelle
    - ROI chatbot
    """
    try:
        from datetime import timedelta
        from sqlalchemy import func, desc
        from ...chatbot.models import ChatbotLead, ChatbotAnalytics
        
        # Période
        period_end = datetime.utcnow()
        period_start = period_end - timedelta(days=period_days)
        
        # Total conversations
        total_conversations = db.query(func.count(ChatbotConversation.id)).filter(
            ChatbotConversation.site_id == site_id,
            ChatbotConversation.created_at >= period_start
        ).scalar() or 0
        
        # Total messages
        total_messages = db.query(func.count(ChatbotMessage.id)).join(
            ChatbotConversation
        ).filter(
            ChatbotConversation.site_id == site_id,
            ChatbotMessage.created_at >= period_start
        ).scalar() or 0
        
        # Leads capturés
        total_leads = db.query(func.count(ChatbotLead.id)).filter(
            ChatbotLead.site_id == site_id,
            ChatbotLead.created_at >= period_start
        ).scalar() or 0
        
        # Top intents
        top_intents_query = db.query(
            ChatbotMessage.intent,
            func.count(ChatbotMessage.id).label('count')
        ).join(ChatbotConversation).filter(
            ChatbotConversation.site_id == site_id,
            ChatbotMessage.created_at >= period_start,
            ChatbotMessage.intent.isnot(None)
        ).group_by(ChatbotMessage.intent).order_by(desc('count')).limit(10).all()
        
        top_intents = [
            {"intent": intent, "count": count}
            for intent, count in top_intents_query
        ]
        
        # Conversion rate
        conversion_rate = (total_leads / total_conversations * 100) if total_conversations > 0 else 0.0
        
        # Avg messages per conversation
        avg_messages = (total_messages / total_conversations) if total_conversations > 0 else 0.0
        
        return AnalyticsResponse(
            site_id=site_id,
            period_start=period_start,
            period_end=period_end,
            total_conversations=total_conversations,
            total_messages=total_messages,
            total_leads_captured=total_leads,
            top_intents=top_intents,
            conversion_rate=round(conversion_rate, 2),
            avg_messages_per_conversation=round(avg_messages, 2)
        )
        
    except Exception as e:
        logger.error(f"Error retrieving analytics: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve analytics")


# ============================================================
# HEALTH CHECK
# ============================================================

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "chatbot-api",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }

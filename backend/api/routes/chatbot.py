"""
Routes API Chatbot - Compatible Deep Chat
Phase 1-S1.4 : Intégration frontend React 18 + Deep Chat avec backend 29 agents IA

Routes:
- POST /api/chatbot/message - Envoyer message (pipeline complet)
- GET /api/chatbot/conversation/{id} - Historique conversation
- GET /api/chatbot/search - Recherche dans les articles du blog (tâche 6.8)
- GET /api/chatbot/push/config - Clé publique VAPID pour le navigateur (P3-PUSH, public)
- POST /api/chatbot/push/subscribe - Abonnement au push navigateur (P3-PUSH, public)
- DELETE /api/chatbot/push/unsubscribe - Désabonnement (P3-PUSH, public)
- POST /api/chatbot/sites/{site_id}/configure - Config multi-tenant (admin)
- GET /api/chatbot/analytics/{site_id} - Métriques par site
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging

from ...core.auth import get_current_user
from ...core.database import get_db
from ...chatbot.service import ChatbotService
from ...chatbot.models import ChatbotConversation, ChatbotMessage, ChatbotSite
from ...chatbot.vision import ImageInvalide, preparer_image, resume_pour_journal
from ...chatbot import blog_search, notifications, push_abonnements

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


class PushKeysPayload(BaseModel):
    """
    Les deux clés produites par le navigateur (norme Web Push, RFC 8291).

    `p256dh` est la clé publique éphémère du navigateur (point P-256 non
    compressé, base64url), `auth` le secret d'authentification. Sans elles, le
    message ne peut pas être chiffré : le service de push le refuse. Elles ne
    sont jamais renvoyées par l'API ni écrites dans un journal.
    """

    p256dh: str = Field(..., description="Clé publique p256dh (base64url, 87 caractères)")
    auth: str = Field(..., description="Secret d'authentification (base64url, 22 caractères)")

    @field_validator("p256dh")
    @classmethod
    def _valider_p256dh(cls, valeur: str) -> str:
        return push_abonnements.valider_cle(
            valeur, "p256dh", push_abonnements.LONGUEUR_MIN_P256DH
        )

    @field_validator("auth")
    @classmethod
    def _valider_auth(cls, valeur: str) -> str:
        return push_abonnements.valider_cle(
            valeur, "auth", push_abonnements.LONGUEUR_MIN_AUTH
        )


class PushSubscribeRequest(BaseModel):
    """
    Abonnement d'un navigateur aux notifications push (P3-PUSH).

    Appelé par le widget APRÈS consentement explicite du visiteur. Aucun
    compte, aucun jeton : l'abonnement est public par nature, le visiteur n'a
    pas d'identité sur le site.
    """

    endpoint: str = Field(..., description="URL du service de push du navigateur (https)")
    keys: PushKeysPayload
    conversation_id: Optional[str] = Field(
        None, max_length=100, description="Conversation en cours, si elle existe"
    )
    site_id: str = Field(
        default="eperformance_vitrine",
        max_length=100,
        description="Site concerné (métadonnée de diagnostic et de ciblage)",
    )

    @field_validator("endpoint")
    @classmethod
    def _valider_endpoint(cls, valeur: str) -> str:
        # Lève ValueError → Pydantic renvoie 422 (jamais 500). Le détail du
        # contrôle (https, domaine parmi les services de push connus) est dans
        # `push_abonnements.valider_endpoint`.
        return push_abonnements.valider_endpoint(valeur)

    @field_validator("conversation_id")
    @classmethod
    def _nettoyer_conversation(cls, valeur: Optional[str]) -> Optional[str]:
        return (valeur or "").strip() or None

    @field_validator("site_id")
    @classmethod
    def _nettoyer_site(cls, valeur: str) -> str:
        return (valeur or "").strip() or "eperformance_vitrine"


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
        # Le LLM est hors service (crédit, indisponibilité) : le widget
        # remplace la bulle brute par sa carte de repli WhatsApp. Champ
        # ADDITIF — incidence du lot C du 24/09, cf. service.process_message.
        if result.get('ia_indisponible'):
            metadata["ia_indisponible"] = True

        # Liens directs du site (lot D) : {url, label, phrase} — additif,
        # absent quand la détection n'a rien trouvé.
        liens = result.get('liens_site') or []
        if liens:
            metadata["liens_site"] = liens

        # Connaissances du propriétaire utilisées (chantier F) — additif,
        # booléen : le visiteur ne voit jamais la donnée brute, le tableau de
        # bord peut mesurer l'effet de l'entraînement.
        if result.get('connaissances_utilisees'):
            metadata["connaissances_utilisees"] = True

        # Pages du site du tenant citées (chantier E) — additif, publiques.
        pages = result.get('site_pages') or []
        if pages:
            metadata["site_pages"] = [
                {"url": p.get("url"), "titre": p.get("titre")} for p in pages
            ]

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
# PUSH NAVIGATEUR — ABONNEMENT ET DÉSABONNEMENT (P3-PUSH)
# ============================================================
#
# POURQUOI CES DEUX ROUTES SONT PUBLIQUES, ET CE QUI LE COMPENSE
# --------------------------------------------------------------
# L'abonnement est créé par le NAVIGATEUR d'un visiteur qui n'a pas de compte :
# exiger un jeton rendrait la fonctionnalité impossible. Ce qui remplace
# l'authentification ici, c'est la nature de ce qui est écrit et le contrôle de
# ce qui est accepté :
#
#   · ce qui est enregistré est l'URL d'un service de push et deux clés
#     PUBLIQUES produites par le navigateur — aucune donnée personnelle ;
#   · l'URL doit être un service de push connu (liste blanche dans
#     `push_abonnements`) : sans ce filtre, l'enregistrement public deviendrait
#     un relais d'envoi vers n'importe quelle adresse, réseau interne compris ;
#   · l'enregistrement remplace la ligne de MÊME endpoint, il ne peut pas
#     écraser celle d'un autre (l'endpoint est unique en base) ;
#   · le désabonnement exige l'endpoint EXACT, qui n'est connu que du navigateur
#     concerné : personne ne peut désabonner le navigateur d'un autre ;
#   · la route d'écriture est bornée par le limiteur de débit de l'application
#     (`_RATE_LIMITS` dans `backend/api/app.py`).


@router.get("/push/config", response_model=None)
async def configurer_push():
    """
    Servir la clé PUBLIQUE VAPID au navigateur (P3-PUSH).

    `PushManager.subscribe()` exige en `applicationServerKey` la clé publique
    VAPID. Elle est publique par nature — elle est transmise à chaque
    abonnement — mais elle ne peut pas être écrite en dur dans le widget : une
    rotation de clés obligerait alors à republier le widget. Cette route est le
    seul point d'interface qui la transporte.

    TROIS PROPRIÉTÉS, ET POURQUOI CHACUNE EST NÉCESSAIRE :

    1. **La clé privée ne sort jamais.** Cette route ne lit QUE
       `VAPID_PUBLIC_KEY`, et elle ne sert la valeur que si elle se décode
       réellement comme un point public P-256 sur la courbe (`config_cle_publique`).
       Une variable inversée — la clé privée collée dans la variable publique,
       l'erreur de manipulation la plus probable puisque le script de génération
       imprime les deux lignes à la suite — ne peut donc pas être publiée ici :
       elle est REFUSÉE, et le motif ne recopie jamais la valeur (voir les tests
       `TestClePriveeJamaisExposee`).

    2. **La route est publique et en lecture seule.** Elle n'écrit rien, ne
       prend aucun paramètre, ne touche pas la base et n'appelle aucun service
       extérieur : sa réponse ne dépend que de l'environnement. Elle peut donc
       répondre même si la base est indisponible, ce qui est utile au widget qui
       la consulte au chargement. Elle n'est pas limitée en débit pour cette
       raison : c'est une constante, il n'y a rien à abuser.

    3. **L'absence de clé est un ÉTAT, pas une erreur.** Sans clé configurée,
       la réponse reste 200 avec `configure = faux` et une `raison` en clair :
       le widget cesse alors simplement de proposer la fonctionnalité, sans
       rien casser. Un 404 ou un 503 obligerait le widget à interpréter un code
       d'erreur pour un cas nominal.

    `configure` est vrai seulement si le serveur peut À LA FOIS recevoir
    l'abonnement et envoyer la notification (clé publique exploitable ET clé
    privée présente) : promettre la fonctionnalité au visiteur alors que rien
    ne pourrait partir serait une fausse promesse. `canal` porte l'état brut du
    canal, pour le diagnostic.
    """
    etat = notifications.etat_canal("webpush")
    cle = push_abonnements.config_cle_publique()

    # Ordre des raisons : d'abord ce qui manque au serveur pour ENVOYER, ensuite
    # ce qui manque au navigateur pour S'ABONNER.
    raison = None
    if not etat.configure:
        raison = etat.raison
    elif not cle.disponible:
        raison = cle.raison

    configure = bool(etat.configure and cle.disponible)
    return {
        "canal": etat.pour_api(),
        "configure": configure,
        # Base64url sans remplissage : c'est la forme attendue par
        # `applicationServerKey` (le widget la convertit en octets).
        "cle_publique": cle.cle,
        "raison": raison,
        "forme_cle": cle.forme,
        "message": (
            "push non configuré côté serveur : le widget ne propose pas les "
            "notifications, aucun réglage n'est nécessaire côté visiteur"
            if not configure
            else "clé publique disponible : le widget peut proposer les "
            "notifications, après consentement explicite du visiteur"
        ),
    }


@router.post("/push/subscribe", response_model=None)
async def abonner_push(
    corps: PushSubscribeRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Enregistrer (ou mettre à jour) un abonnement au push navigateur (P3-PUSH).

    Un même `endpoint` réabonné met à jour sa ligne : jamais de doublon, jamais
    de 409. Le réabonnement remplace les clés (le navigateur les régénère) et
    réactive la ligne si le visiteur s'était désabonné.

    CETTE ROUTE RÉPOND 200 MÊME SI LE PUSH N'EST PAS ENCORE CONFIGURÉ (clés
    VAPID absentes) : l'abonnement ne dépend pas des clés, et le refuser
    ferait perdre au propriétaire les abonnements déjà consentis par les
    visiteurs le jour où il posera les clés. L'état du canal est renvoyé dans
    `canal` pour que l'absence de configuration soit visible, pas silencieuse.

    Un corps invalide (endpoint vide, clés absentes, domaine non autorisé)
    répond 422 : la validation est faite par Pydantic, avant toute écriture.
    """
    user_agent = (request.headers.get("user-agent") or "").strip()[:500] or None

    abonnement, cree = push_abonnements.enregistrer(
        db,
        endpoint=corps.endpoint,
        cle_p256dh=corps.keys.p256dh,
        cle_auth=corps.keys.auth,
        conversation_id=corps.conversation_id,
        site_id=corps.site_id,
        user_agent=user_agent,
    )

    etat = notifications.etat_canal("webpush")
    reponse = {
        "abonnement": {
            **push_abonnements.vers_api(abonnement),
            "cree": cree,
        },
        "canal": etat.pour_api(),
    }
    if not etat.configure:
        # Un état, pas une erreur : l'abonnement EST enregistré.
        reponse["message"] = (
            "abonnement enregistré ; les notifications partiront dès que le "
            "propriétaire aura créé les clés VAPID — rien d'autre n'est requis "
            "côté visiteur"
        )
    logger.info(
        "Abonnement push %s (site=%s, conversation=%s)",
        "créé" if cree else "mis à jour",
        abonnement.site_id,
        abonnement.conversation_id,
    )
    return reponse


@router.delete("/push/unsubscribe", response_model=None)
async def desabonner_push(
    endpoint: str = Query(
        ...,
        min_length=1,
        max_length=push_abonnements.LONGUEUR_ENDPOINT_MAX,
        description="Endpoint EXACT de l'abonnement à désactiver (renvoyé par le navigateur)",
    ),
    conversation_id: Optional[str] = Query(
        None, max_length=100, description="Condition supplémentaire optionnelle"
    ),
    db: Session = Depends(get_db),
):
    """
    Désabonner un navigateur du push (P3-PUSH).

    La ligne n'est PAS supprimée : elle passe à `actif = faux`. La trace est ce
    qui permet de diagnostiquer après coup un abonnement qui a cessé de
    recevoir, et de le réactiver si le même navigateur se réabonne.

    L'`endpoint` exact est EXIGÉ : c'est lui qui garantit qu'on ne peut pas
    désabonner le navigateur d'un autre. `conversation_id`, s'il est fourni,
    est une condition supplémentaire — un endpoint qui ne lui correspond pas
    n'est pas touché.

    La route est idempotente et répond toujours 200 : un endpoint inconnu ne
    produit ni erreur ni écriture, et le résultat dit exactement ce qui a été
    fait (`abonnements_desactives`). Elle ne peut donc pas servir à découvrir
    quels endpoints existent.
    """
    publics, admins = push_abonnements.desabonner(
        db, endpoint=endpoint.strip(), conversation_id=conversation_id
    )
    total = publics + admins
    return {
        "endpoint_tronque": push_abonnements.tronquer_endpoint(endpoint),
        "abonnements_desactives": total,
        "detail": {"public": publics, "admin": admins},
        "message": (
            "abonnement désactivé — la ligne est conservée pour le diagnostic"
            if total
            else "aucun abonnement actif ne correspond à cet endpoint"
        ),
    }


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

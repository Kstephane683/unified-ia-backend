"""
Vision — préparation d'une image pour le modèle multimodal (tâche 6.3-BIS A.1).

Le modèle est `deepseek-flash`, natif multimodal (`llm_client.DEEPSEEK_MODEL`) :
il reçoit l'image au format OpenAI-compatible, dans le contenu du message :

    {"role": "user", "content": [
        {"type": "text", "text": "Décris cette image"},
        {"type": "image_url",
         "image_url": {"url": "data:image/jpeg;base64,…", "detail": "low"}},
    ]}

Ce module ne fait AUCUN appel réseau : il valide, normalise et borne l'image.

Trois responsabilités, dans cet ordre :

1. **Détection par le CONTENU, jamais par l'extension.** Un fichier nommé
   `photo.jpg` qui contient du PNG est un PNG ; un `.png` qui contient autre
   chose est refusé. Les formats acceptés sont JPEG, PNG, GIF et WebP — les
   quatre que le fournisseur sait lire. Une extension ou un
   `media_type` déclaré par le client ne sert qu'à documenter : il est écrasé
   par ce que dit l'octet d'en-tête.

2. **Budget de tokens borné (~384 par image).** Le coût d'une image se paie en
   tokens de prompt, et il croît avec la surface. On plafonne donc le grand
   côté à `MAX_DIMENSION` (512 px par défaut) : à cette taille, la
   re-échantillonnage tuile 512 px du fournisseur donne AU PLUS 1 tuile, soit
   85 tokens en `detail:"low"` et 85 + 170 = 255 tokens en `detail:"high"` —
   les deux sous le plafond de 384 demandé. `TAILLE_MAX_OCTETS` borne le
   transport (4 Mo de base64 décodé).

   Ce plafond est un CHOIX : une photo de 4000 px coûterait ~2 000 tokens pour
   une description qui ne serait pas meilleure (le modèle décrit la scène, pas
   les pixels). La réduction se fait AVANT l'envoi, une fois pour toutes.

3. **`detail` optionnel** (`low` | `high` | `auto`, défaut `auto`). Il est
   transmis tel quel au fournisseur — c'est LUI qui décide de l'échantillonnage
   final ; le plafond de dimension ci-dessus reste la borne haute.

Aucune donnée n'est écrite sur disque, rien n'est journalisé du contenu.
"""

from __future__ import annotations

import base64
import binascii
import io
from typing import Dict, Optional, Tuple

# ============================================================
# Formats acceptés — signature binaire (magic bytes)
# ============================================================

# JPEG : SOI + marqueur (FFD8FF). Le 4e octet varie (FFE0 JFIF, FFE1 EXIF…).
MAGIC_JPEG = b"\xff\xd8\xff"
MAGIC_PNG = b"\x89PNG\r\n\x1a\n"
MAGIC_GIF87 = b"GIF87a"
MAGIC_GIF89 = b"GIF89a"
# WebP : conteneur RIFF, « WEBP » en octets 8-11
MAGIC_RIFF = b"RIFF"
MAGIC_WEBP = b"WEBP"

MEDIA_TYPES = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/gif": "GIF",
    "image/webp": "WebP",
}

# Budget et bornes (voir le commentaire de module pour le calcul des tokens)
MAX_DIMENSION = 512
TAILLE_MAX_OCTETS = 4 * 1024 * 1024
DETAILS_VALIDES = ("low", "high", "auto")
DETAIL_DEFAUT = "auto"
# Estimation de coût du fournisseur pour une image ≤ 512 px (documentaire)
TOKENS_ESTIMES_LOW = 85
TOKENS_ESTIMES_HIGH = 255

# Erreurs compréhensibles, remontées telles quelles au client (HTTP 400)
MSG_FORMAT = (
    "Format d'image non reconnu. Formats acceptés : JPEG, PNG, GIF, WebP "
    "(détectés par le contenu du fichier)."
)
MSG_TAILLE = "Image trop volumineuse (4 Mo maximum)."
MSG_VIDE = "Image vide ou illisible."
MSG_BASE64 = "Image illisible : base64 invalide."
MSG_DETAIL = f"`detail` doit valoir {' | '.join(DETAILS_VALIDES)}."


class ImageInvalide(ValueError):
    """Image refusée — le message porte la raison, affichable au client."""


def detecter_media_type(octets: bytes) -> Optional[str]:
    """
    Type MIME déduit des PREMIERS OCTETS du fichier.

    L'extension et le `Content-Type` déclarés ne sont jamais consultés : une
    image renommée ne doit pas tromper le serveur.
    """
    if not octets:
        return None
    if octets.startswith(MAGIC_JPEG):
        return "image/jpeg"
    if octets.startswith(MAGIC_PNG):
        return "image/png"
    if octets.startswith(MAGIC_GIF87) or octets.startswith(MAGIC_GIF89):
        return "image/gif"
    if (
        len(octets) >= 12
        and octets.startswith(MAGIC_RIFF)
        and octets[8:12] == MAGIC_WEBP
    ):
        return "image/webp"
    return None


def _decoder_base64(data: str) -> bytes:
    """Décoder du base64 « tolérant » : data URL acceptée, padding optionnel."""
    valeur = (data or "").strip()
    if not valeur:
        raise ImageInvalide(MSG_VIDE)
    # Une data URL complète est acceptée (le widget peut envoyer l'un ou l'autre)
    if valeur.startswith("data:"):
        _, _, valeur = valeur.partition(",")
        valeur = valeur.strip()
    # Les espaces/retours de ligne d'un base64 multiligne sont légitimes
    valeur = "".join(valeur.split())
    # Padding absent (base64url tronqué) : on le reconstitue
    reste = len(valeur) % 4
    if reste:
        valeur += "=" * (4 - reste)
    try:
        return base64.b64decode(valeur, validate=False)
    except (binascii.Error, ValueError) as exc:  # pragma: no cover - défensif
        raise ImageInvalide(MSG_BASE64) from exc


def _normaliser_detail(detail: Optional[str]) -> str:
    if detail is None:
        return DETAIL_DEFAUT
    valeur = str(detail).strip().lower()
    if not valeur:
        return DETAIL_DEFAUT
    if valeur not in DETAILS_VALIDES:
        raise ImageInvalide(MSG_DETAIL)
    return valeur


def _reduire(octets: bytes, media_type: str) -> Tuple[bytes, str, Dict]:
    """
    Ramener l'image sous `MAX_DIMENSION` (grand côté) et la ré-encoder.

    Retour : (octets, media_type, mesures). Si Pillow est absent ou que
    l'image ne se laisse pas décoder, on rend l'original TEL QUEL : refuser
    une image valide pour un problème d'outillage serait pire que de payer
    quelques tokens de plus.
    """
    mesures: Dict = {"reduite": False}
    try:
        from PIL import Image  # Pillow est déjà dans requirements.txt
    except ImportError:  # pragma: no cover - dépendance de production
        return octets, media_type, mesures

    try:
        with Image.open(io.BytesIO(octets)) as image:
            largeur, hauteur = image.size
            mesures.update({"largeur": largeur, "hauteur": hauteur})
            plus_grand = max(largeur, hauteur)
            if plus_grand <= MAX_DIMENSION:
                return octets, media_type, mesures

            ratio = MAX_DIMENSION / float(plus_grand)
            nouvelle = (
                max(1, int(round(largeur * ratio))),
                max(1, int(round(hauteur * ratio))),
            )
            # GIF animé : seule la première vue est décrite par le modèle
            if media_type == "image/gif":
                image.seek(0)
            redimensionnee = image.convert("RGBA" if _a_transparence(image) else "RGB")
            redimensionnee = redimensionnee.resize(nouvelle, Image.LANCZOS)

            tampon = io.BytesIO()
            if _a_transparence(image):
                # PNG : la transparence doit survivre (sinon fond noir)
                redimensionnee.convert("RGBA").save(tampon, format="PNG", optimize=True)
                nouveau_type = "image/png"
            else:
                redimensionnee.convert("RGB").save(
                    tampon, format="JPEG", quality=82, optimize=True
                )
                nouveau_type = "image/jpeg"
            mesures.update(
                {
                    "reduite": True,
                    "largeur": nouvelle[0],
                    "hauteur": nouvelle[1],
                    "origine": (largeur, hauteur),
                }
            )
            return tampon.getvalue(), nouveau_type, mesures
    except Exception:  # image acceptée par les magic bytes mais non décodable
        return octets, media_type, mesures


def _a_transparence(image) -> bool:
    """L'image porte-t-elle un canal alpha ?"""
    try:
        return image.mode in ("RGBA", "LA", "PA") or (
            image.mode == "P" and "transparency" in image.info
        )
    except Exception:  # pragma: no cover - défensif
        return False


def preparer_image(
    data: str,
    media_type_declare: Optional[str] = None,
    detail: Optional[str] = None,
    nom: Optional[str] = None,
) -> Dict:
    """
    Valider et normaliser une image reçue du widget.

    Args:
        data: image en base64 (ou data URL complète) — SANS le préfixe de type
        media_type_declare: ignoré (documentaire) — le contenu fait foi
        detail: `low` | `high` | `auto` (défaut `auto`)
        nom: nom de fichier d'origine (documentaire)

    Returns:
        {
          "data_uri": "data:image/jpeg;base64,…",   # prêt pour image_url.url
          "media_type": "image/jpeg",
          "media_type_declare": "image/png" | None,  # écart signalé
          "detail": "auto",
          "octets": 12345,
          "mesures": {...},
        }

    Raises:
        ImageInvalide: format inconnu, taille excessive, base64 illisible.
    """
    detail_normalise = _normaliser_detail(detail)
    octets = _decoder_base64(data)

    if not octets:
        raise ImageInvalide(MSG_VIDE)
    if len(octets) > TAILLE_MAX_OCTETS:
        raise ImageInvalide(MSG_TAILLE)

    media_type = detecter_media_type(octets)
    if not media_type:
        raise ImageInvalide(MSG_FORMAT)

    octets, media_type, mesures = _reduire(octets, media_type)
    if len(octets) > TAILLE_MAX_OCTETS:
        raise ImageInvalide(MSG_TAILLE)

    encode = base64.b64encode(octets).decode("ascii")
    return {
        "data_uri": f"data:{media_type};base64,{encode}",
        "media_type": media_type,
        "media_type_declare": (media_type_declare or None),
        "detail": detail_normalise,
        "nom": nom or None,
        "octets": len(octets),
        "mesures": mesures,
    }


def bloc_vision(image: Dict, detail: Optional[str] = None) -> Dict:
    """
    Bloc `image_url` OpenAI-compatible, prêt à insérer dans `content`.

    `detail` permet à l'appelant de forcer l'échantillonnage du fournisseur
    pour un usage précis (la description d'image utilise `high` : mesuré plus
    fiable sur les petites images, et ≤ 255 tokens à 512 px, donc sous le
    plafond de 384). Par défaut, on transmet le detail validé à l'entrée.
    """
    return {
        "type": "image_url",
        "image_url": {
            "url": image["data_uri"],
            "detail": detail or image["detail"],
        },
    }


def resume_pour_journal(image: Dict) -> str:
    """Ligne de journal SANS contenu : type, poids, mesures. Jamais l'image."""
    mesures = image.get("mesures") or {}
    taille = (
        f"{mesures.get('largeur')}x{mesures.get('hauteur')}"
        if mesures.get("largeur")
        else "?"
    )
    reduite = " (réduite)" if mesures.get("reduite") else ""
    return (
        f"{image['media_type']} {taille}{reduite} — {image['octets']} o, "
        f"detail={image['detail']}"
    )

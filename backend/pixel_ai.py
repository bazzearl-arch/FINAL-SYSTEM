"""AI-powered Everskies-style pixel-art mini character generator.

Because the available image models only support text-to-image, we use a
two-step pipeline:
  1) A vision model looks at the rendered try-on image and writes a precise
     description of the character (body, face/expression, hair, clothing,
     accessories, colors).
  2) gpt-image-1 generates an Everskies-style pixel-art mini character from
     that description + a fixed style prompt.

If any step fails, the caller is expected to fall back to the local
algorithmic pixelator so the favorite flow never fully breaks.
"""
from __future__ import annotations

import base64
import io
import os
import uuid

from PIL import Image

STYLE_PROMPT_BASE = (
    "Pixel art avatar in the style of Everskies (a cute chibi-like dress-up "
    "game avatar with clean, crisp pixel shading and soft outlines). "
    "Draw ONE complete mini character, full body, standing front view, "
    "centered on a plain solid pure-white background. "
    "Imitate the body shape, facial features and expression. "
    "Faithfully reproduce the exact hairstyle, clothing and accessories "
    "described below, matching their colors. "
    "No text, no watermark, no extra characters, no props besides what is worn."
)

VISION_SYSTEM = (
    "You are a character analyst for a pixel-art dress-up game. "
    "Look at the person in the image and describe them so an artist can draw a "
    "matching mini avatar."
)

VISION_PROMPT = (
    "Describe this character for a pixel-art avatar. Be specific and concise. "
    "Cover, in short phrases: body build/shape; face shape and facial "
    "expression; hair (style, length, color); every clothing item worn with "
    "its color/pattern; footwear; and any accessories. "
    "Reply with 4-6 short comma-separated phrases only, no preamble."
)


def _downscale_for_vision(image_bytes: bytes, max_side: int = 640) -> str:
    """Return base64 (no data-uri prefix) of a downscaled PNG to save tokens."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    scale = min(1.0, float(max_side) / float(max(w, h)))
    if scale < 1.0:
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


async def describe_character(image_bytes: bytes, api_key: str) -> str:
    """Step 1: use a vision LLM to describe the rendered character."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

    img_b64 = _downscale_for_vision(image_bytes)
    chat = LlmChat(
        api_key=api_key,
        session_id=f"pixel-desc-{uuid.uuid4().hex[:12]}",
        system_message=VISION_SYSTEM,
    ).with_model("openai", "gpt-4o")
    msg = UserMessage(text=VISION_PROMPT, file_contents=[ImageContent(image_base64=img_b64)])
    text = await chat.send_message(msg)
    return (text or "").strip()


async def generate_pixel_image(prompt: str, api_key: str) -> bytes:
    """Step 2: text-to-image with gpt-image-1. Returns PNG bytes."""
    from emergentintegrations.llm.openai.image_generation import OpenAIImageGeneration

    image_gen = OpenAIImageGeneration(api_key=api_key)
    images = await image_gen.generate_images(
        prompt=prompt,
        model="gpt-image-1",
        number_of_images=1,
        quality="low",
    )
    if not images:
        raise RuntimeError("No image returned by gpt-image-1")
    return images[0]


PIXEL_EDIT_PROMPT = (
    "Recreate the person in this image as an Everskies-style pixel-art chibi mini "
    "character (a cute dress-up-game avatar with clean, crisp pixel shading and soft "
    "outlines). Keep the SAME hairstyle, hair color, facial features and expression, "
    "and faithfully reproduce every clothing item, its colors and patterns, the "
    "footwear and any accessories the person is wearing. Draw ONE complete mini "
    "character, full body, standing front view, centered on a plain solid pure-white "
    "background. No text, no watermark, no extra characters, no props besides what is worn."
)


async def generate_everskies_pixel(render_bytes: bytes) -> bytes:
    """Full pipeline. Returns PNG bytes of the Everskies-style pixel mini.

    Uses Gemini Nano Banana (gemini-3.1-flash-image-preview) image-to-image editing:
    the actual try-on render is fed directly to the model so the pixel character
    faithfully copies the real outfit/hair/accessories (single call).

    Raises on any failure so the caller can fall back to the local pixelator.
    """
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise RuntimeError("EMERGENT_LLM_KEY not configured")

    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

    img_b64 = _downscale_for_vision(render_bytes, max_side=768)
    chat = LlmChat(
        api_key=api_key,
        session_id=f"pixel-i2i-{uuid.uuid4().hex[:12]}",
        system_message="You are a meticulous pixel-art character artist.",
    ).with_model("gemini", "gemini-3.1-flash-image-preview").with_params(modalities=["image", "text"])

    msg = UserMessage(text=PIXEL_EDIT_PROMPT, file_contents=[ImageContent(image_base64=img_b64)])
    _text, images = await chat.send_message_multimodal_response(msg)
    if not images:
        raise RuntimeError("Gemini returned no image for pixel generation")
    return base64.b64decode(images[0]["data"])

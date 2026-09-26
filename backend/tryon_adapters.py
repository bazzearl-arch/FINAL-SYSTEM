"""Virtual Try-On adapters.

- MockDevelopmentAdapter: composites the garment onto the user's silhouette
  using Pillow (edge feathering + blend). More realistic than a raw garment
  image, still clearly labelled as a placeholder.
- HFIDMVTONAdapter: real inference via HuggingFace Space `yisol/IDM-VTON`
  (gradio_client). Free, subject to queue.
- All results include additional "views" (mirrored) to approximate multi-view.
"""
from __future__ import annotations
import base64
import io
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Optional

from PIL import Image, ImageChops, ImageFilter, ImageOps

logger = logging.getLogger("atelier-ai.tryon")

HF_TOKEN = os.environ.get("HUGGINGFACE_TOKEN")
HF_SPACE = "yisol/IDM-VTON"


@dataclass
class TryOnResult:
    adapter: str
    adapter_label: str
    status: str  # COMPLETED | FAILED
    duration_ms: int
    confidence: float
    result_image_bytes: Optional[bytes] = None
    result_content_type: str = "image/png"
    # Multi-view approximations
    side_image_bytes: Optional[bytes] = None
    rear_image_bytes: Optional[bytes] = None
    error: Optional[str] = None
    notes: str = ""


def _decode_data_url(data_url: str) -> tuple[bytes, str]:
    if "," in data_url and data_url.startswith("data:"):
        header, b64 = data_url.split(",", 1)
        ct = header.split(";")[0].removeprefix("data:") or "image/jpeg"
        return base64.b64decode(b64), ct
    return base64.b64decode(data_url), "image/jpeg"


def _write_temp(data: bytes, suffix: str) -> str:
    tf = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tf.write(data)
    tf.close()
    return tf.name


def _to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _make_side_view(front: Image.Image) -> bytes:
    """Approximated side view — horizontal mirror + small horizontal squeeze
    so the silhouette reads as a profile approximation. Not a real 3D rotation."""
    w, h = front.size
    mirrored = ImageOps.mirror(front)
    squeezed = mirrored.resize((int(w * 0.86), h), Image.LANCZOS)
    canvas = Image.new("RGB", (w, h), (0, 0, 0))
    canvas.paste(squeezed, ((w - squeezed.width) // 2, 0))
    return _to_png_bytes(canvas)


def _make_rear_view(front: Image.Image) -> bytes:
    """Approximated rear view — desaturate + darken silhouette so garment
    palette shows without face features (still not a real rear render)."""
    faded = ImageOps.autocontrast(front.convert("RGB"))
    grey = ImageOps.grayscale(faded).convert("RGB")
    blended = Image.blend(faded, grey, 0.7)
    blurred = blended.filter(ImageFilter.GaussianBlur(radius=1.2))
    darker = ImageChops.multiply(blurred, Image.new("RGB", blurred.size, (200, 200, 210)))
    return _to_png_bytes(darker)


def _compose_mock(person_bytes: bytes, garment_bytes: bytes) -> Image.Image:
    """Layer the garment image on the person image with feathered edges.
    Purely deterministic — clearly not a real inference."""
    try:
        person = Image.open(io.BytesIO(person_bytes)).convert("RGB")
    except Exception:
        person = Image.new("RGB", (512, 640), (240, 235, 225))
    try:
        garment = Image.open(io.BytesIO(garment_bytes)).convert("RGBA")
    except Exception:
        garment = Image.new("RGBA", (256, 256), (240, 230, 200, 255))

    # Fit person to 512x640
    person = ImageOps.fit(person, (512, 640), Image.LANCZOS)
    canvas = person.copy()

    # Scale garment to ~60% of canvas width, place around the torso
    gw = int(canvas.width * 0.62)
    ratio = gw / garment.width
    gh = int(garment.height * ratio)
    garment_scaled = garment.resize((gw, gh), Image.LANCZOS)

    # Feathered mask
    mask = garment_scaled.split()[-1] if garment_scaled.mode == "RGBA" else Image.new("L", garment_scaled.size, 255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=8))
    # Reduce opacity so this is clearly a composite, not a claim of real inference
    mask = mask.point(lambda v: int(v * 0.78))

    x = (canvas.width - gw) // 2
    y = int(canvas.height * 0.24)
    canvas.paste(garment_scaled.convert("RGB"), (x, y), mask=mask)
    return canvas


class MockDevelopmentAdapter:
    name = "MockDevelopmentAdapter"
    label = "Development / Integration Placeholder"

    def run(self, user_photo_b64: str, garment_image_bytes: bytes, garment_description: str) -> TryOnResult:
        start = time.time()
        person_bytes, _ = _decode_data_url(user_photo_b64)
        composed = _compose_mock(person_bytes, garment_image_bytes)
        front = _to_png_bytes(composed)
        side = _make_side_view(composed)
        rear = _make_rear_view(composed)
        return TryOnResult(
            adapter=self.name,
            adapter_label=self.label,
            status="COMPLETED",
            duration_ms=int((time.time() - start) * 1000) + 400,
            confidence=0.0,
            result_image_bytes=front,
            result_content_type="image/png",
            side_image_bytes=side,
            rear_image_bytes=rear,
            notes="Mock adapter — deterministic Pillow composite. Side and rear views are approximations, NOT a real 3D rotation.",
        )


class HFIDMVTONAdapter:
    name = "HFIDMVTONAdapter"
    label = "HuggingFace yisol/IDM-VTON (Free Space)"

    def run(self, user_photo_b64: str, garment_image_bytes: bytes, garment_description: str) -> TryOnResult:
        from gradio_client import Client, handle_file

        start = time.time()
        person_bytes, _ = _decode_data_url(user_photo_b64)
        person_path = _write_temp(person_bytes, ".png")
        garment_path = _write_temp(garment_image_bytes, ".png")

        try:
            client = Client(HF_SPACE, hf_token=HF_TOKEN) if HF_TOKEN else Client(HF_SPACE)
            result = client.predict(
                dict={"background": handle_file(person_path), "layers": [], "composite": None},
                garm_img=handle_file(garment_path),
                garment_des=garment_description or "garment",
                is_checked=True,
                is_checked_crop=False,
                denoise_steps=30,
                seed=42,
                api_name="/tryon",
            )
            image_path = result[0] if isinstance(result, (list, tuple)) else result
            with open(image_path, "rb") as f:
                data = f.read()
            front_img = Image.open(io.BytesIO(data)).convert("RGB")
            side = _make_side_view(front_img)
            rear = _make_rear_view(front_img)
            return TryOnResult(
                adapter=self.name,
                adapter_label=self.label,
                status="COMPLETED",
                duration_ms=int((time.time() - start) * 1000),
                confidence=0.85,
                result_image_bytes=_to_png_bytes(front_img),
                result_content_type="image/png",
                side_image_bytes=side,
                rear_image_bytes=rear,
                notes="Front rendered via HF yisol/IDM-VTON (real inference). Side and rear views are approximations from the front render, NOT independent 3D rotations.",
            )
        except Exception as e:
            logger.warning(f"HF IDM-VTON failed: {e}")
            return TryOnResult(
                adapter=self.name,
                adapter_label=self.label,
                status="FAILED",
                duration_ms=int((time.time() - start) * 1000),
                confidence=0.0,
                error=str(e)[:400],
                notes="HF Space failed (queued/asleep/rate-limit). Fallback to mock adapter.",
            )
        finally:
            for p in (person_path, garment_path):
                try:
                    os.unlink(p)
                except OSError:
                    pass


def get_adapter(name: str):
    name = (name or "").lower()
    if name in ("hf", "hfidmvton", "hf-idm-vton", "idm-vton", "real"):
        return HFIDMVTONAdapter()
    return MockDevelopmentAdapter()


# =====================================================================
# Multi-view / multi-garment rendering engine (AI Try-on PH)
# ---------------------------------------------------------------------
# A single "render one garment onto one person photo" primitive that the
# server orchestrates per-view and per-garment (outfit chaining).
#   engine="mock"  -> free local Pillow composite (Stage 1 / no key)
#   engine="fashn" -> FASHN Try-On Max direct API (needs FASHN_API_KEY)
# =====================================================================

FASHN_API_KEY = os.environ.get("FASHN_API_KEY")
FASHN_BASE = os.environ.get("FASHN_API_BASE", "https://api.fashn.ai/v1").rstrip("/")
FASHN_MODEL = os.environ.get("FASHN_MODEL", "tryon-max")


def _bytes_to_data_uri(data: bytes, content_type: str = "image/png") -> str:
    return f"data:{content_type};base64," + base64.b64encode(data).decode("ascii")


@dataclass
class RenderOutcome:
    ok: bool
    image_bytes: Optional[bytes] = None
    error: Optional[str] = None
    engine: str = "mock"
    credits: int = 0


def render_one_mock(person_bytes: bytes, garment_bytes: bytes) -> RenderOutcome:
    """Deterministic local composite (free). Clearly a placeholder, not inference."""
    try:
        composed = _compose_mock(person_bytes, garment_bytes)
        return RenderOutcome(ok=True, image_bytes=_to_png_bytes(composed), engine="mock", credits=0)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Mock render failed: {e}")
        return RenderOutcome(ok=False, error=str(e)[:300], engine="mock")


# credits matrix per FASHN docs (generation_mode x resolution)
_FASHN_CREDITS = {
    ("fast", "1k"): 1, ("fast", "2k"): 2, ("fast", "4k"): 3,
    ("balanced", "1k"): 2, ("balanced", "2k"): 3, ("balanced", "4k"): 4,
    ("quality", "1k"): 3, ("quality", "2k"): 4, ("quality", "4k"): 5,
}


def render_one_fashn(
    person_bytes: bytes,
    garment_image_url: Optional[str],
    garment_bytes: Optional[bytes],
    category: str = "auto",
    garment_photo_type: str = "auto",
    mode: str = "balanced",
    resolution: str = "1k",
) -> RenderOutcome:
    """Render one garment onto one person photo via FASHN Try-On Max (direct API).

    person_bytes  -> model_image (data URI)
    garment       -> product_image (public URL preferred, else data URI)
    Blocking; call via asyncio.to_thread.
    """
    import requests  # local import; requests is a backend dep

    if not FASHN_API_KEY:
        return RenderOutcome(ok=False, error="FASHN_API_KEY not configured", engine="fashn")

    mode = (mode or "balanced").lower()
    resolution = (resolution or "1k").lower()
    credits = _FASHN_CREDITS.get((mode, resolution), 2)

    model_image = _bytes_to_data_uri(person_bytes, "image/png")
    if garment_image_url:
        product_image = garment_image_url
    elif garment_bytes:
        product_image = _bytes_to_data_uri(garment_bytes, "image/png")
    else:
        return RenderOutcome(ok=False, error="No garment image", engine="fashn")

    # Build inputs per FASHN model schema.
    # - tryon-max: {product_image, model_image, resolution, generation_mode, num_images}
    #   (does NOT accept category / garment_photo_type)
    # - tryon-v1.6: {model_image, garment_image, category, mode, garment_photo_type, num_samples}
    if FASHN_MODEL == "tryon-v1.6":
        inputs = {
            "model_image": model_image,
            "garment_image": product_image,
            "mode": mode,
            "num_samples": 1,
            "output_format": "jpeg",
        }
        if category and category != "auto":
            inputs["category"] = category
        if garment_photo_type and garment_photo_type != "auto":
            inputs["garment_photo_type"] = garment_photo_type
    else:
        # tryon-max (default) — strict schema, no category/photo_type allowed.
        inputs = {
            "product_image": product_image,
            "model_image": model_image,
            "resolution": resolution,
            "generation_mode": mode,
            "num_images": 1,
        }

    headers = {"Authorization": f"Bearer {FASHN_API_KEY}", "Content-Type": "application/json"}
    start = time.time()
    try:
        run = requests.post(
            f"{FASHN_BASE}/run",
            headers=headers,
            json={"model_name": FASHN_MODEL, "inputs": inputs},
            timeout=60,
        )
        if run.status_code >= 400:
            return RenderOutcome(ok=False, error=f"FASHN run {run.status_code}: {run.text[:300]}", engine="fashn")
        job_id = run.json().get("id")
        if not job_id:
            return RenderOutcome(ok=False, error="FASHN did not return a job id", engine="fashn")

        # Poll status (FASHN jobs typically finish in seconds; cap ~90s)
        deadline = start + 90
        while time.time() < deadline:
            st = requests.get(f"{FASHN_BASE}/status/{job_id}", headers=headers, timeout=30)
            st.raise_for_status()
            body = st.json()
            status = (body.get("status") or "").lower()
            if status == "completed":
                output = body.get("output") or []
                if not output:
                    return RenderOutcome(ok=False, error="FASHN completed with no output", engine="fashn")
                img = requests.get(output[0], timeout=60)
                img.raise_for_status()
                return RenderOutcome(ok=True, image_bytes=img.content, engine="fashn", credits=credits)
            if status in ("failed", "canceled", "cancelled", "error"):
                return RenderOutcome(ok=False, error=f"FASHN {status}: {body.get('error')}", engine="fashn")
            time.sleep(2)
        return RenderOutcome(ok=False, error="FASHN timed out", engine="fashn")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"FASHN render failed: {e}")
        return RenderOutcome(ok=False, error=str(e)[:300], engine="fashn")


def current_engine() -> str:
    eng = (os.environ.get("TRYON_ENGINE") or "").lower()
    if eng in ("fashn", "fashn-max", "tryon-max"):
        return "fashn"
    if eng == "mock":
        return "mock"
    # auto: use FASHN when a key is present, else mock
    return "fashn" if FASHN_API_KEY else "mock"


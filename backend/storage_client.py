"""Emergent Object Storage client.

Uploads private user photos and try-on renders. DB is the source of truth for
file records (is_deleted flag). Frontend downloads through the API which
enforces ownership.
"""
import os
import logging
from pathlib import Path

import requests

logger = logging.getLogger("atelier-ai.storage")

STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
APP_PREFIX = os.environ.get("APP_STORAGE_PREFIX", "atelier-ai")

# Local-disk fallback: when no EMERGENT_LLM_KEY is configured, persist objects on
# the local filesystem so photo/render storage works for free. (Single-pod MVP;
# for multi-pod production, wire a real object store or store bytes in the DB.)
LOCAL_STORAGE_DIR = Path(os.environ.get("LOCAL_STORAGE_DIR", "/app/backend/storage_data"))
USE_LOCAL = not EMERGENT_KEY

_storage_key: str | None = None

_CT_BY_EXT = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif",
}


def init_storage(force: bool = False) -> str:
    global _storage_key
    if USE_LOCAL:
        LOCAL_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("Object storage: using LOCAL disk fallback at %s", LOCAL_STORAGE_DIR)
        return "local"
    if _storage_key and not force:
        return _storage_key
    if not EMERGENT_KEY:
        raise RuntimeError("EMERGENT_LLM_KEY missing")
    resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30)
    resp.raise_for_status()
    _storage_key = resp.json()["storage_key"]
    logger.info("Object storage session initialised")
    return _storage_key


def _local_full_path(path: str) -> Path:
    full = (LOCAL_STORAGE_DIR / path).resolve()
    # Guard against path traversal
    if not str(full).startswith(str(LOCAL_STORAGE_DIR.resolve())):
        raise RuntimeError("Invalid storage path")
    return full


def put_object(path: str, data: bytes, content_type: str) -> dict:
    if USE_LOCAL:
        init_storage()
        full = _local_full_path(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)
        return {"path": path, "size": len(data)}
    key = init_storage()
    resp = requests.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data,
        timeout=120,
    )
    if resp.status_code == 404:
        key = init_storage(force=True)
        resp = requests.put(
            f"{STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": key, "Content-Type": content_type},
            data=data,
            timeout=120,
        )
    resp.raise_for_status()
    return resp.json()


def get_object(path: str) -> tuple[bytes, str]:
    if USE_LOCAL:
        init_storage()
        full = _local_full_path(path)
        if not full.exists():
            raise FileNotFoundError(path)
        ext = full.suffix.lstrip(".").lower()
        return full.read_bytes(), _CT_BY_EXT.get(ext, "application/octet-stream")
    key = init_storage()
    resp = requests.get(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key},
        timeout=60,
    )
    if resp.status_code == 404:
        key = init_storage(force=True)
        resp = requests.get(
            f"{STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": key},
            timeout=60,
        )
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


def user_path(user_id: str, kind: str, filename: str) -> str:
    """kind: 'photos' | 'renders'"""
    return f"{APP_PREFIX}/{kind}/{user_id}/{filename}"

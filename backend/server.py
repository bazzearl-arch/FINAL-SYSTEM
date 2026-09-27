from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import logging
import uuid
import secrets
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Any, Annotated

import bcrypt
import jwt
import uuid as _uuid
import httpx as _httpx
import csv as _csv
import io as _io
import asyncio
import base64
from bson import ObjectId
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, status, Query, Header
from fastapi.responses import StreamingResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, ConfigDict, EmailStr, BeforeValidator

import storage_client
import tryon_adapters
from tryon_adapters import (
    MockDevelopmentAdapter, HFIDMVTONAdapter, get_adapter, _decode_data_url,
    render_one_mock, render_one_fashn, current_engine,
)
from product_connectors import (
    import_json_feed, import_csv_feed, scrape_lazada, scrape_shopee, scrape_generic_url,
    NormalizedProduct,
)
from email_service import send_email, password_reset_html
from pixel_avatar import make_pixel_avatar
from pixel_ai import generate_everskies_pixel

# -------------------- Config --------------------
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = "HS256"
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="AI Try-on PH API")
api = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("atelier-ai")


# -------------------- Helpers --------------------
def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=60 * 24),
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "refresh",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    response.set_cookie("access_token", access, httponly=True, secure=True, samesite="none", max_age=60 * 60 * 24, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=True, samesite="none", max_age=60 * 60 * 24 * 7, path="/")


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")


def serialize_doc(doc: dict) -> dict:
    if not doc:
        return doc
    doc = dict(doc)
    if "_id" in doc:
        doc["id"] = str(doc.pop("_id"))
    doc.pop("password_hash", None)
    return doc


async def get_token_payload(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(request: Request) -> dict:
    payload = await get_token_payload(request)
    try:
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid user id")
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return serialize_doc(user)


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# -------------------- Category / Gender config --------------------
# Canonical categories used across the app + try-on engine.
CANONICAL_CATEGORIES = [
    "tops", "bottoms", "one-pieces", "outerwear", "shoes", "bags", "jewelry", "hats", "accessories",
]

# Gender-specific category menus (data-level filtering, not just visual).
GENDER_CATEGORIES = {
    "men": ["tops", "bottoms", "outerwear", "shoes", "hats", "bags", "accessories"],
    "women": ["tops", "bottoms", "one-pieces", "outerwear", "shoes", "hats", "bags", "jewelry", "accessories"],
}

# Map legacy category values -> canonical.
_CATEGORY_ALIASES = {
    "top": "tops", "tops": "tops",
    "bottom": "bottoms", "bottoms": "bottoms", "pants": "bottoms", "trousers": "bottoms",
    "dress": "one-pieces", "dresses": "one-pieces", "one-piece": "one-pieces", "one-pieces": "one-pieces",
    "jacket": "outerwear", "coat": "outerwear", "outerwear": "outerwear",
    "shoe": "shoes", "shoes": "shoes", "footwear": "shoes",
    "bag": "bags", "bags": "bags",
    "jewelry": "jewelry", "jewellery": "jewelry",
    "hat": "hats", "hats": "hats", "cap": "hats",
    "accessory": "accessories", "accessories": "accessories",
}

# Categories FASHN Try-On Max can actually render onto the body.
RENDERABLE_CATEGORIES = {"tops", "bottoms", "one-pieces", "outerwear", "shoes", "hats", "jewelry", "bags"}

# Order in which garments are chained onto the photo (base layers first).
_CHAIN_ORDER = ["one-pieces", "tops", "bottoms", "outerwear", "shoes", "bags", "hats", "jewelry"]

# FASHN category param per canonical category (tops/bottoms/one-pieces or auto).
_FASHN_CATEGORY = {
    "tops": "tops", "outerwear": "tops",
    "bottoms": "bottoms",
    "one-pieces": "one-pieces",
}


def canonical_category(value: Optional[str]) -> str:
    return _CATEGORY_ALIASES.get((value or "").strip().lower(), (value or "").strip().lower() or "accessories")


def normalize_gender(value: Optional[str]) -> str:
    v = (value or "").strip().lower()
    if v in ("man", "men", "male", "m"):
        return "men"
    if v in ("woman", "women", "female", "f", "w"):
        return "women"
    return "unisex"


async def get_settings() -> dict:
    doc = await db.app_settings.find_one({"_id": "tryon"})
    engine = tryon_adapters.current_engine()
    return {
        "engine": (doc or {}).get("engine", engine),
        "mode": (doc or {}).get("mode", "balanced"),
        "resolution": (doc or {}).get("resolution", "1k"),
        "fashn_key_configured": bool(os.environ.get("FASHN_API_KEY")),
    }



# -------------------- Models --------------------
class RegisterInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str = Field(min_length=1)


class LoginInput(BaseModel):
    email: EmailStr
    password: str


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    chest_cm: Optional[float] = None
    waist_cm: Optional[float] = None
    hips_cm: Optional[float] = None
    preferred_fit: Optional[str] = None
    preferred_styles: Optional[List[str]] = None
    avatar_url: Optional[str] = None


class ProductInput(BaseModel):
    name: str
    description: Optional[str] = ""
    brand: Optional[str] = ""
    category: str  # tops, bottoms, one-pieces, outerwear, shoes, bags, jewelry, hats, accessories
    subcategory: Optional[str] = None
    gender: Optional[str] = "unisex"  # men | women | unisex
    style: Optional[List[str]] = []
    color: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = "PHP"
    image_url: str
    garment_photo_type: Optional[str] = "auto"  # model | flat-lay | auto
    source_platform: Optional[str] = "manual"  # platform/store name
    source_url: Optional[str] = None  # legacy field
    product_url: Optional[str] = None  # EXACT product listing URL
    tags: Optional[List[str]] = []
    active: bool = True


class WardrobeItemInput(BaseModel):
    product_id: str


class OutfitInput(BaseModel):
    name: str
    items: dict  # {top: product_id, bottom: product_id, ...}


class TryOnInput(BaseModel):
    photo_base64: str  # user photo (data URL or base64)
    product_ids: List[str]
    adapter: Optional[str] = "mock"  # "mock" | "hf" (real IDM-VTON)


class TryOnMultiInput(BaseModel):
    gender: Optional[str] = "unisex"
    photos: dict  # {"front": dataURL, "left": ..., "right": ..., "rear": ...}
    product_ids: List[str]  # ordered outfit items


class SettingsInput(BaseModel):
    engine: Optional[str] = None      # mock | fashn
    mode: Optional[str] = None        # fast | balanced | quality
    resolution: Optional[str] = None  # 1k | 2k | 4k


class ImportCSVInput(BaseModel):
    payload: str  # raw CSV text
    default_gender: Optional[str] = "unisex"


class AdminTestRenderInput(BaseModel):
    photo_base64: str
    product_id: str


class ImportJSONInput(BaseModel):
    payload: str
    auto_save: bool = True


class ImportURLInput(BaseModel):
    url: str
    auto_save: bool = True


class ForgotPasswordInput(BaseModel):
    email: EmailStr


class ResetPasswordInput(BaseModel):
    token: str
    password: str = Field(min_length=6)


class GoogleCallbackInput(BaseModel):
    session_id: str


class PixelAvatarInput(BaseModel):
    session_id: str
    pixel_size: int = 48
    posterize_bits: int = 3


class ShoppingClick(BaseModel):
    product_id: str
    platform: str


# -------------------- Startup --------------------
async def seed_admin_and_data():
    admin_email = os.environ["ADMIN_EMAIL"].lower()
    admin_password = os.environ["ADMIN_PASSWORD"]
    existing = await db.users.find_one({"email": admin_email})
    if existing is None:
        await db.users.insert_one({
            "email": admin_email,
            "password_hash": hash_password(admin_password),
            "name": "Admin",
            "role": "admin",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("Seeded admin user")
    elif not verify_password(admin_password, existing["password_hash"]):
        await db.users.update_one(
            {"email": admin_email},
            {"$set": {"password_hash": hash_password(admin_password), "role": "admin"}},
        )

    # Seed products if empty
    count = await db.products.count_documents({})
    if count == 0:
        sample = [
            # ---- Women ----
            {"name": "Minimalist Tailored Trench Blazer", "brand": "Kultura", "category": "outerwear", "gender": "women", "style": ["Minimalist", "Formal"], "color": "Beige", "price": 4500,
             "image_url": "https://images.unsplash.com/photo-1551232864-3f0890e580d9?crop=entropy&cs=srgb&fm=jpg&w=800&q=80",
             "source_platform": "Zalora PH", "product_url": "https://www.zalora.com.ph/p/kultura-tailored-trench-blazer-4500123.html", "garment_photo_type": "flat-lay", "tags": ["outerwear", "editorial"]},
            {"name": "Earthy Knit Top", "brand": "Penshoppe", "category": "tops", "gender": "women", "style": ["Casual", "Minimalist"], "color": "Cream", "price": 890,
             "image_url": "https://images.pexels.com/photos/35675692/pexels-photo-35675692.jpeg?auto=compress&cs=tinysrgb&w=800",
             "source_platform": "Lazada", "product_url": "https://www.lazada.com.ph/products/earthy-knit-top-i2109887654.html", "garment_photo_type": "model", "tags": ["knit"]},
            {"name": "Linen Wide-Leg Trousers", "brand": "Kultura", "category": "bottoms", "gender": "women", "style": ["Minimalist", "Formal"], "color": "Sand", "price": 1990,
             "image_url": "https://images.unsplash.com/photo-1548883354-94bcfe321cbb?crop=entropy&cs=srgb&fm=jpg&w=800&q=80",
             "source_platform": "Shopee", "product_url": "https://shopee.ph/Linen-Wide-Leg-Trousers-i.123456.789012", "garment_photo_type": "flat-lay", "tags": ["linen"]},
            {"name": "Silk Slip Dress", "brand": "Kashieca", "category": "one-pieces", "gender": "women", "style": ["Formal", "Modern"], "color": "Emerald", "price": 2790,
             "image_url": "https://images.unsplash.com/photo-1595777457583-95e059d581b8?crop=entropy&cs=srgb&fm=jpg&w=800&q=80",
             "source_platform": "Lazada", "product_url": "https://www.lazada.com.ph/products/silk-slip-dress-i3345566778.html", "garment_photo_type": "model", "tags": ["silk", "evening"]},
            {"name": "Filipiniana Modern Terno", "brand": "Kultura", "category": "one-pieces", "gender": "women", "style": ["Filipiniana", "Formal"], "color": "Ivory", "price": 6890,
             "image_url": "https://images.unsplash.com/photo-1566174053879-31528523f8ae?crop=entropy&cs=srgb&fm=jpg&w=800&q=80",
             "source_platform": "Kultura", "product_url": None, "garment_photo_type": "model", "tags": ["filipiniana", "traditional"]},
            {"name": "Gold Geometric Pendant", "brand": "Suyen Jewelry", "category": "jewelry", "gender": "women", "subcategory": "necklace", "style": ["Minimalist"], "color": "Gold", "price": 1290,
             "image_url": "https://images.unsplash.com/photo-1721103418218-416182aca079?crop=entropy&cs=srgb&fm=jpg&w=800&q=80",
             "source_platform": "Lazada", "product_url": "https://www.lazada.com.ph/products/gold-geometric-pendant-i5567788990.html", "garment_photo_type": "flat-lay", "tags": ["gold"]},
            # ---- Men ----
            {"name": "Monochrome Oversized Suit Blazer", "brand": "Bench", "category": "outerwear", "gender": "men", "style": ["Modern", "Smart Casual"], "color": "Charcoal", "price": 3200,
             "image_url": "https://images.pexels.com/photos/5745783/pexels-photo-5745783.jpeg?auto=compress&cs=tinysrgb&w=800",
             "source_platform": "Shopee", "product_url": "https://shopee.ph/Monochrome-Oversized-Blazer-i.223344.556677", "garment_photo_type": "model", "tags": ["monochrome", "suit"]},
            {"name": "Classic White Oxford Shirt", "brand": "Penshoppe", "category": "tops", "gender": "men", "style": ["Smart Casual", "Formal"], "color": "White", "price": 1290,
             "image_url": "https://images.unsplash.com/photo-1602810318383-e386cc2a3ccf?crop=entropy&cs=srgb&fm=jpg&w=800&q=80",
             "source_platform": "Lazada", "product_url": "https://www.lazada.com.ph/products/classic-white-oxford-shirt-i7788990011.html", "garment_photo_type": "model", "tags": ["shirt"]},
            {"name": "Slim Denim Jeans", "brand": "Bench", "category": "bottoms", "gender": "men", "style": ["Casual", "Streetwear"], "color": "Indigo", "price": 1490,
             "image_url": "https://images.unsplash.com/photo-1541099649105-f69ad21f3246?crop=entropy&cs=srgb&fm=jpg&w=800&q=80",
             "source_platform": "Zalora PH", "product_url": "https://www.zalora.com.ph/p/bench-slim-denim-jeans-1490998.html", "garment_photo_type": "flat-lay", "tags": ["denim"]},
            {"name": "Structured Baseball Cap", "brand": "World Balance", "category": "hats", "gender": "men", "style": ["Casual", "Streetwear"], "color": "Black", "price": 590,
             "image_url": "https://images.unsplash.com/photo-1588850561407-ed78c282e89b?crop=entropy&cs=srgb&fm=jpg&w=800&q=80",
             "source_platform": "Shopee", "product_url": "https://shopee.ph/Structured-Baseball-Cap-i.334455.667788", "garment_photo_type": "flat-lay", "tags": ["cap"]},
            # ---- Unisex ----
            {"name": "White Leather Sneakers", "brand": "World Balance", "category": "shoes", "gender": "unisex", "style": ["Casual", "Streetwear"], "color": "White", "price": 1590,
             "image_url": "https://images.unsplash.com/photo-1549298916-b41d501d3772?crop=entropy&cs=srgb&fm=jpg&w=800&q=80",
             "source_platform": "Shopee", "product_url": "https://shopee.ph/White-Leather-Sneakers-i.445566.778899", "garment_photo_type": "flat-lay", "tags": ["sneakers"]},
            {"name": "Leather Ankle Boots", "brand": "Rusty Lopez", "category": "shoes", "gender": "unisex", "style": ["Formal", "Modern"], "color": "Black", "price": 2490,
             "image_url": "https://images.unsplash.com/photo-1543163521-1bf539c55dd2?crop=entropy&cs=srgb&fm=jpg&w=800&q=80",
             "source_platform": "Lazada", "product_url": "https://www.lazada.com.ph/products/leather-ankle-boots-i9900112233.html", "garment_photo_type": "flat-lay", "tags": ["boots"]},
            {"name": "Metallic Structured Tote", "brand": "SM Accessories", "category": "bags", "gender": "unisex", "subcategory": "bag", "style": ["Modern"], "color": "Silver", "price": 1990,
             "image_url": "https://images.unsplash.com/photo-1589363358751-ab05797e5629?crop=entropy&cs=srgb&fm=jpg&w=800&q=80",
             "source_platform": "Shopee", "product_url": None, "garment_photo_type": "flat-lay", "tags": ["bag"]},
        ]
        now = datetime.now(timezone.utc).isoformat()
        for p in sample:
            p.setdefault("description", "")
            p.setdefault("subcategory", None)
            p.setdefault("tags", [])
            p.setdefault("currency", "PHP")
            p.setdefault("gender", "unisex")
            p.setdefault("garment_photo_type", "auto")
            purl = p.get("product_url")
            p["source_url"] = purl
            # Seed demo links are illustrative; flag them so admin verifies/replaces.
            p["url_status"] = "example" if purl else "missing"
            p["active"] = True
            p["created_at"] = now
            p["updated_at"] = now
        await db.products.insert_many(sample)
        logger.info(f"Seeded {len(sample)} products")


@app.on_event("startup")
async def startup_event():
    await db.users.create_index("email", unique=True)
    await db.products.create_index("category")
    await db.wardrobe_items.create_index("user_id")
    await db.saved_outfits.create_index("user_id")
    await db.try_on_sessions.create_index("user_id")
    await db.audit_logs.create_index("timestamp")
    await db.file_records.create_index([("user_id", 1), ("kind", 1)])
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.password_reset_tokens.create_index("token", unique=True)
    await db.pixel_avatars.create_index("user_id")
    await seed_admin_and_data()

    try:
        storage_client.init_storage()
    except Exception as e:
        logger.warning(f"Object storage init failed at startup (will retry on demand): {e}")

    # Write test credentials memory file
    creds_path = Path("/app/memory/test_credentials.md")
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    creds_path.write_text(
        f"""# Test Credentials

## Admin
- Email: {os.environ['ADMIN_EMAIL']}
- Password: {os.environ['ADMIN_PASSWORD']}
- Role: admin

## Auth endpoints
- POST /api/auth/register
- POST /api/auth/login
- POST /api/auth/logout
- GET /api/auth/me
"""
    )


@app.on_event("shutdown")
async def shutdown_event():
    client.close()


# -------------------- Health --------------------
@api.get("/")
async def root():
    return {"service": "Atelier AI Virtual Try-On", "status": "operational"}


@api.get("/health")
async def health():
    result = {"database": "unknown", "ai_service": "development_placeholder", "storage": "unknown"}
    try:
        await db.command("ping")
        result["database"] = "operational"
    except Exception:
        result["database"] = "unavailable"
    try:
        storage_client.init_storage()
        result["storage"] = "operational (emergent object storage)"
    except Exception:
        result["storage"] = "unavailable"
    result["ai_service"] = "mock + hf_idm_vton (free space, best-effort)"
    return result


# -------------------- Auth --------------------
@api.post("/auth/register")
async def register(input: RegisterInput, response: Response):
    email = input.email.lower()
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user_doc = {
        "email": email,
        "password_hash": hash_password(input.password),
        "name": input.name,
        "role": "user",
        "profile": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = await db.users.insert_one(user_doc)
    uid = str(result.inserted_id)
    access = create_access_token(uid, email, "user")
    refresh = create_refresh_token(uid)
    set_auth_cookies(response, access, refresh)
    return {"id": uid, "email": email, "name": input.name, "role": "user"}


@api.post("/auth/login")
async def login(input: LoginInput, response: Response):
    email = input.email.lower()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(input.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    uid = str(user["_id"])
    access = create_access_token(uid, email, user.get("role", "user"))
    refresh = create_refresh_token(uid)
    set_auth_cookies(response, access, refresh)
    return serialize_doc(user)


@api.post("/auth/logout")
async def logout(response: Response, _user: dict = Depends(get_current_user)):
    clear_auth_cookies(response)
    return {"ok": True}


@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return user


@api.put("/auth/profile")
async def update_profile(update: ProfileUpdate, user: dict = Depends(get_current_user)):
    updates = {k: v for k, v in update.model_dump().items() if v is not None}
    if updates:
        set_ops = {f"profile.{k}": v for k, v in updates.items() if k != "name"}
        if "name" in updates:
            set_ops["name"] = updates["name"]
        await db.users.update_one({"_id": ObjectId(user["id"])}, {"$set": set_ops})
    updated = await db.users.find_one({"_id": ObjectId(user["id"])})
    return serialize_doc(updated)


# -------------------- Password Reset --------------------
@api.post("/auth/google/callback")
async def google_callback(input: GoogleCallbackInput, response: Response):
    """Exchange Emergent Auth session_id for a user session.

    Backend calls Emergent Auth's session-data endpoint (never the frontend).
    We match/create the user by email and then issue our normal JWT cookies so
    the rest of the app (which already uses cookie-based JWT) works unchanged.
    """
    try:
        async with _httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
                headers={"X-Session-ID": input.session_id},
            )
        if r.status_code >= 400:
            logger.warning(f"Emergent Auth exchange failed: {r.status_code} {r.text[:200]}")
            raise HTTPException(status_code=401, detail="Google sign-in failed")
        data = r.json()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Emergent Auth network error: {e}")
        raise HTTPException(status_code=502, detail="Auth provider unreachable")

    email = (data.get("email") or "").lower().strip()
    if not email:
        raise HTTPException(status_code=400, detail="Google account has no email")
    name = data.get("name") or email.split("@")[0]
    picture = data.get("picture") or ""
    google_id = data.get("id") or ""

    existing = await db.users.find_one({"email": email})
    now = datetime.now(timezone.utc).isoformat()
    if existing:
        await db.users.update_one(
            {"_id": existing["_id"]},
            {"$set": {
                "google_id": google_id,
                "avatar_url": picture or existing.get("avatar_url"),
                "last_login_at": now,
                "auth_provider": existing.get("auth_provider") or "google",
            }},
        )
        uid = str(existing["_id"])
        role = existing.get("role", "user")
    else:
        insert_doc = {
            "email": email,
            "name": name,
            "role": "user",
            "google_id": google_id,
            "avatar_url": picture,
            "auth_provider": "google",
            "password_hash": hash_password(secrets.token_urlsafe(32)),  # random unusable pw
            "profile": {},
            "created_at": now,
            "last_login_at": now,
        }
        r2 = await db.users.insert_one(insert_doc)
        uid = str(r2.inserted_id)
        role = "user"

    access = create_access_token(uid, email, role)
    refresh = create_refresh_token(uid)
    set_auth_cookies(response, access, refresh)
    user = await db.users.find_one({"_id": ObjectId(uid)})
    return serialize_doc(user)


# -------------------- Password Reset --------------------
@api.post("/auth/forgot-password")
async def forgot_password(input: ForgotPasswordInput):
    email = input.email.lower()
    user = await db.users.find_one({"email": email})
    # Don't leak whether the account exists
    if user:
        token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        await db.password_reset_tokens.insert_one({
            "token": token, "user_id": str(user["_id"]), "email": email,
            "expires_at": expires, "used": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        reset_url = f"{FRONTEND_URL.rstrip('/')}/reset-password?token={token}"
        try:
            result = await send_email(
                to=email,
                subject="Reset your AtelierAI password",
                html=password_reset_html(user.get("name", ""), reset_url),
            )
            logger.info(f"Password reset email for {email}: {result}")
        except Exception as e:
            logger.error(f"Password reset send error for {email}: {e}")
        # Always log to backend log so devs can retrieve the link if email is unset
        logger.warning(f"[PASSWORD RESET] URL for {email}: {reset_url}")
    return {"ok": True, "message": "If that email is registered, a reset link has been sent."}


@api.post("/auth/reset-password")
async def reset_password(input: ResetPasswordInput):
    rec = await db.password_reset_tokens.find_one({"token": input.token, "used": False})
    if not rec:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    # Compare timezone-aware
    expires = rec["expires_at"]
    if isinstance(expires, str):
        expires = datetime.fromisoformat(expires)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Token expired")
    await db.users.update_one(
        {"_id": ObjectId(rec["user_id"])},
        {"$set": {"password_hash": hash_password(input.password)}},
    )
    await db.password_reset_tokens.update_one(
        {"_id": rec["_id"]}, {"$set": {"used": True}}
    )
    return {"ok": True}


# -------------------- Products (public read) --------------------
@api.get("/products")
async def list_products(
    category: Optional[str] = None,
    gender: Optional[str] = None,
    style: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(60, le=200),
):
    q: dict = {"active": True}
    if category:
        q["category"] = canonical_category(category)
    if gender:
        g = normalize_gender(gender)
        if g in ("men", "women"):
            # data-level gender filter: show the gender's items + unisex
            q["gender"] = {"$in": [g, "unisex", None]}
    if style:
        q["style"] = style
    if search:
        q["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"brand": {"$regex": search, "$options": "i"}},
            {"tags": {"$regex": search, "$options": "i"}},
        ]
    cursor = db.products.find(q).limit(limit)
    docs = await cursor.to_list(length=limit)
    return [serialize_doc(d) for d in docs]


@api.get("/categories")
async def list_categories(gender: Optional[str] = None):
    """Return the category menu appropriate for the selected gender."""
    g = normalize_gender(gender)
    cats = GENDER_CATEGORIES.get(g, CANONICAL_CATEGORIES)
    return {"gender": g, "categories": cats}


@api.get("/products/{product_id}")
async def get_product(product_id: str):
    try:
        doc = await db.products.find_one({"_id": ObjectId(product_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid product id")
    if not doc:
        raise HTTPException(status_code=404, detail="Product not found")
    return serialize_doc(doc)


# -------------------- Wardrobe (auth) --------------------
@api.get("/wardrobe/items")
async def list_wardrobe_items(user: dict = Depends(get_current_user)):
    docs = await db.wardrobe_items.find({"user_id": user["id"]}).to_list(length=500)
    result = []
    for d in docs:
        prod = None
        try:
            prod = await db.products.find_one({"_id": ObjectId(d["product_id"])})
        except Exception:
            pass
        item = serialize_doc(d)
        item["product"] = serialize_doc(prod) if prod else None
        result.append(item)
    return result


@api.post("/wardrobe/items")
async def add_wardrobe_item(input: WardrobeItemInput, user: dict = Depends(get_current_user)):
    existing = await db.wardrobe_items.find_one({"user_id": user["id"], "product_id": input.product_id})
    if existing:
        return serialize_doc(existing)
    doc = {
        "user_id": user["id"],
        "product_id": input.product_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    r = await db.wardrobe_items.insert_one(doc)
    doc["_id"] = r.inserted_id
    return serialize_doc(doc)


@api.delete("/wardrobe/items/{item_id}")
async def remove_wardrobe_item(item_id: str, user: dict = Depends(get_current_user)):
    try:
        r = await db.wardrobe_items.delete_one({"_id": ObjectId(item_id), "user_id": user["id"]})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


# -------------------- Outfits --------------------
@api.get("/wardrobe/outfits")
async def list_outfits(user: dict = Depends(get_current_user)):
    docs = await db.saved_outfits.find({"user_id": user["id"]}).sort("created_at", -1).to_list(length=200)
    return [serialize_doc(d) for d in docs]


@api.post("/wardrobe/outfits")
async def save_outfit(input: OutfitInput, user: dict = Depends(get_current_user)):
    doc = {
        "user_id": user["id"],
        "name": input.name,
        "items": input.items,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    r = await db.saved_outfits.insert_one(doc)
    doc["_id"] = r.inserted_id
    return serialize_doc(doc)


@api.delete("/wardrobe/outfits/{outfit_id}")
async def delete_outfit(outfit_id: str, user: dict = Depends(get_current_user)):
    try:
        r = await db.saved_outfits.delete_one({"_id": ObjectId(outfit_id), "user_id": user["id"]})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


# -------------------- Files (private, owner-only) --------------------
async def save_bytes_for_user(user_id: str, kind: str, data: bytes, content_type: str) -> dict:
    """Upload to object storage and record in DB. Returns file record."""
    ext = {
        "image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
        "image/webp": "webp", "image/gif": "gif",
    }.get(content_type, "bin")
    filename = f"{_uuid.uuid4()}.{ext}"
    path = storage_client.user_path(user_id, kind, filename)
    result = storage_client.put_object(path, data, content_type)
    record = {
        "user_id": user_id,
        "kind": kind,
        "storage_path": result["path"],
        "content_type": content_type,
        "size": result.get("size", len(data)),
        "is_deleted": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    r = await db.file_records.insert_one(record)
    record["_id"] = r.inserted_id
    return record


@api.get("/files/{file_id}")
async def get_file(file_id: str, user: dict = Depends(get_current_user)):
    try:
        rec = await db.file_records.find_one({"_id": ObjectId(file_id), "is_deleted": False})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file id")
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")
    if rec["user_id"] != user["id"] and user.get("role") != "admin":
        # Admins never access private user photos even so — enforce strict rule
        raise HTTPException(status_code=403, detail="Forbidden")
    # Admin cannot view private photos (per PDF policy)
    if user.get("role") == "admin" and rec["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Admin cannot access private user files")
    data, ct = storage_client.get_object(rec["storage_path"])
    return Response(content=data, media_type=rec.get("content_type", ct))


# -------------------- Try-On --------------------
@api.post("/tryon/generate")
async def generate_tryon(input: TryOnInput, user: dict = Depends(get_current_user)):
    """Runs the selected adapter. HF real adapter falls back to Mock on failure.
    All artefacts (user photo + result render) go to private Object Storage."""
    if not input.photo_base64:
        raise HTTPException(status_code=400, detail="Photo is required")
    if not input.product_ids:
        raise HTTPException(status_code=400, detail="At least one product required")

    products = []
    for pid in input.product_ids:
        try:
            p = await db.products.find_one({"_id": ObjectId(pid)})
            if p: products.append(serialize_doc(p))
        except Exception:
            continue
    if not products:
        raise HTTPException(status_code=404, detail="No valid products")

    # Store user photo in object storage
    user_bytes, user_ct = _decode_data_url(input.photo_base64)
    try:
        photo_rec = await save_bytes_for_user(user["id"], "photos", user_bytes, user_ct)
    except Exception as e:
        logger.error(f"Photo upload failed: {e}")
        raise HTTPException(status_code=500, detail="Could not store photo")
    photo_file_id = str(photo_rec["_id"])

    # Fetch garment image bytes (first product) for the model
    garment = products[0]
    async with _httpx.AsyncClient(timeout=20) as c:
        try:
            gr = await c.get(garment["image_url"])
            gr.raise_for_status()
            garment_bytes = gr.content
        except Exception:
            garment_bytes = user_bytes  # graceful

    # Pick adapter
    requested = (input.adapter or "mock").lower()
    adapter = get_adapter(requested)
    # Run in a thread since gradio_client / bcrypt are blocking
    result = await asyncio.to_thread(
        adapter.run, input.photo_base64, garment_bytes, garment.get("name", "")
    )

    # If HF failed, fall back to Mock so the user still sees a preview
    used_fallback = False
    if result.status == "FAILED" and requested != "mock":
        used_fallback = True
        result = await asyncio.to_thread(
            MockDevelopmentAdapter().run, input.photo_base64, garment_bytes, garment.get("name", "")
        )

    # Store rendered result (front + side/rear approximations)
    result_file_id = None
    side_file_id = None
    rear_file_id = None
    if result.result_image_bytes:
        try:
            rrec = await save_bytes_for_user(
                user["id"], "renders", result.result_image_bytes, result.result_content_type
            )
            result_file_id = str(rrec["_id"])
        except Exception as e:
            logger.warning(f"Render upload failed: {e}")
    if result.side_image_bytes:
        try:
            srec = await save_bytes_for_user(user["id"], "renders", result.side_image_bytes, "image/png")
            side_file_id = str(srec["_id"])
        except Exception as e:
            logger.warning(f"Side view upload failed: {e}")
    if result.rear_image_bytes:
        try:
            rrec2 = await save_bytes_for_user(user["id"], "renders", result.rear_image_bytes, "image/png")
            rear_file_id = str(rrec2["_id"])
        except Exception as e:
            logger.warning(f"Rear view upload failed: {e}")

    session = {
        "user_id": user["id"],
        "adapter": result.adapter,
        "adapter_label": result.adapter_label,
        "requested_adapter": requested,
        "used_fallback": used_fallback,
        "status": result.status,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": result.duration_ms,
        "confidence": result.confidence,
        "error": result.error,
        "notes": result.notes,
        "product_ids": input.product_ids,
        "products_snapshot": products,
        "photo_file_id": photo_file_id,
        "result_file_id": result_file_id,
        "side_file_id": side_file_id,
        "rear_file_id": rear_file_id,
        "is_favorite": False,
        "pixel_avatar_id": None,
    }
    r = await db.try_on_sessions.insert_one(session)
    session["_id"] = r.inserted_id
    return serialize_doc(session)


# -------------------- Try-On (multi-view, outfit chaining) --------------------
VIEW_KEYS = ["front", "left", "right", "rear"]


async def _fetch_bytes(url: str) -> Optional[bytes]:
    try:
        async with _httpx.AsyncClient(timeout=25, follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
            return r.content
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Garment fetch failed ({url[:60]}): {e}")
        return None


def _order_products_for_chaining(products: List[dict]) -> List[dict]:
    def key(p):
        cat = canonical_category(p.get("category"))
        try:
            return _CHAIN_ORDER.index(cat)
        except ValueError:
            return len(_CHAIN_ORDER)
    return sorted(products, key=key)


async def _process_multiview(session_id, user_id: str, photos: dict, products: List[dict], settings: dict):
    """Background task: chain garments onto each provided view, store renders."""
    engine = settings["engine"]
    mode = settings["mode"]
    resolution = settings["resolution"]
    ordered = _order_products_for_chaining(products)

    # Which products can actually be rendered by the current engine.
    def is_renderable(p) -> bool:
        cat = canonical_category(p.get("category"))
        if engine == "mock":
            return True
        return cat in RENDERABLE_CATEGORIES

    # Pre-fetch garment bytes (for mock) once.
    garment_cache: dict = {}
    for p in ordered:
        if is_renderable(p):
            garment_cache[p["id"]] = await _fetch_bytes(p.get("image_url", ""))

    views_out: dict = {}
    any_ok = False
    first_error = None

    for vk in VIEW_KEYS:
        data_url = photos.get(vk)
        if not data_url:
            continue
        try:
            person_bytes, _ct = _decode_data_url(data_url)
        except Exception:
            continue

        applied = []
        view_error = None
        for p in ordered:
            if not is_renderable(p):
                continue
            cat = canonical_category(p.get("category"))
            gtype = p.get("garment_photo_type") or "auto"
            if engine == "fashn":
                outcome = await asyncio.to_thread(
                    render_one_fashn,
                    person_bytes,
                    p.get("image_url"),
                    garment_cache.get(p["id"]),
                    _FASHN_CATEGORY.get(cat, "auto"),
                    gtype,
                    mode,
                    resolution,
                )
            else:
                gb = garment_cache.get(p["id"]) or person_bytes
                outcome = await asyncio.to_thread(render_one_mock, person_bytes, gb)

            if outcome.ok and outcome.image_bytes:
                person_bytes = outcome.image_bytes
                applied.append(p["id"])
            else:
                view_error = outcome.error
                if first_error is None:
                    first_error = outcome.error

        # store the (possibly chained) view render
        file_id = None
        try:
            rec = await save_bytes_for_user(user_id, "renders", person_bytes, "image/png")
            file_id = str(rec["_id"])
            any_ok = True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"View render store failed ({vk}): {e}")
            view_error = view_error or str(e)[:200]

        views_out[vk] = {"file_id": file_id, "applied_product_ids": applied, "error": view_error}

    status = "COMPLETED" if any_ok else "FAILED"
    await db.try_on_sessions.update_one(
        {"_id": session_id},
        {"$set": {
            "status": status,
            "views": views_out,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error": None if any_ok else (first_error or "All views failed to render"),
        }},
    )


@api.post("/tryon/multiview")
async def generate_multiview(input: TryOnMultiInput, user: dict = Depends(get_current_user)):
    """4-view outfit try-on. Chains selected garments across the provided photos.
    Returns immediately with status 'processing'; poll GET /tryon/sessions/{id}."""
    photos = {k: v for k, v in (input.photos or {}).items() if k in VIEW_KEYS and v}
    if not photos.get("front"):
        raise HTTPException(status_code=400, detail="A front photo is required")
    if not input.product_ids:
        raise HTTPException(status_code=400, detail="Select at least one product")

    products = []
    for pid in input.product_ids:
        try:
            p = await db.products.find_one({"_id": ObjectId(pid)})
            if p:
                products.append(serialize_doc(p))
        except Exception:
            continue
    if not products:
        raise HTTPException(status_code=404, detail="No valid products")

    settings = await get_settings()

    # Store the user's photos (private)
    photo_file_ids = {}
    for vk, durl in photos.items():
        try:
            pb, pct = _decode_data_url(durl)
            rec = await save_bytes_for_user(user["id"], "photos", pb, pct)
            photo_file_ids[vk] = str(rec["_id"])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Photo store failed ({vk}): {e}")

    # items_used snapshot (all selected products, with render capability + links)
    items_used = []
    for p in products:
        cat = canonical_category(p.get("category"))
        renderable = True if settings["engine"] == "mock" else (cat in RENDERABLE_CATEGORIES)
        items_used.append({
            "product_id": p["id"],
            "name": p.get("name"),
            "brand": p.get("brand"),
            "category": cat,
            "price": p.get("price"),
            "currency": p.get("currency", "PHP"),
            "image_url": p.get("image_url"),
            "platform": p.get("source_platform") or p.get("platform"),
            "product_url": p.get("product_url") or p.get("source_url"),
            "url_status": p.get("url_status", "ok" if (p.get("product_url") or p.get("source_url")) else "missing"),
            "rendered": renderable,
        })

    session = {
        "user_id": user["id"],
        "kind": "multiview",
        "engine": settings["engine"],
        "mode": settings["mode"],
        "resolution": settings["resolution"],
        "gender": normalize_gender(input.gender),
        "status": "processing",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "product_ids": input.product_ids,
        "items_used": items_used,
        "photo_file_ids": photo_file_ids,
        "views": {},
        "error": None,
        "is_favorite": False,
    }
    r = await db.try_on_sessions.insert_one(session)
    session["_id"] = r.inserted_id

    asyncio.create_task(_process_multiview(r.inserted_id, user["id"], photos, products, settings))
    return serialize_doc(session)



@api.get("/tryon/sessions")
async def list_sessions(user: dict = Depends(get_current_user)):
    docs = await db.try_on_sessions.find({"user_id": user["id"]}).sort("started_at", -1).to_list(length=100)
    return [serialize_doc(d) for d in docs]


@api.get("/tryon/sessions/{session_id}")
async def get_session(session_id: str, user: dict = Depends(get_current_user)):
    try:
        doc = await db.try_on_sessions.find_one({"_id": ObjectId(session_id), "user_id": user["id"]})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return serialize_doc(doc)


@api.delete("/tryon/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    try:
        r = await db.try_on_sessions.delete_one({"_id": ObjectId(session_id), "user_id": user["id"]})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


@api.post("/tryon/sessions/{session_id}/favorite")
async def favorite_session(session_id: str, user: dict = Depends(get_current_user)):
    """Mark a try-on session as favorite AND auto-generate a pixel-art mini."""
    try:
        session = await db.try_on_sessions.find_one({
            "_id": ObjectId(session_id), "user_id": user["id"],
        })
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    if not session:
        raise HTTPException(status_code=404, detail="Not found")

    already_favorite = bool(session.get("is_favorite"))
    pixel_avatar_id = session.get("pixel_avatar_id")
    pixel_file_id = None
    pixel_is_ai = False

    # Resolve the FRONT-view render as the pixel source. Handles both single
    # renders (result_file_id) and multi-view sessions (views.front.file_id).
    def _front_source(sess):
        views = sess.get("views") or {}
        for key in ("front", "left", "right", "rear"):
            v = views.get(key) or {}
            if v.get("file_id"):
                return v["file_id"]
        return sess.get("result_file_id") or sess.get("photo_file_id")

    # Auto-create pixel avatar if not already generated
    if not pixel_avatar_id:
        source_file_id = _front_source(session)
        if source_file_id:
            try:
                src_rec = await db.file_records.find_one({"_id": ObjectId(source_file_id)})
                if src_rec:
                    src_bytes, _ = storage_client.get_object(src_rec["storage_path"])
                    # Try AI Everskies-style pixel art first; fall back to the
                    # local algorithmic pixelator so the flow never fully breaks.
                    png = None
                    try:
                        png = await generate_everskies_pixel(src_bytes)
                        pixel_is_ai = True
                    except Exception as ai_err:
                        logger.warning(f"AI pixel gen failed, using local pixelator: {ai_err}")
                        png = await asyncio.to_thread(make_pixel_avatar, src_bytes, 40, 384, 3)
                        pixel_is_ai = False
                    rec = await save_bytes_for_user(user["id"], "pixels", png, "image/png")
                    pixel_file_id = str(rec["_id"])
                    now = datetime.now(timezone.utc).isoformat()
                    avatar_doc = {
                        "user_id": user["id"],
                        "session_id": session_id,
                        "file_id": pixel_file_id,
                        "style": "everskies" if pixel_is_ai else "pixelate",
                        "ai_generated": pixel_is_ai,
                        "pixel_size": 40,
                        "posterize_bits": 3,
                        "auto_generated": True,
                        "created_at": now,
                    }
                    r = await db.pixel_avatars.insert_one(avatar_doc)
                    pixel_avatar_id = str(r.inserted_id)
            except Exception as e:
                logger.warning(f"Auto pixel avatar failed: {e}")
    elif pixel_avatar_id:
        # Already generated earlier — surface its file_id for display.
        try:
            av = await db.pixel_avatars.find_one({"_id": ObjectId(pixel_avatar_id)})
            if av:
                pixel_file_id = av.get("file_id")
                pixel_is_ai = bool(av.get("ai_generated"))
        except Exception:
            pass

    await db.try_on_sessions.update_one(
        {"_id": ObjectId(session_id)},
        {"$set": {
            "is_favorite": True,
            "favorited_at": datetime.now(timezone.utc).isoformat(),
            "pixel_avatar_id": pixel_avatar_id,
        }},
    )
    updated = await db.try_on_sessions.find_one({"_id": ObjectId(session_id)})
    return {
        **serialize_doc(updated),
        "auto_pixel_created": bool(pixel_avatar_id) and not already_favorite,
        "pixel_file_id": pixel_file_id,
        "pixel_is_ai": pixel_is_ai,
    }


@api.post("/tryon/sessions/{session_id}/unfavorite")
async def unfavorite_session(session_id: str, user: dict = Depends(get_current_user)):
    try:
        r = await db.try_on_sessions.update_one(
            {"_id": ObjectId(session_id), "user_id": user["id"]},
            {"$set": {"is_favorite": False}},
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    updated = await db.try_on_sessions.find_one({"_id": ObjectId(session_id)})
    return serialize_doc(updated)


@api.get("/tryon/favorites")
async def list_favorites(user: dict = Depends(get_current_user)):
    docs = await db.try_on_sessions.find(
        {"user_id": user["id"], "is_favorite": True}
    ).sort("favorited_at", -1).to_list(length=200)
    return [serialize_doc(d) for d in docs]


# -------------------- Pixel Avatar --------------------
@api.post("/pixel-avatars")
async def create_pixel_avatar(input: PixelAvatarInput, user: dict = Depends(get_current_user)):
    """Convert a saved try-on render into a pixel-art avatar and store as a new file."""
    try:
        session = await db.try_on_sessions.find_one({
            "_id": ObjectId(input.session_id), "user_id": user["id"],
        })
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid session id")
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    source_file_id = session.get("result_file_id") or session.get("photo_file_id")
    if not source_file_id:
        raise HTTPException(status_code=400, detail="Session has no rendered image")
    src_rec = await db.file_records.find_one({"_id": ObjectId(source_file_id)})
    if not src_rec:
        raise HTTPException(status_code=404, detail="Source file missing")
    src_bytes, _ = storage_client.get_object(src_rec["storage_path"])

    pixel_size = max(16, min(input.pixel_size, 128))
    posterize = max(1, min(input.posterize_bits, 8))
    png = await asyncio.to_thread(make_pixel_avatar, src_bytes, pixel_size, 384, posterize)
    rec = await save_bytes_for_user(user["id"], "pixels", png, "image/png")

    doc = {
        "user_id": user["id"],
        "session_id": input.session_id,
        "file_id": str(rec["_id"]),
        "pixel_size": pixel_size,
        "posterize_bits": posterize,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    r = await db.pixel_avatars.insert_one(doc)
    doc["_id"] = r.inserted_id
    return serialize_doc(doc)


@api.get("/pixel-avatars")
async def list_pixel_avatars(user: dict = Depends(get_current_user)):
    docs = await db.pixel_avatars.find({"user_id": user["id"]}).sort("created_at", -1).to_list(length=200)
    return [serialize_doc(d) for d in docs]


@api.delete("/pixel-avatars/{avatar_id}")
async def delete_pixel_avatar(avatar_id: str, user: dict = Depends(get_current_user)):
    try:
        doc = await db.pixel_avatars.find_one({"_id": ObjectId(avatar_id), "user_id": user["id"]})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    # Soft-delete the file record
    if doc.get("file_id"):
        try:
            await db.file_records.update_one(
                {"_id": ObjectId(doc["file_id"])},
                {"$set": {"is_deleted": True}},
            )
        except Exception:
            pass
    await db.pixel_avatars.delete_one({"_id": doc["_id"]})
    return {"ok": True}


# -------------------- Shopping Click Tracking --------------------
@api.post("/shopping/click")
async def track_click(input: ShoppingClick, request: Request):
    doc = {
        "product_id": input.product_id,
        "platform": input.platform,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    # Track user id if authenticated (optional)
    try:
        payload = await get_token_payload(request)
        doc["user_id"] = payload.get("sub")
    except HTTPException:
        pass
    await db.shopping_clicks.insert_one(doc)
    return {"ok": True}


# -------------------- Admin --------------------
@api.get("/admin/stats")
async def admin_stats(_admin: dict = Depends(require_admin)):
    users = await db.users.count_documents({"role": "user"})
    products = await db.products.count_documents({})
    tryons = await db.try_on_sessions.count_documents({})
    clicks = await db.shopping_clicks.count_documents({})
    outfits = await db.saved_outfits.count_documents({})
    # Top categories by product count
    pipe = [{"$group": {"_id": "$category", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}]
    cats_cursor = db.products.aggregate(pipe)
    categories = [{"category": d["_id"], "count": d["count"]} async for d in cats_cursor]
    return {
        "total_users": users,
        "total_products": products,
        "total_tryons": tryons,
        "total_shopping_clicks": clicks,
        "total_outfits": outfits,
        "categories": categories,
    }


@api.get("/admin/products")
async def admin_list_products(_admin: dict = Depends(require_admin), limit: int = 200):
    docs = await db.products.find({}).sort("created_at", -1).to_list(length=limit)
    return [serialize_doc(d) for d in docs]


@api.post("/admin/products")
async def admin_create_product(input: ProductInput, admin: dict = Depends(require_admin)):
    now = datetime.now(timezone.utc).isoformat()
    doc = input.model_dump()
    doc["category"] = canonical_category(doc.get("category"))
    doc["gender"] = normalize_gender(doc.get("gender"))
    purl = doc.get("product_url") or doc.get("source_url")
    doc["product_url"] = purl
    doc["source_url"] = purl
    doc["url_status"] = "ok" if purl else "missing"
    doc["admin_edited"] = True
    doc["created_at"] = now
    doc["updated_at"] = now
    r = await db.products.insert_one(doc)
    await db.audit_logs.insert_one({
        "admin_id": admin["id"], "action": "product.create", "resource_id": str(r.inserted_id),
        "timestamp": now, "status": "success",
    })
    doc["_id"] = r.inserted_id
    return serialize_doc(doc)


@api.put("/admin/products/{product_id}")
async def admin_update_product(product_id: str, input: ProductInput, admin: dict = Depends(require_admin)):
    now = datetime.now(timezone.utc).isoformat()
    doc = input.model_dump()
    doc["category"] = canonical_category(doc.get("category"))
    doc["gender"] = normalize_gender(doc.get("gender"))
    purl = doc.get("product_url") or doc.get("source_url")
    doc["product_url"] = purl
    doc["source_url"] = purl
    doc["url_status"] = "ok" if purl else "missing"
    doc["admin_edited"] = True
    doc["updated_at"] = now
    try:
        r = await db.products.update_one({"_id": ObjectId(product_id)}, {"$set": doc})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    await db.audit_logs.insert_one({
        "admin_id": admin["id"], "action": "product.update", "resource_id": product_id,
        "timestamp": now, "status": "success",
    })
    updated = await db.products.find_one({"_id": ObjectId(product_id)})
    return serialize_doc(updated)


@api.delete("/admin/products/{product_id}")
async def admin_delete_product(product_id: str, admin: dict = Depends(require_admin)):
    try:
        r = await db.products.delete_one({"_id": ObjectId(product_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    await db.audit_logs.insert_one({
        "admin_id": admin["id"], "action": "product.delete", "resource_id": product_id,
        "timestamp": datetime.now(timezone.utc).isoformat(), "status": "success",
    })
    return {"ok": True}


@api.get("/admin/users")
async def admin_users(_admin: dict = Depends(require_admin)):
    docs = await db.users.find({}, {"password_hash": 0}).to_list(length=500)
    return [serialize_doc(d) for d in docs]


@api.get("/admin/audit-logs")
async def admin_audit(_admin: dict = Depends(require_admin), limit: int = 100):
    docs = await db.audit_logs.find({}).sort("timestamp", -1).to_list(length=limit)
    return [serialize_doc(d) for d in docs]


# -------------------- Admin: Settings, CSV import, Test render --------------------
@api.get("/admin/settings")
async def admin_get_settings(_admin: dict = Depends(require_admin)):
    return await get_settings()


@api.put("/admin/settings")
async def admin_update_settings(input: SettingsInput, admin: dict = Depends(require_admin)):
    update = {}
    if input.engine in ("mock", "fashn"):
        update["engine"] = input.engine
    if input.mode in ("fast", "balanced", "quality"):
        update["mode"] = input.mode
    if input.resolution in ("1k", "2k", "4k"):
        update["resolution"] = input.resolution
    if update:
        await db.app_settings.update_one({"_id": "tryon"}, {"$set": update}, upsert=True)
    return await get_settings()


@api.get("/admin/fashn/credits")
async def admin_fashn_credits(_admin: dict = Depends(require_admin)):
    """Return remaining FASHN credits by proxying https://api.fashn.ai/v1/credits.
    Never exposes the API key to the client."""
    import requests as _requests
    key = os.environ.get("FASHN_API_KEY")
    if not key:
        return {"ok": False, "configured": False, "error": "FASHN_API_KEY not set"}
    try:
        r = _requests.get(
            "https://api.fashn.ai/v1/credits",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
    except Exception as e:
        return {"ok": False, "configured": True, "error": f"network: {e}"}
    if r.status_code != 200:
        return {"ok": False, "configured": True, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
    try:
        body = r.json()
    except Exception:
        return {"ok": False, "configured": True, "error": "non-JSON response"}
    credits = body.get("credits") or {}
    return {
        "ok": True,
        "configured": True,
        "total": int(credits.get("total") or 0),
        "subscription": int(credits.get("subscription") or 0),
        "on_demand": int(credits.get("on_demand") or 0),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


@api.post("/admin/import/csv")
async def admin_import_csv(input: ImportCSVInput, admin: dict = Depends(require_admin)):
    """Bulk import products from CSV text. Columns (case-insensitive):
    product_name/name, gender, category, price, currency, image_url,
    product_url, platform, garment_photo_type, brand, description, color."""
    import csv as _csv
    import io as _io

    reader = _csv.DictReader(_io.StringIO(input.payload))
    now = datetime.now(timezone.utc).isoformat()
    saved = 0
    errors = 0
    samples = []

    def g(row, *keys, default=None):
        for k in row:
            if k and k.strip().lower() in keys:
                v = (row[k] or "").strip()
                if v:
                    return v
        return default

    for row in reader:
        try:
            name = g(row, "product_name", "name")
            image_url = g(row, "image_url", "image")
            if not name or not image_url:
                errors += 1
                if len(samples) < 5:
                    samples.append(f"Missing name/image_url: {dict(row)}")
                continue
            product_url = g(row, "product_url", "url")
            price_raw = g(row, "price")
            try:
                price = float(str(price_raw).replace(",", "")) if price_raw else None
            except Exception:
                price = None
            doc = {
                "name": name,
                "description": g(row, "description", default=""),
                "brand": g(row, "brand", default=""),
                "category": canonical_category(g(row, "category", default="accessories")),
                "gender": normalize_gender(g(row, "gender", default=input.default_gender)),
                "color": g(row, "color"),
                "price": price,
                "currency": g(row, "currency", default="PHP"),
                "image_url": image_url,
                "garment_photo_type": (g(row, "garment_photo_type", "photo_type", default="auto") or "auto").lower(),
                "source_platform": g(row, "platform", "source_platform", default="manual"),
                "product_url": product_url,
                "source_url": product_url,
                "url_status": "ok" if product_url else "missing",
                "tags": [],
                "active": True,
                "updated_at": now,
                "imported_at": now,
                "created_by_admin": admin["id"],
            }
            filt = {"product_url": product_url} if product_url else {"name": name, "brand": doc["brand"]}
            existing = await db.products.find_one(filt)
            if existing:
                await db.products.update_one({"_id": existing["_id"]}, {"$set": doc})
            else:
                doc["created_at"] = now
                await db.products.insert_one(doc)
            saved += 1
        except Exception as e:  # noqa: BLE001
            errors += 1
            if len(samples) < 5:
                samples.append(str(e)[:150])

    await db.import_jobs.insert_one({
        "admin_id": admin["id"], "source": "csv", "status": "success" if saved else "error",
        "imported": saved, "saved": saved, "errors": errors, "error_samples": samples,
        "message": f"CSV import: {saved} saved, {errors} errors", "timestamp": now,
    })
    return {"status": "success" if saved else "error", "saved": saved, "errors": errors, "error_samples": samples}


@api.post("/admin/tryon/test")
async def admin_test_render(input: AdminTestRenderInput, admin: dict = Depends(require_admin)):
    """Single-garment / single-photo render — cheap smoke test of the live engine."""
    if not input.photo_base64:
        raise HTTPException(status_code=400, detail="Photo required")
    try:
        p = await db.products.find_one({"_id": ObjectId(input.product_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid product id")
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    product = serialize_doc(p)
    settings = await get_settings()
    person_bytes, _ = _decode_data_url(input.photo_base64)
    cat = canonical_category(product.get("category"))
    gtype = product.get("garment_photo_type") or "auto"

    if settings["engine"] == "fashn":
        garment_bytes = await _fetch_bytes(product.get("image_url", ""))
        outcome = await asyncio.to_thread(
            render_one_fashn, person_bytes, product.get("image_url"), garment_bytes,
            _FASHN_CATEGORY.get(cat, "auto"), gtype, settings["mode"], settings["resolution"],
        )
    else:
        garment_bytes = await _fetch_bytes(product.get("image_url", "")) or person_bytes
        outcome = await asyncio.to_thread(render_one_mock, person_bytes, garment_bytes)

    if not outcome.ok:
        return {"ok": False, "engine": outcome.engine, "error": outcome.error,
                "credits_estimate": outcome.credits}
    b64 = base64.b64encode(outcome.image_bytes).decode("ascii")
    return {"ok": True, "engine": outcome.engine, "credits_estimate": outcome.credits,
            "image": f"data:image/png;base64,{b64}"}


# -------------------- Admin: Product Import Connectors --------------------
async def _persist_imported(products, admin_id: str, source: str) -> int:
    """Upsert by (source_platform + source_id) if id present, else by (name + brand)."""
    now = datetime.now(timezone.utc).isoformat()
    saved = 0
    for p in products:
        doc = {
            "name": p.name, "description": p.description, "brand": p.brand,
            "category": p.category, "subcategory": p.subcategory,
            "style": p.style, "color": p.color, "price": p.price, "currency": p.currency,
            "image_url": p.image_url, "source_platform": p.source_platform,
            "source_url": p.source_url, "source_id": p.source_id,
            "tags": p.tags, "active": True, "updated_at": now, "imported_at": now,
            "created_by_admin": admin_id,
        }
        if p.source_id:
            filt = {"source_platform": p.source_platform, "source_id": p.source_id}
        else:
            filt = {"name": p.name, "brand": p.brand}
        existing = await db.products.find_one(filt)
        if existing:
            # respect admin-corrections: skip fields flagged as admin_edited
            if not existing.get("admin_edited"):
                await db.products.update_one({"_id": existing["_id"]}, {"$set": doc})
        else:
            doc["created_at"] = now
            await db.products.insert_one(doc)
        saved += 1
    if saved:
        await db.audit_logs.insert_one({
            "admin_id": admin_id, "action": f"import.{source}", "resource_id": None,
            "timestamp": now, "status": "success", "metadata": {"count": saved},
        })
    return saved


@api.post("/admin/import/json")
async def admin_import_json(input: ImportJSONInput, admin: dict = Depends(require_admin)):
    outcome = import_json_feed(input.payload)
    saved = 0
    if input.auto_save and outcome.products:
        saved = await _persist_imported(outcome.products, admin["id"], "json_feed")
    await db.import_jobs.insert_one({
        "admin_id": admin["id"], "source": "json_feed", "status": outcome.status,
        "imported": outcome.imported, "saved": saved, "errors": outcome.errors,
        "error_samples": outcome.error_samples, "message": outcome.message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return {
        "status": outcome.status, "imported": outcome.imported, "saved": saved,
        "errors": outcome.errors, "error_samples": outcome.error_samples,
        "message": outcome.message,
    }


@api.post("/admin/import/url")
async def admin_import_url(input: ImportURLInput, admin: dict = Depends(require_admin)):
    outcome = await asyncio.to_thread(scrape_generic_url, input.url)
    saved = 0
    if input.auto_save and outcome.products:
        saved = await _persist_imported(outcome.products, admin["id"], outcome.source)
    await db.import_jobs.insert_one({
        "admin_id": admin["id"], "source": outcome.source, "status": outcome.status,
        "url": input.url, "imported": outcome.imported, "saved": saved,
        "errors": outcome.errors, "error_samples": outcome.error_samples,
        "message": outcome.message, "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return {
        "status": outcome.status, "source": outcome.source, "imported": outcome.imported,
        "saved": saved, "errors": outcome.errors, "error_samples": outcome.error_samples,
        "message": outcome.message,
        "products_preview": [
            {"name": p.name, "brand": p.brand, "price": p.price, "image_url": p.image_url,
             "category": p.category, "source_url": p.source_url}
            for p in outcome.products[:5]
        ],
    }


@api.get("/admin/import/jobs")
async def admin_import_jobs(_admin: dict = Depends(require_admin), limit: int = 50):
    docs = await db.import_jobs.find({}).sort("timestamp", -1).to_list(length=limit)
    return [serialize_doc(d) for d in docs]


# -------------------- Admin: Research Export --------------------
def _anon(user_id: str) -> str:
    """Deterministic anonymised user id (research-friendly)."""
    import hashlib
    return "u_" + hashlib.sha256((user_id + JWT_SECRET).encode()).hexdigest()[:12]


async def _build_export_rows() -> list[dict]:
    rows = []
    async for s in db.try_on_sessions.find({}):
        rows.append({
            "type": "tryon",
            "anon_user_id": _anon(s.get("user_id", "")),
            "adapter": s.get("adapter"),
            "status": s.get("status"),
            "duration_ms": s.get("duration_ms"),
            "confidence": s.get("confidence"),
            "used_fallback": s.get("used_fallback"),
            "product_count": len(s.get("product_ids") or []),
            "product_categories": ",".join(sorted({p.get("category", "") for p in (s.get("products_snapshot") or [])})),
            "timestamp": s.get("started_at"),
            "target_product_id": None,
            "platform": None,
        })
    async for c in db.shopping_clicks.find({}):
        rows.append({
            "type": "shopping_click",
            "anon_user_id": _anon(c.get("user_id") or "anonymous"),
            "adapter": None, "status": None, "duration_ms": None, "confidence": None,
            "used_fallback": None, "product_count": None, "product_categories": None,
            "timestamp": c.get("timestamp"),
            "target_product_id": c.get("product_id"),
            "platform": c.get("platform"),
        })
    async for o in db.saved_outfits.find({}):
        rows.append({
            "type": "saved_outfit",
            "anon_user_id": _anon(o.get("user_id", "")),
            "adapter": None, "status": None, "duration_ms": None, "confidence": None,
            "used_fallback": None,
            "product_count": len(o.get("items") or {}),
            "product_categories": ",".join(sorted((o.get("items") or {}).keys())),
            "timestamp": o.get("created_at"),
            "target_product_id": None, "platform": None,
        })
    return rows


@api.get("/admin/export")
async def admin_export(format: str = Query("json"), _admin: dict = Depends(require_admin)):
    rows = await _build_export_rows()
    if format.lower() == "csv":
        buf = _io.StringIO()
        cols = [
            "type", "anon_user_id", "timestamp", "adapter", "status", "duration_ms",
            "confidence", "used_fallback", "product_count", "product_categories",
            "target_product_id", "platform",
        ]
        w = _csv.DictWriter(buf, fieldnames=cols)
        w.writeheader()
        for r in rows: w.writerow({k: r.get(k) for k in cols})
        return PlainTextResponse(
            buf.getvalue(),
            headers={"Content-Disposition": 'attachment; filename="atelier_export.csv"'},
            media_type="text/csv",
        )
    return {"count": len(rows), "rows": rows}


# -------------------- Register routes and CORS --------------------
app.include_router(api)

# Explicit origins: configured frontend + local dev. Extra origins (e.g. a custom
# domain) can be added via the CORS_ORIGINS env var as a comma-separated list.
_cors_origins = {FRONTEND_URL, "http://localhost:3000", "http://localhost:3001"}
for _o in (os.environ.get("CORS_ORIGINS") or "").split(","):
    _o = _o.strip()
    if _o:
        _cors_origins.add(_o)

# Regex covers all Emergent-managed hosts (preview + deployed app URLs) so auth
# works whether the app is opened from the preview domain or its public URL.
_cors_origin_regex = r"https://([a-z0-9-]+\.)*(emergentagent\.com|emergent\.host|emergent\.sh)$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_cors_origins),
    allow_origin_regex=_cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

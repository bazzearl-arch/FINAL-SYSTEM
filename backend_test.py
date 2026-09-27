#!/usr/bin/env python3
"""
Backend test for AI Try-on PH - Favorite endpoint with AI pixel generation
Tests the new feature: POST /api/tryon/sessions/{id}/favorite
"""
import requests
import time
import base64
import io
from PIL import Image

# Base URL from frontend/.env
BASE_URL = "https://api-keys-ready-1.preview.emergentagent.com/api"

# Admin credentials from test_credentials.md
ADMIN_EMAIL = "admin@gmail.com"
ADMIN_PASSWORD = "adminpass"

# Test results
results = []

def log(msg, status="INFO"):
    """Log test results"""
    print(f"[{status}] {msg}")
    results.append({"status": status, "message": msg})

def create_small_base64_image(color=(255, 200, 150)):
    """Create a small base64 PNG data URL for testing"""
    img = Image.new('RGB', (200, 300), color=color)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    return f"data:image/png;base64,{b64}"

def test_favorite_endpoint():
    """Main test function"""
    session = requests.Session()
    
    # Step 1: Login as admin
    log("=" * 80)
    log("STEP 1: Login as admin")
    log("=" * 80)
    
    login_resp = session.post(
        f"{BASE_URL}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15
    )
    
    if login_resp.status_code != 200:
        log(f"Login failed: {login_resp.status_code} {login_resp.text[:200]}", "FAIL")
        return False
    
    user_data = login_resp.json()
    log(f"✓ Login successful: {user_data.get('email')} (role: {user_data.get('role')})", "PASS")
    
    # Step 2: Get a product_id
    log("\n" + "=" * 80)
    log("STEP 2: Get product_id for try-on")
    log("=" * 80)
    
    products_resp = session.get(f"{BASE_URL}/products?gender=men&limit=5", timeout=15)
    if products_resp.status_code != 200:
        log(f"Failed to get products: {products_resp.status_code}", "FAIL")
        return False
    
    products = products_resp.json()
    if not products:
        log("No products found", "FAIL")
        return False
    
    product_id = products[0]["id"]
    product_name = products[0]["name"]
    log(f"✓ Selected product: {product_name} (ID: {product_id})", "PASS")
    
    # Step 3: Create multiview try-on session
    log("\n" + "=" * 80)
    log("STEP 3: Create multiview try-on session")
    log("=" * 80)
    
    # Create 4 small base64 images with different colors
    photos = {
        "front": create_small_base64_image((255, 200, 150)),
        "left": create_small_base64_image((200, 255, 150)),
        "right": create_small_base64_image((150, 200, 255)),
        "rear": create_small_base64_image((255, 150, 200))
    }
    
    tryon_payload = {
        "gender": "men",
        "photos": photos,
        "product_ids": [product_id]
    }
    
    log("Creating multiview session...")
    tryon_resp = session.post(
        f"{BASE_URL}/tryon/multiview",
        json=tryon_payload,
        timeout=30
    )
    
    if tryon_resp.status_code != 200:
        log(f"Failed to create try-on session: {tryon_resp.status_code} {tryon_resp.text[:500]}", "FAIL")
        return False
    
    session_data = tryon_resp.json()
    session_id = session_data["id"]
    log(f"✓ Try-on session created: {session_id}", "PASS")
    log(f"  Initial status: {session_data.get('status')}")
    
    # Step 4: Poll until COMPLETED
    log("\n" + "=" * 80)
    log("STEP 4: Poll session until COMPLETED")
    log("=" * 80)
    
    max_polls = 60  # 4 minutes max (4s per poll)
    poll_count = 0
    start_time = time.time()
    
    while poll_count < max_polls:
        poll_count += 1
        time.sleep(4)
        
        poll_resp = session.get(f"{BASE_URL}/tryon/sessions/{session_id}", timeout=15)
        if poll_resp.status_code != 200:
            log(f"Poll failed: {poll_resp.status_code}", "FAIL")
            return False
        
        session_data = poll_resp.json()
        status = session_data.get("status")
        
        if status == "COMPLETED":
            elapsed = time.time() - start_time
            log(f"✓ Session COMPLETED after {poll_count} polls ({elapsed:.1f}s)", "PASS")
            
            # Verify views exist
            views = session_data.get("views", {})
            log(f"  Views available: {list(views.keys())}")
            
            has_front = views.get("front", {}).get("file_id")
            if has_front:
                log(f"  ✓ Front view file_id: {has_front}", "PASS")
            else:
                log("  ✗ No front view file_id found", "WARN")
            
            break
        elif status == "FAILED":
            log(f"Session FAILED: {session_data.get('error')}", "FAIL")
            return False
        else:
            if poll_count % 5 == 0:
                log(f"  Poll {poll_count}: status={status}")
    
    if session_data.get("status") != "COMPLETED":
        log(f"Session did not complete in time (status: {session_data.get('status')})", "FAIL")
        return False
    
    # Step 5: POST /favorite (with long timeout for AI generation)
    log("\n" + "=" * 80)
    log("STEP 5: POST /favorite (AI pixel generation - may take up to 60s)")
    log("=" * 80)
    
    log("Calling /favorite endpoint with 120s timeout...")
    fav_start = time.time()
    
    try:
        fav_resp = session.post(
            f"{BASE_URL}/tryon/sessions/{session_id}/favorite",
            timeout=120  # Long timeout for AI generation
        )
    except requests.Timeout:
        log("Favorite endpoint timed out after 120s", "FAIL")
        return False
    
    fav_elapsed = time.time() - fav_start
    log(f"Favorite call completed in {fav_elapsed:.1f}s")
    
    if fav_resp.status_code != 200:
        log(f"Favorite failed: {fav_resp.status_code} {fav_resp.text[:500]}", "FAIL")
        return False
    
    fav_data = fav_resp.json()
    log(f"✓ Favorite endpoint returned 200", "PASS")
    
    # Verify response fields
    log("\nVerifying response fields:")
    
    is_favorite = fav_data.get("is_favorite")
    log(f"  is_favorite: {is_favorite}")
    if is_favorite is True:
        log(f"  ✓ is_favorite=true", "PASS")
    else:
        log(f"  ✗ is_favorite={is_favorite} (expected true)", "FAIL")
    
    auto_pixel_created = fav_data.get("auto_pixel_created")
    log(f"  auto_pixel_created: {auto_pixel_created}")
    if auto_pixel_created is True:
        log(f"  ✓ auto_pixel_created=true (first time)", "PASS")
    else:
        log(f"  ✗ auto_pixel_created={auto_pixel_created} (expected true on first call)", "FAIL")
    
    pixel_file_id = fav_data.get("pixel_file_id")
    log(f"  pixel_file_id: {pixel_file_id}")
    if pixel_file_id and isinstance(pixel_file_id, str) and len(pixel_file_id) > 0:
        log(f"  ✓ pixel_file_id is non-empty string", "PASS")
    else:
        log(f"  ✗ pixel_file_id is empty or missing", "FAIL")
    
    pixel_is_ai = fav_data.get("pixel_is_ai")
    log(f"  pixel_is_ai: {pixel_is_ai}")
    if pixel_is_ai is True:
        log(f"  ✓ pixel_is_ai=true (AI generation succeeded)", "PASS")
    elif pixel_is_ai is False:
        log(f"  ⚠ pixel_is_ai=false (fell back to local pixelator)", "WARN")
    else:
        log(f"  ✗ pixel_is_ai={pixel_is_ai} (expected boolean)", "FAIL")
    
    # Step 6: GET /files/{pixel_file_id}
    log("\n" + "=" * 80)
    log("STEP 6: Verify pixel image file")
    log("=" * 80)
    
    if pixel_file_id:
        file_resp = session.get(f"{BASE_URL}/files/{pixel_file_id}", timeout=15)
        
        if file_resp.status_code != 200:
            log(f"Failed to get pixel file: {file_resp.status_code}", "FAIL")
        else:
            content_type = file_resp.headers.get("content-type", "")
            content_length = len(file_resp.content)
            
            log(f"✓ GET /files/{pixel_file_id} returned 200", "PASS")
            log(f"  Content-Type: {content_type}")
            log(f"  Content-Length: {content_length} bytes")
            
            if "image/png" in content_type:
                log(f"  ✓ Content-Type is image/png", "PASS")
            else:
                log(f"  ✗ Content-Type is not image/png", "FAIL")
            
            if content_length > 1024:  # >1KB
                log(f"  ✓ Image size > 1KB (real image)", "PASS")
            else:
                log(f"  ✗ Image size <= 1KB (may be empty)", "FAIL")
    else:
        log("Skipping file verification (no pixel_file_id)", "WARN")
    
    # Step 7: Idempotency test - POST /favorite again
    log("\n" + "=" * 80)
    log("STEP 7: Idempotency test - POST /favorite again")
    log("=" * 80)
    
    log("Calling /favorite endpoint again...")
    fav2_resp = session.post(
        f"{BASE_URL}/tryon/sessions/{session_id}/favorite",
        timeout=30  # Should be fast (no regeneration)
    )
    
    if fav2_resp.status_code != 200:
        log(f"Second favorite call failed: {fav2_resp.status_code}", "FAIL")
    else:
        fav2_data = fav2_resp.json()
        log(f"✓ Second favorite call returned 200", "PASS")
        
        auto_pixel_created_2 = fav2_data.get("auto_pixel_created")
        log(f"  auto_pixel_created: {auto_pixel_created_2}")
        
        if auto_pixel_created_2 is False:
            log(f"  ✓ auto_pixel_created=false (no regeneration)", "PASS")
        else:
            log(f"  ✗ auto_pixel_created={auto_pixel_created_2} (expected false, should not regenerate)", "FAIL")
        
        pixel_file_id_2 = fav2_data.get("pixel_file_id")
        if pixel_file_id_2 == pixel_file_id:
            log(f"  ✓ pixel_file_id unchanged: {pixel_file_id_2}", "PASS")
        else:
            log(f"  ✗ pixel_file_id changed (expected same): {pixel_file_id_2}", "FAIL")
    
    # Step 8: POST /unfavorite
    log("\n" + "=" * 80)
    log("STEP 8: POST /unfavorite")
    log("=" * 80)
    
    unfav_resp = session.post(
        f"{BASE_URL}/tryon/sessions/{session_id}/unfavorite",
        timeout=15
    )
    
    if unfav_resp.status_code != 200:
        log(f"Unfavorite failed: {unfav_resp.status_code}", "FAIL")
    else:
        unfav_data = unfav_resp.json()
        log(f"✓ Unfavorite endpoint returned 200", "PASS")
        
        is_favorite_after = unfav_data.get("is_favorite")
        log(f"  is_favorite: {is_favorite_after}")
        
        if is_favorite_after is False:
            log(f"  ✓ is_favorite=false", "PASS")
        else:
            log(f"  ✗ is_favorite={is_favorite_after} (expected false)", "FAIL")
    
    # Step 9: Check GET /api/tryon/favorites
    log("\n" + "=" * 80)
    log("STEP 9: Check GET /api/tryon/favorites")
    log("=" * 80)
    
    favorites_resp = session.get(f"{BASE_URL}/tryon/favorites", timeout=15)
    
    if favorites_resp.status_code != 200:
        log(f"Failed to get favorites: {favorites_resp.status_code}", "FAIL")
    else:
        favorites = favorites_resp.json()
        log(f"✓ GET /tryon/favorites returned 200", "PASS")
        log(f"  Favorites count: {len(favorites)}")
        
        # After unfavorite, our session should NOT be in favorites
        session_in_favorites = any(f.get("id") == session_id for f in favorites)
        if not session_in_favorites:
            log(f"  ✓ Session {session_id} not in favorites (correct after unfavorite)", "PASS")
        else:
            log(f"  ✗ Session {session_id} still in favorites (should be removed)", "FAIL")
    
    # Step 10: Check GET /api/pixel-avatars
    log("\n" + "=" * 80)
    log("STEP 10: Check GET /api/pixel-avatars")
    log("=" * 80)
    
    pixels_resp = session.get(f"{BASE_URL}/pixel-avatars", timeout=15)
    
    if pixels_resp.status_code != 200:
        log(f"Failed to get pixel avatars: {pixels_resp.status_code}", "FAIL")
    else:
        pixels = pixels_resp.json()
        log(f"✓ GET /pixel-avatars returned 200", "PASS")
        log(f"  Pixel avatars count: {len(pixels)}")
        
        # Find our pixel avatar
        our_pixel = None
        for p in pixels:
            if p.get("session_id") == session_id:
                our_pixel = p
                break
        
        if our_pixel:
            log(f"  ✓ Found pixel avatar for session {session_id}", "PASS")
            log(f"    file_id: {our_pixel.get('file_id')}")
            log(f"    style: {our_pixel.get('style')}")
            log(f"    ai_generated: {our_pixel.get('ai_generated')}")
        else:
            log(f"  ⚠ No pixel avatar found for session {session_id}", "WARN")
    
    return True

def print_summary():
    """Print test summary"""
    log("\n" + "=" * 80)
    log("TEST SUMMARY")
    log("=" * 80)
    
    pass_count = sum(1 for r in results if r["status"] == "PASS")
    fail_count = sum(1 for r in results if r["status"] == "FAIL")
    warn_count = sum(1 for r in results if r["status"] == "WARN")
    
    log(f"PASS: {pass_count}")
    log(f"FAIL: {fail_count}")
    log(f"WARN: {warn_count}")
    
    if fail_count > 0:
        log("\nFailed checks:")
        for r in results:
            if r["status"] == "FAIL":
                log(f"  - {r['message']}")
    
    if warn_count > 0:
        log("\nWarnings:")
        for r in results:
            if r["status"] == "WARN":
                log(f"  - {r['message']}")

if __name__ == "__main__":
    try:
        success = test_favorite_endpoint()
        print_summary()
        
        if success and sum(1 for r in results if r["status"] == "FAIL") == 0:
            log("\n✅ ALL TESTS PASSED", "PASS")
        else:
            log("\n❌ SOME TESTS FAILED", "FAIL")
    except Exception as e:
        log(f"\n❌ TEST CRASHED: {e}", "FAIL")
        import traceback
        traceback.print_exc()

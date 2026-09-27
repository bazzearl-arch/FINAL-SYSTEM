#!/usr/bin/env python3
"""
FASHN Multi-View Try-On Test Script
Tests the /api/tryon/multiview endpoint with real FASHN engine
"""

import requests
import time
import base64
from io import BytesIO

BASE_URL = "https://api-keys-ready-1.preview.emergentagent.com"
FASHN_API_KEY = "fa-dmerXc5HGfHl-uKB3RsUF8H3XkFC72PCG6z7M"

# Test credentials
ADMIN_EMAIL = "admin@gmail.com"
ADMIN_PASSWORD = "adminpass"

# Unsplash photo URL for testing
UNSPLASH_PHOTO_URL = "https://images.unsplash.com/photo-1618354691373-d851c5c3a990?w=512&h=768&fit=crop"

def log(message):
    """Print timestamped log message"""
    print(f"[{time.strftime('%H:%M:%S')}] {message}")

def check_fashn_credits_before():
    """Check FASHN credits before test"""
    log("Checking FASHN credits BEFORE test...")
    try:
        response = requests.get(
            "https://api.fashn.ai/v1/credits",
            headers={"Authorization": f"Bearer {FASHN_API_KEY}"}
        )
        if response.status_code == 200:
            data = response.json()
            credits = data.get("credits", {})
            total = credits.get("total", 0) if isinstance(credits, dict) else credits
            log(f"✓ FASHN credits BEFORE: {credits}")
            return credits, total
        else:
            log(f"✗ Failed to get FASHN credits: {response.status_code}")
            return None, None
    except Exception as e:
        log(f"✗ Error checking FASHN credits: {e}")
        return None, None

def check_fashn_credits_after():
    """Check FASHN credits after test"""
    log("Checking FASHN credits AFTER test...")
    try:
        response = requests.get(
            "https://api.fashn.ai/v1/credits",
            headers={"Authorization": f"Bearer {FASHN_API_KEY}"}
        )
        if response.status_code == 200:
            data = response.json()
            credits = data.get("credits", {})
            total = credits.get("total", 0) if isinstance(credits, dict) else credits
            log(f"✓ FASHN credits AFTER: {credits}")
            return credits, total
        else:
            log(f"✗ Failed to get FASHN credits: {response.status_code}")
            return None, None
    except Exception as e:
        log(f"✗ Error checking FASHN credits: {e}")
        return None, None

def login_admin(session):
    """Login as admin and return session"""
    log("Step 1: Logging in as admin...")
    response = session.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    
    if response.status_code == 200:
        log(f"✓ Admin login successful")
        return True
    else:
        log(f"✗ Admin login failed: {response.status_code} - {response.text}")
        return False

def check_admin_settings(session):
    """Check admin settings to confirm FASHN engine is enabled"""
    log("Step 2: Checking admin settings...")
    response = session.get(f"{BASE_URL}/api/admin/settings")
    
    if response.status_code == 200:
        data = response.json()
        engine = data.get("engine")
        fashn_key_configured = data.get("fashn_key_configured")
        
        log(f"✓ Admin settings retrieved:")
        log(f"  - engine: {engine}")
        log(f"  - fashn_key_configured: {fashn_key_configured}")
        log(f"  - mode: {data.get('mode')}")
        log(f"  - resolution: {data.get('resolution')}")
        
        if engine == "fashn" and fashn_key_configured:
            log("✓ FASHN engine is enabled and configured")
            return True
        else:
            log(f"✗ FASHN engine not properly configured (engine={engine}, fashn_key_configured={fashn_key_configured})")
            return False
    else:
        log(f"✗ Failed to get admin settings: {response.status_code} - {response.text}")
        return False

def get_women_tops_product(session):
    """Get a single women's tops product"""
    log("Step 3: Getting women's tops products...")
    response = session.get(f"{BASE_URL}/api/products?gender=women&limit=20")
    
    if response.status_code == 200:
        products = response.json()
        log(f"✓ Retrieved {len(products)} women's products")
        
        # Find a tops product
        tops_products = [p for p in products if p.get("category") == "tops"]
        
        if tops_products:
            product = tops_products[0]
            log(f"✓ Selected product: {product.get('product_name')} (ID: {product.get('id')}, category: {product.get('category')})")
            return product.get("id")
        else:
            log(f"✗ No tops products found in women's category")
            return None
    else:
        log(f"✗ Failed to get products: {response.status_code} - {response.text}")
        return None

def download_and_encode_photo():
    """Download the Unsplash photo and encode as base64 data URL"""
    log("Step 4: Downloading and encoding test photo...")
    try:
        response = requests.get(UNSPLASH_PHOTO_URL, timeout=10)
        if response.status_code == 200:
            image_bytes = response.content
            base64_encoded = base64.b64encode(image_bytes).decode('utf-8')
            data_url = f"data:image/jpeg;base64,{base64_encoded}"
            log(f"✓ Photo downloaded and encoded (size: {len(image_bytes)} bytes, data URL length: {len(data_url)} chars)")
            return data_url
        else:
            log(f"✗ Failed to download photo: {response.status_code}")
            return None
    except Exception as e:
        log(f"✗ Error downloading photo: {e}")
        return None

def create_multiview_session(session, product_id, photo_data_url):
    """Create a multi-view try-on session"""
    log("Step 5: Creating multi-view try-on session...")
    
    payload = {
        "gender": "women",
        "photos": {
            "front": photo_data_url,
            "left": photo_data_url,
            "right": photo_data_url,
            "rear": photo_data_url
        },
        "product_ids": [product_id]
    }
    
    start_time = time.time()
    response = session.post(f"{BASE_URL}/api/tryon/multiview", json=payload)
    
    if response.status_code == 200:
        data = response.json()
        session_id = data.get("id")
        status = data.get("status")
        log(f"✓ Multi-view session created:")
        log(f"  - session_id: {session_id}")
        log(f"  - status: {status}")
        
        if status == "processing":
            log("✓ Session status is 'processing' as expected")
            return session_id, start_time
        else:
            log(f"✗ Unexpected status: {status}")
            return None, None
    else:
        log(f"✗ Failed to create multi-view session: {response.status_code} - {response.text}")
        return None, None

def poll_session_until_complete(session, session_id, start_time, max_wait=150):
    """Poll the session until it completes or times out"""
    log(f"Step 6: Polling session until complete (max wait: {max_wait}s)...")
    
    poll_count = 0
    while True:
        elapsed = time.time() - start_time
        
        if elapsed > max_wait:
            log(f"✗ Timeout: Session did not complete within {max_wait} seconds")
            return None
        
        poll_count += 1
        log(f"  Poll #{poll_count} (elapsed: {elapsed:.1f}s)...")
        
        response = session.get(f"{BASE_URL}/api/tryon/sessions/{session_id}")
        
        if response.status_code == 200:
            data = response.json()
            status = data.get("status")
            
            if status == "COMPLETED":
                total_time = time.time() - start_time
                log(f"✓ Session COMPLETED in {total_time:.1f} seconds ({poll_count} polls)")
                return data
            elif status == "FAILED":
                log(f"✗ Session FAILED")
                log(f"  Error: {data.get('error', 'No error message')}")
                return None
            elif status == "processing":
                log(f"  Status: {status} (waiting...)")
                time.sleep(3)  # Wait 3 seconds before next poll
            else:
                log(f"  Status: {status}")
                time.sleep(3)
        else:
            log(f"✗ Failed to poll session: {response.status_code} - {response.text}")
            return None

def verify_session_results(session_data):
    """Verify the completed session has all required data"""
    log("Step 7: Verifying session results...")
    
    # Check engine
    engine = session_data.get("engine")
    log(f"  - engine: {engine}")
    if engine == "fashn":
        log("✓ Engine is 'fashn'")
    else:
        log(f"✗ Engine is not 'fashn': {engine}")
        return False
    
    # Check views
    views = session_data.get("views", {})
    required_views = ["front", "left", "right", "rear"]
    
    all_views_ok = True
    view_file_ids = {}
    
    for view_name in required_views:
        view_data = views.get(view_name)
        if view_data:
            file_id = view_data.get("file_id")
            error = view_data.get("error")
            
            if file_id:
                log(f"✓ View '{view_name}' has file_id: {file_id}")
                view_file_ids[view_name] = file_id
            else:
                log(f"✗ View '{view_name}' missing file_id (error: {error})")
                all_views_ok = False
        else:
            log(f"✗ View '{view_name}' not found in results")
            all_views_ok = False
    
    # Check items_used
    items_used = session_data.get("items_used", [])
    log(f"  - items_used count: {len(items_used)}")
    
    if len(items_used) == 1:
        item = items_used[0]
        log(f"✓ Items_used has 1 entry:")
        log(f"  - product_id: {item.get('product_id')}")
        log(f"  - product_url: {item.get('product_url')}")
        log(f"  - url_status: {item.get('url_status')}")
    else:
        log(f"✗ Expected 1 item in items_used, got {len(items_used)}")
        all_views_ok = False
    
    return all_views_ok, view_file_ids

def verify_image_files(session, view_file_ids):
    """Verify each view's image file is a real FASHN render (>50KB)"""
    log("Step 8: Verifying image files...")
    
    all_images_ok = True
    image_sizes = {}
    
    for view_name, file_id in view_file_ids.items():
        response = session.get(f"{BASE_URL}/api/files/{file_id}")
        
        if response.status_code == 200:
            content_type = response.headers.get("content-type", "")
            content_length = len(response.content)
            
            log(f"✓ View '{view_name}' (file_id: {file_id}):")
            log(f"  - content-type: {content_type}")
            log(f"  - size: {content_length} bytes ({content_length / 1024:.1f} KB)")
            
            if content_type.startswith("image/"):
                log(f"  ✓ Content-type is image")
            else:
                log(f"  ✗ Content-type is not image: {content_type}")
                all_images_ok = False
            
            if content_length > 50000:  # >50KB
                log(f"  ✓ Size > 50KB (real FASHN render)")
            else:
                log(f"  ✗ Size <= 50KB (likely mock render, not real FASHN)")
                all_images_ok = False
            
            image_sizes[view_name] = content_length
        else:
            log(f"✗ Failed to get file for view '{view_name}': {response.status_code}")
            all_images_ok = False
    
    return all_images_ok, image_sizes

def main():
    """Main test execution"""
    print("=" * 80)
    print("FASHN Multi-View Try-On Test")
    print("=" * 80)
    
    # Check FASHN credits BEFORE
    credits_before, credits_before_total = check_fashn_credits_before()
    print()
    
    # Create session
    session = requests.Session()
    
    # Step 1: Login
    if not login_admin(session):
        print("\n✗ TEST FAILED: Could not login as admin")
        return
    print()
    
    # Step 2: Check settings
    if not check_admin_settings(session):
        print("\n✗ TEST FAILED: FASHN engine not properly configured")
        return
    print()
    
    # Step 3: Get product
    product_id = get_women_tops_product(session)
    if not product_id:
        print("\n✗ TEST FAILED: Could not find a women's tops product")
        return
    print()
    
    # Step 4: Download photo
    photo_data_url = download_and_encode_photo()
    if not photo_data_url:
        print("\n✗ TEST FAILED: Could not download and encode photo")
        return
    print()
    
    # Step 5: Create multi-view session
    session_id, start_time = create_multiview_session(session, product_id, photo_data_url)
    if not session_id:
        print("\n✗ TEST FAILED: Could not create multi-view session")
        return
    print()
    
    # Step 6: Poll until complete
    session_data = poll_session_until_complete(session, session_id, start_time, max_wait=150)
    if not session_data:
        print("\n✗ TEST FAILED: Session did not complete successfully")
        return
    print()
    
    # Step 7: Verify results
    views_ok, view_file_ids = verify_session_results(session_data)
    if not views_ok:
        print("\n✗ TEST FAILED: Session results verification failed")
        return
    print()
    
    # Step 8: Verify image files
    images_ok, image_sizes = verify_image_files(session, view_file_ids)
    if not images_ok:
        print("\n✗ TEST FAILED: Image file verification failed")
        return
    print()
    
    # Check FASHN credits AFTER
    credits_after, credits_after_total = check_fashn_credits_after()
    print()
    
    # Summary
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"✓ All assertions PASSED")
    print(f"✓ Total wall-clock time: {time.time() - start_time:.1f} seconds")
    print(f"✓ Image sizes:")
    for view_name, size in image_sizes.items():
        print(f"  - {view_name}: {size} bytes ({size / 1024:.1f} KB)")
    print(f"✓ FASHN credits:")
    print(f"  - Before: {credits_before}")
    print(f"  - After: {credits_after}")
    if credits_before_total is not None and credits_after_total is not None:
        used = credits_before_total - credits_after_total
        print(f"  - Used: {used} credits")
    print("=" * 80)

if __name__ == "__main__":
    main()

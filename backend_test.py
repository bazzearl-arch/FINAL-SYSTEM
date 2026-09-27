#!/usr/bin/env python3
"""
Backend API Testing for AI Try-on PH
Tests 5 new backend features:
1. Gender/category filtering
2. Multi-view outfit try-on (mock engine)
3. Admin settings
4. Admin CSV import
5. Admin single-render test endpoint
"""

import requests
import time
import base64
import json
from io import BytesIO
from PIL import Image

# Configuration
BASE_URL = "https://40e5ab34-2b75-43df-9d8d-4810740d8b98.preview.emergentagent.com/api"
ADMIN_EMAIL = "admin@gmail.com"
ADMIN_PASSWORD = "adminpass"

# Test user credentials (will be created if needed)
TEST_USER_EMAIL = f"testuser_{int(time.time())}@example.com"
TEST_USER_PASSWORD = "TestPass123!"
TEST_USER_NAME = "Test User"

# Session to maintain cookies
session = requests.Session()


def create_tiny_image_data_url(color=(255, 0, 0)):
    """Create a tiny 10x10 PNG image as a data URL."""
    img = Image.new('RGB', (10, 10), color=color)
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    img_bytes = buffer.getvalue()
    b64 = base64.b64encode(img_bytes).decode('ascii')
    return f"data:image/png;base64,{b64}"


def print_section(title):
    """Print a section header."""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}\n")


def print_result(test_name, passed, details=""):
    """Print test result."""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} - {test_name}")
    if details:
        print(f"    {details}")


# ============================================================================
# Test 0: Auth API Endpoints (Login, Register, Logout, Me)
# ============================================================================
def test_auth_endpoints():
    print_section("TEST 0: Auth API Endpoints")
    
    results = {
        "admin_login_success": False,
        "admin_login_cookies_set": False,
        "admin_login_user_data": False,
        "wrong_password_401": False,
        "register_success": False,
        "register_cookies_set": False,
        "register_role_user": False,
        "me_with_cookie_success": False,
        "me_without_cookie_401": False,
        "logout_success": False,
        "logout_cookies_cleared": False,
    }
    
    # Test 1: POST /api/auth/login with admin@gmail.com/adminpass
    print("\n--- Test 1: Admin Login ---")
    admin_session = requests.Session()
    try:
        resp = admin_session.post(f"{BASE_URL}/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        print(f"POST /auth/login (admin) -> {resp.status_code}")
        
        if resp.status_code == 200:
            results["admin_login_success"] = True
            print_result("Admin login returns 200", True)
            
            # Check cookies
            cookies = resp.cookies
            if "access_token" in cookies and "refresh_token" in cookies:
                results["admin_login_cookies_set"] = True
                print_result("Admin login sets cookies (access_token, refresh_token)", True)
                print(f"    access_token: {cookies['access_token'][:20]}...")
                print(f"    refresh_token: {cookies['refresh_token'][:20]}...")
            else:
                print_result("Admin login sets cookies", False, f"Cookies: {list(cookies.keys())}")
            
            # Check user data
            user_data = resp.json()
            print(f"    User data: {json.dumps(user_data, indent=2)}")
            if user_data.get("email") == ADMIN_EMAIL and user_data.get("role") == "admin":
                results["admin_login_user_data"] = True
                print_result("Admin login returns correct user data (email, role=admin)", True)
            else:
                print_result("Admin login returns correct user data", False, 
                           f"email={user_data.get('email')}, role={user_data.get('role')}")
        else:
            print_result("Admin login returns 200", False, f"Status {resp.status_code}: {resp.text}")
    except Exception as e:
        print_result("Admin login", False, str(e))
    
    # Test 2: POST /api/auth/login with wrong password
    print("\n--- Test 2: Login with Wrong Password ---")
    try:
        resp = requests.post(f"{BASE_URL}/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": "wrongpassword123"
        })
        print(f"POST /auth/login (wrong password) -> {resp.status_code}")
        
        if resp.status_code in [401, 400]:
            results["wrong_password_401"] = True
            print_result("Wrong password returns 401/400", True, f"Status: {resp.status_code}")
        else:
            print_result("Wrong password returns 401/400", False, f"Got {resp.status_code}")
    except Exception as e:
        print_result("Wrong password returns 401/400", False, str(e))
    
    # Test 3: POST /api/auth/register with fresh email
    print("\n--- Test 3: Register New User ---")
    register_session = requests.Session()
    test_email = f"testuser_{int(time.time())}@example.com"
    test_name = f"Test User {int(time.time())}"
    test_password = "TestPass123!"
    
    try:
        resp = register_session.post(f"{BASE_URL}/auth/register", json={
            "email": test_email,
            "password": test_password,
            "name": test_name
        })
        print(f"POST /auth/register -> {resp.status_code}")
        
        if resp.status_code == 200:
            results["register_success"] = True
            print_result("Register returns 200", True)
            
            # Check cookies
            cookies = resp.cookies
            if "access_token" in cookies and "refresh_token" in cookies:
                results["register_cookies_set"] = True
                print_result("Register sets cookies (access_token, refresh_token)", True)
            else:
                print_result("Register sets cookies", False, f"Cookies: {list(cookies.keys())}")
            
            # Check user data
            user_data = resp.json()
            print(f"    User data: {json.dumps(user_data, indent=2)}")
            if user_data.get("email") == test_email and user_data.get("role") == "user":
                results["register_role_user"] = True
                print_result("Register returns correct user data (email, role=user)", True)
            else:
                print_result("Register returns correct user data", False, 
                           f"email={user_data.get('email')}, role={user_data.get('role')}")
        else:
            print_result("Register returns 200", False, f"Status {resp.status_code}: {resp.text}")
    except Exception as e:
        print_result("Register", False, str(e))
    
    # Test 4: GET /api/auth/me with cookie
    print("\n--- Test 4: GET /auth/me with Cookie ---")
    try:
        resp = admin_session.get(f"{BASE_URL}/auth/me")
        print(f"GET /auth/me (with cookie) -> {resp.status_code}")
        
        if resp.status_code == 200:
            results["me_with_cookie_success"] = True
            user_data = resp.json()
            print_result("GET /auth/me with cookie returns 200", True)
            print(f"    User data: {json.dumps(user_data, indent=2)}")
            if user_data.get("email") == ADMIN_EMAIL:
                print(f"    ✓ Correct user data (email={user_data.get('email')})")
        else:
            print_result("GET /auth/me with cookie returns 200", False, f"Status {resp.status_code}")
    except Exception as e:
        print_result("GET /auth/me with cookie", False, str(e))
    
    # Test 5: GET /api/auth/me without cookie
    print("\n--- Test 5: GET /auth/me without Cookie ---")
    try:
        resp = requests.get(f"{BASE_URL}/auth/me")  # No session, no cookies
        print(f"GET /auth/me (without cookie) -> {resp.status_code}")
        
        if resp.status_code == 401:
            results["me_without_cookie_401"] = True
            print_result("GET /auth/me without cookie returns 401", True)
        else:
            print_result("GET /auth/me without cookie returns 401", False, f"Got {resp.status_code}")
    except Exception as e:
        print_result("GET /auth/me without cookie", False, str(e))
    
    # Test 6: POST /api/auth/logout
    print("\n--- Test 6: Logout ---")
    try:
        resp = admin_session.post(f"{BASE_URL}/auth/logout")
        print(f"POST /auth/logout -> {resp.status_code}")
        
        if resp.status_code == 200:
            results["logout_success"] = True
            print_result("Logout returns 200", True)
            
            # Check if cookies are cleared (should be empty or have max-age=0)
            # After logout, try to access /auth/me - should fail
            resp_me = admin_session.get(f"{BASE_URL}/auth/me")
            print(f"GET /auth/me (after logout) -> {resp_me.status_code}")
            if resp_me.status_code == 401:
                results["logout_cookies_cleared"] = True
                print_result("Logout clears cookies (GET /auth/me returns 401)", True)
            else:
                print_result("Logout clears cookies", False, f"GET /auth/me returned {resp_me.status_code}")
        else:
            print_result("Logout returns 200", False, f"Status {resp.status_code}: {resp.text}")
    except Exception as e:
        print_result("Logout", False, str(e))
    
    return results


# ============================================================================
# Test 1: Gender/Category Filtering
# ============================================================================
def test_gender_category_filtering():
    print_section("TEST 1: Gender/Category Filtering")
    
    results = {
        "men_no_one_pieces": False,
        "women_has_one_pieces": False,
        "categories_men_no_one_pieces": False,
        "categories_women_has_one_pieces": False,
        "category_filter_tops": False,
    }
    
    # Test 1a: GET /api/products?gender=men should NOT have 'one-pieces'
    try:
        resp = session.get(f"{BASE_URL}/products", params={"gender": "men"})
        print(f"GET /products?gender=men -> {resp.status_code}")
        if resp.status_code == 200:
            products = resp.json()
            print(f"  Returned {len(products)} products")
            has_one_pieces = any(p.get("category") == "one-pieces" for p in products)
            if not has_one_pieces:
                results["men_no_one_pieces"] = True
                print_result("Men products have NO 'one-pieces'", True)
            else:
                print_result("Men products have NO 'one-pieces'", False, 
                           f"Found {sum(1 for p in products if p.get('category') == 'one-pieces')} one-pieces items")
        else:
            print_result("GET /products?gender=men", False, f"Status {resp.status_code}")
    except Exception as e:
        print_result("GET /products?gender=men", False, str(e))
    
    # Test 1b: GET /api/products?gender=women should include 'one-pieces'
    try:
        resp = session.get(f"{BASE_URL}/products", params={"gender": "women"})
        print(f"\nGET /products?gender=women -> {resp.status_code}")
        if resp.status_code == 200:
            products = resp.json()
            print(f"  Returned {len(products)} products")
            has_one_pieces = any(p.get("category") == "one-pieces" for p in products)
            if has_one_pieces:
                results["women_has_one_pieces"] = True
                count = sum(1 for p in products if p.get("category") == "one-pieces")
                print_result("Women products include 'one-pieces'", True, f"Found {count} one-pieces items")
            else:
                print_result("Women products include 'one-pieces'", False, "No one-pieces found")
        else:
            print_result("GET /products?gender=women", False, f"Status {resp.status_code}")
    except Exception as e:
        print_result("GET /products?gender=women", False, str(e))
    
    # Test 1c: GET /api/categories?gender=men should NOT have 'one-pieces'
    try:
        resp = session.get(f"{BASE_URL}/categories", params={"gender": "men"})
        print(f"\nGET /categories?gender=men -> {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            categories = data.get("categories", [])
            print(f"  Categories: {categories}")
            if "one-pieces" not in categories:
                results["categories_men_no_one_pieces"] = True
                print_result("Men categories have NO 'one-pieces'", True)
            else:
                print_result("Men categories have NO 'one-pieces'", False, "'one-pieces' found in list")
        else:
            print_result("GET /categories?gender=men", False, f"Status {resp.status_code}")
    except Exception as e:
        print_result("GET /categories?gender=men", False, str(e))
    
    # Test 1d: GET /api/categories?gender=women should include 'one-pieces'
    try:
        resp = session.get(f"{BASE_URL}/categories", params={"gender": "women"})
        print(f"\nGET /categories?gender=women -> {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            categories = data.get("categories", [])
            print(f"  Categories: {categories}")
            if "one-pieces" in categories:
                results["categories_women_has_one_pieces"] = True
                print_result("Women categories include 'one-pieces'", True)
            else:
                print_result("Women categories include 'one-pieces'", False, "'one-pieces' not in list")
        else:
            print_result("GET /categories?gender=women", False, f"Status {resp.status_code}")
    except Exception as e:
        print_result("GET /categories?gender=women", False, str(e))
    
    # Test 1e: GET /api/products?category=tops should only return 'tops'
    try:
        resp = session.get(f"{BASE_URL}/products", params={"category": "tops"})
        print(f"\nGET /products?category=tops -> {resp.status_code}")
        if resp.status_code == 200:
            products = resp.json()
            print(f"  Returned {len(products)} products")
            all_tops = all(p.get("category") == "tops" for p in products)
            if all_tops and len(products) > 0:
                results["category_filter_tops"] = True
                print_result("Category filter 'tops' works correctly", True, f"All {len(products)} products are 'tops'")
            elif len(products) == 0:
                print_result("Category filter 'tops' works correctly", False, "No products returned")
            else:
                wrong = [p.get("category") for p in products if p.get("category") != "tops"]
                print_result("Category filter 'tops' works correctly", False, f"Found non-tops: {set(wrong)}")
        else:
            print_result("GET /products?category=tops", False, f"Status {resp.status_code}")
    except Exception as e:
        print_result("GET /products?category=tops", False, str(e))
    
    return results


# ============================================================================
# Test 2: Multi-view Outfit Try-on (Mock Engine)
# ============================================================================
def test_multiview_tryon():
    print_section("TEST 2: Multi-view Outfit Try-on (Mock Engine)")
    
    results = {
        "login_success": False,
        "get_products": False,
        "multiview_post_success": False,
        "multiview_missing_front_400": False,
        "multiview_empty_products_400": False,
        "session_completed": False,
        "views_have_file_ids": False,
        "items_used_correct": False,
        "file_download_success": False,
    }
    
    # Login as admin
    try:
        resp = session.post(f"{BASE_URL}/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        print(f"POST /auth/login -> {resp.status_code}")
        if resp.status_code == 200:
            results["login_success"] = True
            user_data = resp.json()
            print_result("Admin login", True, f"Logged in as {user_data.get('email')}")
        else:
            print_result("Admin login", False, f"Status {resp.status_code}: {resp.text}")
            return results
    except Exception as e:
        print_result("Admin login", False, str(e))
        return results
    
    # Get 2-3 product IDs
    product_ids = []
    try:
        resp = session.get(f"{BASE_URL}/products", params={"limit": 10})
        print(f"\nGET /products -> {resp.status_code}")
        if resp.status_code == 200:
            products = resp.json()
            product_ids = [p["id"] for p in products[:3]]
            results["get_products"] = True
            print_result("Get products", True, f"Got {len(product_ids)} product IDs: {product_ids}")
        else:
            print_result("Get products", False, f"Status {resp.status_code}")
            return results
    except Exception as e:
        print_result("Get products", False, str(e))
        return results
    
    # Test 2a: POST /api/tryon/multiview with valid data
    try:
        photos = {
            "front": create_tiny_image_data_url((255, 0, 0)),
            "left": create_tiny_image_data_url((0, 255, 0)),
            "right": create_tiny_image_data_url((0, 0, 255)),
            "rear": create_tiny_image_data_url((255, 255, 0)),
        }
        payload = {
            "gender": "women",
            "photos": photos,
            "product_ids": product_ids
        }
        resp = session.post(f"{BASE_URL}/tryon/multiview", json=payload)
        print(f"\nPOST /tryon/multiview -> {resp.status_code}")
        if resp.status_code == 200:
            session_data = resp.json()
            session_id = session_data.get("id")
            status = session_data.get("status")
            print(f"  Session ID: {session_id}")
            print(f"  Status: {status}")
            if status == "processing" and session_id:
                results["multiview_post_success"] = True
                print_result("Multiview try-on POST", True, f"Session {session_id} created with status 'processing'")
                
                # Poll the session until completion
                max_attempts = 20
                for attempt in range(max_attempts):
                    time.sleep(1)
                    poll_resp = session.get(f"{BASE_URL}/tryon/sessions/{session_id}")
                    if poll_resp.status_code == 200:
                        poll_data = poll_resp.json()
                        poll_status = poll_data.get("status")
                        print(f"  Poll attempt {attempt+1}: status = {poll_status}")
                        
                        if poll_status != "processing":
                            if poll_status == "COMPLETED":
                                results["session_completed"] = True
                                print_result("Session completed", True, f"Status: {poll_status}")
                                
                                # Check views
                                views = poll_data.get("views", {})
                                print(f"  Views: {list(views.keys())}")
                                
                                all_have_file_ids = True
                                for view_key in ["front", "left", "right", "rear"]:
                                    view_data = views.get(view_key, {})
                                    file_id = view_data.get("file_id")
                                    print(f"    {view_key}: file_id={file_id}")
                                    if not file_id:
                                        all_have_file_ids = False
                                
                                if all_have_file_ids:
                                    results["views_have_file_ids"] = True
                                    print_result("All views have file_ids", True)
                                else:
                                    print_result("All views have file_ids", False, "Some views missing file_id")
                                
                                # Check items_used
                                items_used = poll_data.get("items_used", [])
                                print(f"  Items used: {len(items_used)} items")
                                if len(items_used) == len(product_ids):
                                    results["items_used_correct"] = True
                                    print_result("Items used matches selected products", True)
                                    for item in items_used:
                                        print(f"    - {item.get('name')}: product_url={item.get('product_url')}, url_status={item.get('url_status')}, rendered={item.get('rendered')}")
                                else:
                                    print_result("Items used matches selected products", False, 
                                               f"Expected {len(product_ids)}, got {len(items_used)}")
                                
                                # Test file download
                                front_view = views.get("front", {})
                                front_file_id = front_view.get("file_id")
                                if front_file_id:
                                    try:
                                        file_resp = session.get(f"{BASE_URL}/files/{front_file_id}")
                                        print(f"\n  GET /files/{front_file_id} -> {file_resp.status_code}")
                                        if file_resp.status_code == 200:
                                            content_type = file_resp.headers.get("content-type", "")
                                            print(f"    Content-Type: {content_type}")
                                            if "image" in content_type:
                                                results["file_download_success"] = True
                                                print_result("File download", True, f"Got image ({len(file_resp.content)} bytes)")
                                            else:
                                                print_result("File download", False, f"Not an image: {content_type}")
                                        else:
                                            print_result("File download", False, f"Status {file_resp.status_code}")
                                    except Exception as e:
                                        print_result("File download", False, str(e))
                            else:
                                print_result("Session completed", False, f"Status: {poll_status}, Error: {poll_data.get('error')}")
                            break
                    else:
                        print(f"  Poll failed: {poll_resp.status_code}")
                        break
                else:
                    print_result("Session completed", False, "Timeout after 20 seconds")
            else:
                print_result("Multiview try-on POST", False, f"Unexpected status: {status}")
        else:
            print_result("Multiview try-on POST", False, f"Status {resp.status_code}: {resp.text}")
    except Exception as e:
        print_result("Multiview try-on POST", False, str(e))
    
    # Test 2b: Missing front photo should return 400
    try:
        payload = {
            "gender": "women",
            "photos": {
                "left": create_tiny_image_data_url(),
                "right": create_tiny_image_data_url(),
            },
            "product_ids": product_ids
        }
        resp = session.post(f"{BASE_URL}/tryon/multiview", json=payload)
        print(f"\nPOST /tryon/multiview (no front photo) -> {resp.status_code}")
        if resp.status_code == 400:
            results["multiview_missing_front_400"] = True
            print_result("Missing front photo returns 400", True)
        else:
            print_result("Missing front photo returns 400", False, f"Got {resp.status_code}")
    except Exception as e:
        print_result("Missing front photo returns 400", False, str(e))
    
    # Test 2c: Empty product_ids should return 400
    try:
        payload = {
            "gender": "women",
            "photos": {
                "front": create_tiny_image_data_url(),
            },
            "product_ids": []
        }
        resp = session.post(f"{BASE_URL}/tryon/multiview", json=payload)
        print(f"\nPOST /tryon/multiview (empty product_ids) -> {resp.status_code}")
        if resp.status_code == 400:
            results["multiview_empty_products_400"] = True
            print_result("Empty product_ids returns 400", True)
        else:
            print_result("Empty product_ids returns 400", False, f"Got {resp.status_code}")
    except Exception as e:
        print_result("Empty product_ids returns 400", False, str(e))
    
    return results


# ============================================================================
# Test 3: Admin Settings
# ============================================================================
def test_admin_settings():
    print_section("TEST 3: Admin Settings")
    
    results = {
        "admin_get_settings": False,
        "engine_is_mock": False,
        "fashn_key_configured_false": False,
        "admin_put_settings": False,
        "non_admin_403": False,
    }
    
    # Ensure admin is logged in
    try:
        resp = session.post(f"{BASE_URL}/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if resp.status_code != 200:
            print_result("Admin login", False, f"Status {resp.status_code}")
            return results
    except Exception as e:
        print_result("Admin login", False, str(e))
        return results
    
    # Test 3a: GET /api/admin/settings (admin)
    try:
        resp = session.get(f"{BASE_URL}/admin/settings")
        print(f"GET /admin/settings -> {resp.status_code}")
        if resp.status_code == 200:
            settings = resp.json()
            print(f"  Settings: {json.dumps(settings, indent=2)}")
            results["admin_get_settings"] = True
            print_result("GET admin settings", True)
            
            # Check engine is 'mock'
            if settings.get("engine") == "mock":
                results["engine_is_mock"] = True
                print_result("Engine is 'mock'", True)
            else:
                print_result("Engine is 'mock'", False, f"Engine: {settings.get('engine')}")
            
            # Check fashn_key_configured is false
            if settings.get("fashn_key_configured") == False:
                results["fashn_key_configured_false"] = True
                print_result("fashn_key_configured is False", True)
            else:
                print_result("fashn_key_configured is False", False, 
                           f"fashn_key_configured: {settings.get('fashn_key_configured')}")
        else:
            print_result("GET admin settings", False, f"Status {resp.status_code}: {resp.text}")
    except Exception as e:
        print_result("GET admin settings", False, str(e))
    
    # Test 3b: PUT /api/admin/settings (admin)
    try:
        payload = {"mode": "quality"}
        resp = session.put(f"{BASE_URL}/admin/settings", json=payload)
        print(f"\nPUT /admin/settings (mode=quality) -> {resp.status_code}")
        if resp.status_code == 200:
            settings = resp.json()
            if settings.get("mode") == "quality":
                results["admin_put_settings"] = True
                print_result("PUT admin settings persists", True, f"Mode: {settings.get('mode')}")
            else:
                print_result("PUT admin settings persists", False, f"Mode: {settings.get('mode')}")
        else:
            print_result("PUT admin settings persists", False, f"Status {resp.status_code}: {resp.text}")
    except Exception as e:
        print_result("PUT admin settings persists", False, str(e))
    
    # Test 3c: Non-admin should get 403
    # Create a normal user
    normal_session = requests.Session()
    try:
        # Register normal user
        resp = normal_session.post(f"{BASE_URL}/auth/register", json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD,
            "name": TEST_USER_NAME
        })
        if resp.status_code == 200:
            print(f"\nCreated normal user: {TEST_USER_EMAIL}")
            
            # Try to access admin settings
            resp = normal_session.get(f"{BASE_URL}/admin/settings")
            print(f"GET /admin/settings (non-admin) -> {resp.status_code}")
            if resp.status_code == 403:
                results["non_admin_403"] = True
                print_result("Non-admin gets 403", True)
            else:
                print_result("Non-admin gets 403", False, f"Got {resp.status_code}")
        else:
            print(f"Failed to create normal user: {resp.status_code}")
    except Exception as e:
        print_result("Non-admin gets 403", False, str(e))
    
    return results


# ============================================================================
# Test 4: Admin CSV Import
# ============================================================================
def test_admin_csv_import():
    print_section("TEST 4: Admin CSV Import")
    
    results = {
        "csv_import_success": False,
        "saved_count_correct": False,
        "errors_count_zero": False,
        "test_tee_exists": False,
        "test_tee_url_status_ok": False,
        "no_url_item_exists": False,
        "no_url_item_status_missing": False,
    }
    
    # Ensure admin is logged in
    try:
        resp = session.post(f"{BASE_URL}/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if resp.status_code != 200:
            print_result("Admin login", False, f"Status {resp.status_code}")
            return results
    except Exception as e:
        print_result("Admin login", False, str(e))
        return results
    
    # Test 4a: POST /api/admin/import/csv
    csv_payload = """product_name,gender,category,price,image_url,product_url,platform
Test Tee,men,tops,499,https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?w=400,https://shopee.ph/test-tee-i.1.2,Shopee
No URL Item,women,bottoms,299,https://images.unsplash.com/photo-1541099649105-f69ad21f3246?w=400,,Lazada"""
    
    try:
        payload = {"payload": csv_payload}
        resp = session.post(f"{BASE_URL}/admin/import/csv", json=payload)
        print(f"POST /admin/import/csv -> {resp.status_code}")
        if resp.status_code == 200:
            result = resp.json()
            print(f"  Result: {json.dumps(result, indent=2)}")
            results["csv_import_success"] = True
            print_result("CSV import POST", True)
            
            saved = result.get("saved", 0)
            errors = result.get("errors", 0)
            
            if saved == 2:
                results["saved_count_correct"] = True
                print_result("Saved count is 2", True)
            else:
                print_result("Saved count is 2", False, f"Saved: {saved}")
            
            if errors == 0:
                results["errors_count_zero"] = True
                print_result("Errors count is 0", True)
            else:
                print_result("Errors count is 0", False, f"Errors: {errors}")
        else:
            print_result("CSV import POST", False, f"Status {resp.status_code}: {resp.text}")
            return results
    except Exception as e:
        print_result("CSV import POST", False, str(e))
        return results
    
    # Test 4b: Verify products exist in GET /api/admin/products
    try:
        resp = session.get(f"{BASE_URL}/admin/products")
        print(f"\nGET /admin/products -> {resp.status_code}")
        if resp.status_code == 200:
            products = resp.json()
            print(f"  Total products: {len(products)}")
            
            # Find "Test Tee"
            test_tee = next((p for p in products if p.get("name") == "Test Tee"), None)
            if test_tee:
                results["test_tee_exists"] = True
                print_result("'Test Tee' exists", True)
                print(f"    product_url: {test_tee.get('product_url')}")
                print(f"    url_status: {test_tee.get('url_status')}")
                
                if test_tee.get("product_url") and test_tee.get("url_status") == "ok":
                    results["test_tee_url_status_ok"] = True
                    print_result("'Test Tee' has product_url and url_status='ok'", True)
                else:
                    print_result("'Test Tee' has product_url and url_status='ok'", False)
            else:
                print_result("'Test Tee' exists", False, "Not found in products")
            
            # Find "No URL Item"
            no_url_item = next((p for p in products if p.get("name") == "No URL Item"), None)
            if no_url_item:
                results["no_url_item_exists"] = True
                print_result("'No URL Item' exists", True)
                print(f"    product_url: {no_url_item.get('product_url')}")
                print(f"    url_status: {no_url_item.get('url_status')}")
                
                if no_url_item.get("url_status") == "missing":
                    results["no_url_item_status_missing"] = True
                    print_result("'No URL Item' has url_status='missing'", True)
                else:
                    print_result("'No URL Item' has url_status='missing'", False, 
                               f"url_status: {no_url_item.get('url_status')}")
            else:
                print_result("'No URL Item' exists", False, "Not found in products")
        else:
            print_result("GET /admin/products", False, f"Status {resp.status_code}")
    except Exception as e:
        print_result("GET /admin/products", False, str(e))
    
    return results


# ============================================================================
# Test 5: Admin Single-Render Test Endpoint
# ============================================================================
def test_admin_test_render():
    print_section("TEST 5: Admin Single-Render Test Endpoint")
    
    results = {
        "test_render_success": False,
        "ok_true": False,
        "engine_mock": False,
        "credits_estimate_zero": False,
        "image_data_url": False,
        "invalid_product_id_error": False,
    }
    
    # Ensure admin is logged in
    try:
        resp = session.post(f"{BASE_URL}/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if resp.status_code != 200:
            print_result("Admin login", False, f"Status {resp.status_code}")
            return results
    except Exception as e:
        print_result("Admin login", False, str(e))
        return results
    
    # Get a valid product ID
    product_id = None
    try:
        resp = session.get(f"{BASE_URL}/products", params={"limit": 1})
        if resp.status_code == 200:
            products = resp.json()
            if products:
                product_id = products[0]["id"]
                print(f"Using product ID: {product_id}")
        if not product_id:
            print_result("Get product ID", False, "No products available")
            return results
    except Exception as e:
        print_result("Get product ID", False, str(e))
        return results
    
    # Test 5a: POST /api/admin/tryon/test with valid data
    try:
        payload = {
            "photo_base64": create_tiny_image_data_url(),
            "product_id": product_id
        }
        resp = session.post(f"{BASE_URL}/admin/tryon/test", json=payload)
        print(f"POST /admin/tryon/test -> {resp.status_code}")
        if resp.status_code == 200:
            result = resp.json()
            print(f"  Result keys: {list(result.keys())}")
            results["test_render_success"] = True
            print_result("Test render POST", True)
            
            if result.get("ok") == True:
                results["ok_true"] = True
                print_result("ok is True", True)
            else:
                print_result("ok is True", False, f"ok: {result.get('ok')}")
            
            if result.get("engine") == "mock":
                results["engine_mock"] = True
                print_result("engine is 'mock'", True)
            else:
                print_result("engine is 'mock'", False, f"engine: {result.get('engine')}")
            
            if result.get("credits_estimate") == 0:
                results["credits_estimate_zero"] = True
                print_result("credits_estimate is 0", True)
            else:
                print_result("credits_estimate is 0", False, f"credits_estimate: {result.get('credits_estimate')}")
            
            image = result.get("image", "")
            if image.startswith("data:image"):
                results["image_data_url"] = True
                print_result("image is data URL", True, f"Length: {len(image)} chars")
            else:
                print_result("image is data URL", False, f"Image: {image[:50]}...")
        else:
            print_result("Test render POST", False, f"Status {resp.status_code}: {resp.text}")
    except Exception as e:
        print_result("Test render POST", False, str(e))
    
    # Test 5b: Invalid product_id should return 400 or 404
    try:
        payload = {
            "photo_base64": create_tiny_image_data_url(),
            "product_id": "invalid_id_12345"
        }
        resp = session.post(f"{BASE_URL}/admin/tryon/test", json=payload)
        print(f"\nPOST /admin/tryon/test (invalid product_id) -> {resp.status_code}")
        if resp.status_code in [400, 404]:
            results["invalid_product_id_error"] = True
            print_result("Invalid product_id returns 400/404", True, f"Status: {resp.status_code}")
        else:
            print_result("Invalid product_id returns 400/404", False, f"Got {resp.status_code}")
    except Exception as e:
        print_result("Invalid product_id returns 400/404", False, str(e))
    
    return results


# ============================================================================
# Main Test Runner
# ============================================================================
def main():
    print("\n" + "="*80)
    print("  AI Try-on PH Backend Testing - AUTH ENDPOINTS ONLY")
    print("  Base URL:", BASE_URL)
    print("="*80)
    
    all_results = {}
    
    # Run ONLY auth test (as requested in review)
    all_results["test0_auth"] = test_auth_endpoints()
    
    # Uncomment below to run all tests
    # all_results["test1"] = test_gender_category_filtering()
    # all_results["test2"] = test_multiview_tryon()
    # all_results["test3"] = test_admin_settings()
    # all_results["test4"] = test_admin_csv_import()
    # all_results["test5"] = test_admin_test_render()
    
    # Summary
    print_section("SUMMARY")
    
    total_tests = 0
    passed_tests = 0
    
    for test_name, results in all_results.items():
        for check_name, passed in results.items():
            total_tests += 1
            if passed:
                passed_tests += 1
    
    print(f"Total Tests: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {total_tests - passed_tests}")
    print(f"Success Rate: {passed_tests/total_tests*100:.1f}%")
    
    # Detailed results
    print("\nDetailed Results:")
    for test_name, results in all_results.items():
        print(f"\n{test_name}:")
        for check_name, passed in results.items():
            status = "✅" if passed else "❌"
            print(f"  {status} {check_name}")
    
    return all_results


if __name__ == "__main__":
    main()

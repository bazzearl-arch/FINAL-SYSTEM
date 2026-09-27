#!/usr/bin/env python3
"""
Backend test for mandatory Two-Factor Authentication (TOTP) auth flow.
Tests all auth scenarios including setup, enable, verify, and security checks.
"""

import requests
import pyotp
import time
import random
import string

# Base URL from frontend/.env (HTTPS for Secure cookies)
BASE_URL = "https://95da7c6a-e319-4706-b84a-0ec58998c152.preview.emergentagent.com/api"

# Admin credentials (2FA has been reset, so it will be in SETUP mode)
ADMIN_EMAIL = "admin@gmail.com"
ADMIN_PASSWORD = "adminpass"

# Test results tracking
test_results = []

def log_test(scenario, passed, details=""):
    """Log test result"""
    status = "✅ PASS" if passed else "❌ FAIL"
    test_results.append({
        "scenario": scenario,
        "passed": passed,
        "details": details
    })
    print(f"{status}: {scenario}")
    if details:
        print(f"  Details: {details}")

def generate_random_email():
    """Generate a random email for testing"""
    random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f"test_{random_str}@example.com"

def test_scenario_1_wrong_password():
    """Test 1: POST /api/auth/login with wrong password -> expect 401"""
    print("\n=== Test 1: Login with wrong password ===")
    try:
        response = requests.post(
            f"{BASE_URL}/auth/login",
            json={"email": ADMIN_EMAIL, "password": "wrongpassword"},
            timeout=10
        )
        
        if response.status_code == 401:
            log_test("Scenario 1: Wrong password returns 401", True)
            return True
        else:
            log_test("Scenario 1: Wrong password returns 401", False, 
                    f"Expected 401, got {response.status_code}")
            return False
    except Exception as e:
        log_test("Scenario 1: Wrong password returns 401", False, str(e))
        return False

def test_scenario_2_login_setup_mode():
    """Test 2: POST /api/auth/login with correct creds -> {requires_2fa_setup: true, mfa_token, email}
    Assert NO auth cookies are set at this step and NO full user object with role is returned."""
    print("\n=== Test 2: Login with correct password (setup mode) ===")
    try:
        response = requests.post(
            f"{BASE_URL}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            timeout=10
        )
        
        if response.status_code != 200:
            log_test("Scenario 2: Login returns 200 with requires_2fa_setup", False,
                    f"Expected 200, got {response.status_code}: {response.text}")
            return None
        
        data = response.json()
        
        # Check response structure
        checks = []
        checks.append(("requires_2fa_setup is True", data.get("requires_2fa_setup") == True))
        checks.append(("mfa_token present", "mfa_token" in data and data["mfa_token"]))
        checks.append(("email present", data.get("email") == ADMIN_EMAIL))
        checks.append(("NO role in response", "role" not in data))
        checks.append(("NO id in response", "id" not in data))
        
        # Check NO auth cookies are set
        cookies = response.cookies
        checks.append(("NO access_token cookie", "access_token" not in cookies))
        checks.append(("NO refresh_token cookie", "refresh_token" not in cookies))
        
        all_passed = all(check[1] for check in checks)
        failed_checks = [check[0] for check in checks if not check[1]]
        
        if all_passed:
            log_test("Scenario 2: Login returns requires_2fa_setup with mfa_token, no cookies", True)
            return data["mfa_token"]
        else:
            log_test("Scenario 2: Login returns requires_2fa_setup with mfa_token, no cookies", False,
                    f"Failed checks: {', '.join(failed_checks)}")
            return None
    except Exception as e:
        log_test("Scenario 2: Login returns requires_2fa_setup with mfa_token, no cookies", False, str(e))
        return None

def test_scenario_3_setup_endpoint(mfa_token):
    """Test 3: POST /api/auth/2fa/setup {mfa_token} -> {secret, otpauth_uri, qr, issuer, account}
    Assert qr starts with "data:image/png"."""
    print("\n=== Test 3: 2FA Setup endpoint ===")
    try:
        response = requests.post(
            f"{BASE_URL}/auth/2fa/setup",
            json={"mfa_token": mfa_token},
            timeout=10
        )
        
        if response.status_code != 200:
            log_test("Scenario 3: 2FA setup returns secret and QR", False,
                    f"Expected 200, got {response.status_code}: {response.text}")
            return None
        
        data = response.json()
        
        # Check response structure
        checks = []
        checks.append(("secret present", "secret" in data and data["secret"]))
        checks.append(("otpauth_uri present", "otpauth_uri" in data and data["otpauth_uri"]))
        checks.append(("qr present", "qr" in data and data["qr"]))
        checks.append(("qr starts with data:image/png", data.get("qr", "").startswith("data:image/png;base64,")))
        checks.append(("issuer present", data.get("issuer") == "AI Try-on PH"))
        checks.append(("account present", data.get("account") == ADMIN_EMAIL))
        
        all_passed = all(check[1] for check in checks)
        failed_checks = [check[0] for check in checks if not check[1]]
        
        if all_passed:
            log_test("Scenario 3: 2FA setup returns secret and QR", True)
            return data["secret"]
        else:
            log_test("Scenario 3: 2FA setup returns secret and QR", False,
                    f"Failed checks: {', '.join(failed_checks)}")
            return None
    except Exception as e:
        log_test("Scenario 3: 2FA setup returns secret and QR", False, str(e))
        return None

def test_scenario_4_enable_with_code(mfa_token, secret):
    """Test 4: Compute code = pyotp.TOTP(secret).now(). POST /api/auth/2fa/enable {mfa_token, code}
    -> expect 200, sets access_token/refresh_token cookies, returns the user object.
    Assert the returned user has email=admin@gmail.com and role=admin and does NOT contain
    "password_hash" or "totp_secret"."""
    print("\n=== Test 4: Enable 2FA with TOTP code ===")
    try:
        # Compute TOTP code
        totp = pyotp.TOTP(secret)
        code = totp.now()
        print(f"  Generated TOTP code: {code}")
        
        # Create a session to track cookies
        session = requests.Session()
        response = session.post(
            f"{BASE_URL}/auth/2fa/enable",
            json={"mfa_token": mfa_token, "code": code},
            timeout=10
        )
        
        if response.status_code != 200:
            log_test("Scenario 4: Enable 2FA returns session and user object", False,
                    f"Expected 200, got {response.status_code}: {response.text}")
            return None
        
        data = response.json()
        
        # Check response structure
        checks = []
        checks.append(("email is admin@gmail.com", data.get("email") == ADMIN_EMAIL))
        checks.append(("role is admin", data.get("role") == "admin"))
        checks.append(("NO password_hash in response", "password_hash" not in data))
        checks.append(("NO totp_secret in response", "totp_secret" not in data))
        checks.append(("id present", "id" in data))
        
        # Check cookies are set
        cookies = session.cookies
        checks.append(("access_token cookie set", "access_token" in cookies))
        checks.append(("refresh_token cookie set", "refresh_token" in cookies))
        
        all_passed = all(check[1] for check in checks)
        failed_checks = [check[0] for check in checks if not check[1]]
        
        if all_passed:
            log_test("Scenario 4: Enable 2FA returns session and user object", True)
            return session
        else:
            log_test("Scenario 4: Enable 2FA returns session and user object", False,
                    f"Failed checks: {', '.join(failed_checks)}")
            return None
    except Exception as e:
        log_test("Scenario 4: Enable 2FA returns session and user object", False, str(e))
        return None

def test_scenario_5_auth_me(session):
    """Test 5: With the issued cookies, GET /api/auth/me -> expect 200 returning admin user."""
    print("\n=== Test 5: GET /auth/me with cookies ===")
    try:
        response = session.get(f"{BASE_URL}/auth/me", timeout=10)
        
        if response.status_code != 200:
            log_test("Scenario 5: GET /auth/me returns 200 with user", False,
                    f"Expected 200, got {response.status_code}: {response.text}")
            return False
        
        data = response.json()
        
        # Check response structure
        checks = []
        checks.append(("email is admin@gmail.com", data.get("email") == ADMIN_EMAIL))
        checks.append(("role is admin", data.get("role") == "admin"))
        checks.append(("NO password_hash in response", "password_hash" not in data))
        checks.append(("NO totp_secret in response", "totp_secret" not in data))
        
        all_passed = all(check[1] for check in checks)
        failed_checks = [check[0] for check in checks if not check[1]]
        
        if all_passed:
            log_test("Scenario 5: GET /auth/me returns 200 with user", True)
            return True
        else:
            log_test("Scenario 5: GET /auth/me returns 200 with user", False,
                    f"Failed checks: {', '.join(failed_checks)}")
            return False
    except Exception as e:
        log_test("Scenario 5: GET /auth/me returns 200 with user", False, str(e))
        return False

def test_scenario_6_wrong_code():
    """Test 6: POST /api/auth/2fa/enable again with a wrong/short code using a fresh mfa_token -> expect 401."""
    print("\n=== Test 6: Enable 2FA with wrong code ===")
    try:
        # First, get a fresh mfa_token by logging in again
        response = requests.post(
            f"{BASE_URL}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            timeout=10
        )
        
        if response.status_code != 200:
            log_test("Scenario 6: Wrong code returns 401", False,
                    f"Failed to get mfa_token: {response.status_code}")
            return False
        
        data = response.json()
        # Now admin should be in verify mode (already enrolled)
        if not data.get("requires_2fa"):
            log_test("Scenario 6: Wrong code returns 401", False,
                    "Expected requires_2fa=true after admin enrollment")
            return False
        
        mfa_token = data["mfa_token"]
        
        # Try with wrong code
        response = requests.post(
            f"{BASE_URL}/auth/2fa/verify",  # Use verify endpoint for enrolled users
            json={"mfa_token": mfa_token, "code": "000000"},
            timeout=10
        )
        
        if response.status_code == 401:
            log_test("Scenario 6: Wrong code returns 401", True)
            return True
        else:
            log_test("Scenario 6: Wrong code returns 401", False,
                    f"Expected 401, got {response.status_code}")
            return False
    except Exception as e:
        log_test("Scenario 6: Wrong code returns 401", False, str(e))
        return False

def test_scenario_7_register_fresh_user():
    """Test 7: Register a fresh user: POST /api/auth/register {email: unique, name, password}
    -> expect 200 with {requires_2fa_setup: true, mfa_token}.
    Then complete setup -> enable with pyotp code -> expect session issued and GET /api/auth/me
    returns that user with role=user."""
    print("\n=== Test 7: Register fresh user and complete 2FA setup ===")
    try:
        # Generate unique email
        email = generate_random_email()
        name = "Test User"
        password = "testpass123"
        
        # Register
        response = requests.post(
            f"{BASE_URL}/auth/register",
            json={"email": email, "name": name, "password": password},
            timeout=10
        )
        
        if response.status_code != 200:
            log_test("Scenario 7: Register and complete 2FA setup", False,
                    f"Register failed: {response.status_code}: {response.text}")
            return None
        
        data = response.json()
        
        if not data.get("requires_2fa_setup") or not data.get("mfa_token"):
            log_test("Scenario 7: Register and complete 2FA setup", False,
                    "Register didn't return requires_2fa_setup and mfa_token")
            return None
        
        mfa_token = data["mfa_token"]
        
        # Setup 2FA
        response = requests.post(
            f"{BASE_URL}/auth/2fa/setup",
            json={"mfa_token": mfa_token},
            timeout=10
        )
        
        if response.status_code != 200:
            log_test("Scenario 7: Register and complete 2FA setup", False,
                    f"2FA setup failed: {response.status_code}")
            return None
        
        secret = response.json()["secret"]
        
        # Enable 2FA with code
        totp = pyotp.TOTP(secret)
        code = totp.now()
        
        session = requests.Session()
        response = session.post(
            f"{BASE_URL}/auth/2fa/enable",
            json={"mfa_token": mfa_token, "code": code},
            timeout=10
        )
        
        if response.status_code != 200:
            log_test("Scenario 7: Register and complete 2FA setup", False,
                    f"Enable 2FA failed: {response.status_code}: {response.text}")
            return None
        
        user_data = response.json()
        
        # Verify session with /auth/me
        response = session.get(f"{BASE_URL}/auth/me", timeout=10)
        
        if response.status_code != 200:
            log_test("Scenario 7: Register and complete 2FA setup", False,
                    f"GET /auth/me failed: {response.status_code}")
            return None
        
        me_data = response.json()
        
        # Check user data
        checks = []
        checks.append(("email matches", me_data.get("email") == email))
        checks.append(("role is user", me_data.get("role") == "user"))
        checks.append(("NO password_hash", "password_hash" not in me_data))
        checks.append(("NO totp_secret", "totp_secret" not in me_data))
        
        all_passed = all(check[1] for check in checks)
        failed_checks = [check[0] for check in checks if not check[1]]
        
        if all_passed:
            log_test("Scenario 7: Register and complete 2FA setup", True)
            return {"email": email, "password": password, "secret": secret}
        else:
            log_test("Scenario 7: Register and complete 2FA setup", False,
                    f"Failed checks: {', '.join(failed_checks)}")
            return None
    except Exception as e:
        log_test("Scenario 7: Register and complete 2FA setup", False, str(e))
        return None

def test_scenario_8_relogin_enrolled_user(user_info):
    """Test 8: Re-login the fresh user (now enrolled): POST /api/auth/login
    -> expect {requires_2fa: true, mfa_token} (verify mode, NOT setup).
    Then POST /api/auth/2fa/verify {mfa_token, code} with pyotp code -> expect 200 + session."""
    print("\n=== Test 8: Re-login enrolled user (verify mode) ===")
    try:
        if not user_info:
            log_test("Scenario 8: Re-login enrolled user", False, "No user info from scenario 7")
            return False
        
        email = user_info["email"]
        password = user_info["password"]
        secret = user_info["secret"]
        
        # Login
        response = requests.post(
            f"{BASE_URL}/auth/login",
            json={"email": email, "password": password},
            timeout=10
        )
        
        if response.status_code != 200:
            log_test("Scenario 8: Re-login enrolled user", False,
                    f"Login failed: {response.status_code}: {response.text}")
            return False
        
        data = response.json()
        
        # Check for verify mode (NOT setup)
        checks = []
        checks.append(("requires_2fa is True", data.get("requires_2fa") == True))
        checks.append(("NOT requires_2fa_setup", "requires_2fa_setup" not in data or not data.get("requires_2fa_setup")))
        checks.append(("mfa_token present", "mfa_token" in data))
        
        if not all(check[1] for check in checks):
            failed_checks = [check[0] for check in checks if not check[1]]
            log_test("Scenario 8: Re-login enrolled user", False,
                    f"Login response incorrect: {', '.join(failed_checks)}")
            return False
        
        mfa_token = data["mfa_token"]
        
        # Verify with TOTP code
        totp = pyotp.TOTP(secret)
        code = totp.now()
        
        session = requests.Session()
        response = session.post(
            f"{BASE_URL}/auth/2fa/verify",
            json={"mfa_token": mfa_token, "code": code},
            timeout=10
        )
        
        if response.status_code != 200:
            log_test("Scenario 8: Re-login enrolled user", False,
                    f"Verify failed: {response.status_code}: {response.text}")
            return False
        
        user_data = response.json()
        
        # Check session is issued
        checks = []
        checks.append(("email matches", user_data.get("email") == email))
        checks.append(("access_token cookie", "access_token" in session.cookies))
        checks.append(("refresh_token cookie", "refresh_token" in session.cookies))
        
        all_passed = all(check[1] for check in checks)
        failed_checks = [check[0] for check in checks if not check[1]]
        
        if all_passed:
            log_test("Scenario 8: Re-login enrolled user", True)
            return True
        else:
            log_test("Scenario 8: Re-login enrolled user", False,
                    f"Failed checks: {', '.join(failed_checks)}")
            return False
    except Exception as e:
        log_test("Scenario 8: Re-login enrolled user", False, str(e))
        return False

def test_scenario_9_mfa_token_security():
    """Test 9: Security: take an mfa_token and try to use it as a Bearer access token on a
    protected route (GET /api/auth/me with Authorization: Bearer <mfa_token>) -> expect 401
    (mfa tokens must not be accepted as access tokens)."""
    print("\n=== Test 9: Security - mfa_token should not work as access token ===")
    try:
        # Get an mfa_token
        response = requests.post(
            f"{BASE_URL}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            timeout=10
        )
        
        if response.status_code != 200:
            log_test("Scenario 9: mfa_token rejected as access token", False,
                    f"Failed to get mfa_token: {response.status_code}")
            return False
        
        mfa_token = response.json().get("mfa_token")
        
        if not mfa_token:
            log_test("Scenario 9: mfa_token rejected as access token", False,
                    "No mfa_token in login response")
            return False
        
        # Try to use mfa_token as Bearer token on protected route
        response = requests.get(
            f"{BASE_URL}/auth/me",
            headers={"Authorization": f"Bearer {mfa_token}"},
            timeout=10
        )
        
        if response.status_code == 401:
            log_test("Scenario 9: mfa_token rejected as access token", True)
            return True
        else:
            log_test("Scenario 9: mfa_token rejected as access token", False,
                    f"Expected 401, got {response.status_code} (mfa_token was accepted as access token!)")
            return False
    except Exception as e:
        log_test("Scenario 9: mfa_token rejected as access token", False, str(e))
        return False

def test_scenario_10_logout(session):
    """Test 10: POST /api/auth/logout with cookies -> 200, then GET /api/auth/me -> 401."""
    print("\n=== Test 10: Logout clears session ===")
    try:
        # Logout
        response = session.post(f"{BASE_URL}/auth/logout", timeout=10)
        
        if response.status_code != 200:
            log_test("Scenario 10: Logout clears session", False,
                    f"Logout failed: {response.status_code}")
            return False
        
        # Try to access /auth/me after logout
        response = session.get(f"{BASE_URL}/auth/me", timeout=10)
        
        if response.status_code == 401:
            log_test("Scenario 10: Logout clears session", True)
            return True
        else:
            log_test("Scenario 10: Logout clears session", False,
                    f"Expected 401 after logout, got {response.status_code}")
            return False
    except Exception as e:
        log_test("Scenario 10: Logout clears session", False, str(e))
        return False

def main():
    """Run all test scenarios"""
    print("=" * 80)
    print("MANDATORY 2FA (TOTP) AUTH FLOW TESTING")
    print("=" * 80)
    print(f"Base URL: {BASE_URL}")
    print(f"Admin: {ADMIN_EMAIL}")
    print("=" * 80)
    
    # Test 1: Wrong password
    test_scenario_1_wrong_password()
    
    # Test 2: Login with correct password (setup mode)
    mfa_token = test_scenario_2_login_setup_mode()
    
    if not mfa_token:
        print("\n❌ Cannot continue without mfa_token from scenario 2")
        print_summary()
        return
    
    # Test 3: 2FA Setup
    secret = test_scenario_3_setup_endpoint(mfa_token)
    
    if not secret:
        print("\n❌ Cannot continue without secret from scenario 3")
        print_summary()
        return
    
    # Test 4: Enable 2FA with code
    session = test_scenario_4_enable_with_code(mfa_token, secret)
    
    if not session:
        print("\n❌ Cannot continue without session from scenario 4")
        print_summary()
        return
    
    # Test 5: GET /auth/me with cookies
    test_scenario_5_auth_me(session)
    
    # Test 6: Wrong code returns 401
    test_scenario_6_wrong_code()
    
    # Test 7: Register fresh user and complete setup
    user_info = test_scenario_7_register_fresh_user()
    
    # Test 8: Re-login enrolled user (verify mode)
    test_scenario_8_relogin_enrolled_user(user_info)
    
    # Test 9: Security - mfa_token should not work as access token
    test_scenario_9_mfa_token_security()
    
    # Test 10: Logout
    test_scenario_10_logout(session)
    
    # Print summary
    print_summary()

def print_summary():
    """Print test summary"""
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    passed = sum(1 for r in test_results if r["passed"])
    total = len(test_results)
    
    for result in test_results:
        status = "✅" if result["passed"] else "❌"
        print(f"{status} {result['scenario']}")
        if result["details"] and not result["passed"]:
            print(f"   {result['details']}")
    
    print("=" * 80)
    print(f"TOTAL: {passed}/{total} tests passed ({passed*100//total if total > 0 else 0}%)")
    print("=" * 80)
    
    if passed == total:
        print("✅ ALL TESTS PASSED")
    else:
        print(f"❌ {total - passed} TEST(S) FAILED")

if __name__ == "__main__":
    main()

import requests
import sys
from datetime import datetime
import json

class OAuthAPITester:
    def __init__(self, base_url="https://social-login-qr.preview.emergentagent.com"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
        self.session = requests.Session()
        self.tests_run = 0
        self.tests_passed = 0

    def run_test(self, name, method, endpoint, expected_status, data=None, check_content_type=None):
        """Run a single API test"""
        if endpoint.startswith('/api'):
            url = f"{self.base_url}{endpoint}"
        elif endpoint.startswith('/'):
            url = f"{self.base_url}{endpoint}"
        else:
            url = f"{self.api_url}/{endpoint}"
            
        headers = {'Content-Type': 'application/json'}

        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        
        try:
            if method == 'GET':
                response = self.session.get(url, headers=headers)
            elif method == 'POST':
                response = self.session.post(url, json=data, headers=headers)

            success = response.status_code == expected_status
            
            if success:
                self.tests_passed += 1
                print(f"✅ Passed - Status: {response.status_code}")
                
                # Check content type if specified
                if check_content_type:
                    content_type = response.headers.get('content-type', '')
                    if check_content_type in content_type:
                        print(f"✅ Content-Type: {content_type}")
                    else:
                        print(f"⚠️  Expected content-type: {check_content_type}, got: {content_type}")
                
                # Try to parse JSON response if possible
                try:
                    if 'application/json' in response.headers.get('content-type', ''):
                        json_response = response.json()
                        print(f"   Response: {json.dumps(json_response, indent=2)[:200]}...")
                        return success, json_response
                    else:
                        print(f"   Response size: {len(response.content)} bytes")
                        return success, response.content
                except:
                    return success, response.text[:200] if hasattr(response, 'text') else str(response.content)[:200]
            else:
                print(f"❌ Failed - Expected {expected_status}, got {response.status_code}")
                try:
                    error_response = response.json() if 'json' in response.headers.get('content-type', '') else response.text
                    print(f"   Error: {error_response}")
                except:
                    print(f"   Error: {response.text[:200]}")
                return False, {}

        except Exception as e:
            print(f"❌ Failed - Error: {str(e)}")
            return False, {}

    def test_api_root(self):
        """Test API root endpoint"""
        success, response = self.run_test(
            "API Root",
            "GET",
            "/api/",
            200
        )
        return success

    def test_qr_code_generation(self):
        """Test QR code generation endpoint"""
        success, response = self.run_test(
            "QR Code Generation",
            "GET",
            "/qr",
            200,
            check_content_type="image/png"
        )
        return success

    def test_google_oauth_initiation(self):
        """Test Google OAuth initiation (should redirect)"""
        success, response = self.run_test(
            "Google OAuth Initiation",
            "GET",
            "/auth/google",
            302  # Expecting redirect to Google
        )
        return success

    def test_user_me_unauthenticated(self):
        """Test getting current user when not authenticated"""
        success, response = self.run_test(
            "Get Current User (Unauthenticated)",
            "GET",
            "/user/me",
            401  # Should be unauthorized
        )
        return success

    def test_phone_update_unauthenticated(self):
        """Test updating phone when not authenticated"""
        success, response = self.run_test(
            "Update Phone (Unauthenticated)",
            "POST",
            "/user/phone",
            401,  # Should be unauthorized
            data={"phone": "+1234567890", "consent_given": True}
        )
        return success

    def test_logout_unauthenticated(self):
        """Test logout when not authenticated"""
        success, response = self.run_test(
            "Logout (Unauthenticated)",
            "POST",
            "/auth/logout",
            200  # Should still return success
        )
        return success

    def test_status_endpoints(self):
        """Test status check endpoints"""
        # Test creating a status check
        test_data = {"client_name": f"test_client_{datetime.now().strftime('%H%M%S')}"}
        success1, response1 = self.run_test(
            "Create Status Check",
            "POST",
            "/status",
            200,
            data=test_data
        )
        
        # Test getting status checks
        success2, response2 = self.run_test(
            "Get Status Checks",
            "GET",
            "/status",
            200
        )
        
        return success1 and success2

    def test_get_all_users(self):
        """Test getting all users endpoint"""
        success, response = self.run_test(
            "Get All Users",
            "GET",
            "/users",
            200
        )
        return success

def main():
    print("🚀 Starting OAuth Social Login API Tests")
    print("=" * 50)
    
    # Setup
    tester = OAuthAPITester()
    
    # Run all tests
    tests = [
        ("API Root", tester.test_api_root),
        ("QR Code Generation", tester.test_qr_code_generation),
        ("Google OAuth Initiation", tester.test_google_oauth_initiation),
        ("User Me (Unauthenticated)", tester.test_user_me_unauthenticated),
        ("Phone Update (Unauthenticated)", tester.test_phone_update_unauthenticated),
        ("Logout (Unauthenticated)", tester.test_logout_unauthenticated),
        ("Status Endpoints", tester.test_status_endpoints),
        ("Get All Users", tester.test_get_all_users),
    ]
    
    print(f"\n📋 Running {len(tests)} test categories...")
    
    for test_name, test_func in tests:
        try:
            test_func()
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {str(e)}")

    # Print final results
    print("\n" + "=" * 50)
    print(f"📊 Final Results: {tester.tests_passed}/{tester.tests_run} tests passed")
    
    if tester.tests_passed == tester.tests_run:
        print("🎉 All tests passed!")
        return 0
    else:
        print(f"⚠️  {tester.tests_run - tester.tests_passed} tests failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
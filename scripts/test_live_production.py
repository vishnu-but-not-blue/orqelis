import sys

import httpx

sys.stdout.reconfigure(encoding='utf-8')

base_url = "https://orqelis.pro"
print(f"Testing live production deployment at {base_url}...")

with httpx.Client(follow_redirects=True, timeout=20.0) as client:
    # 1. Test homepage
    r = client.get(f"{base_url}/")
    print(f"1. GET / -> {r.status_code} ({len(r.text)} bytes)")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    assert "Orqelis" in r.text or "contracts" in r.text
    print("   [PASS] Homepage rendered successfully.")
    
    # 2. Test static assets
    r_js = client.get(f"{base_url}/static/app.js")
    print(f"2. GET /static/app.js -> {r_js.status_code} ({len(r_js.text)} bytes)")
    assert r_js.status_code == 200
    print("   [PASS] Static assets served successfully.")
    
    # 3. Test API diagnostic/health or company endpoint
    r_api = client.get(f"{base_url}/api/v1/company")
    print(f"3. GET /api/v1/company -> {r_api.status_code} (Expected 401 without auth)")
    assert r_api.status_code == 401, f"Expected 401 Unauthorized, got {r_api.status_code}"
    print("   [PASS] API endpoint protected by authentication.")
    
    # 4. Check Cloudflare & Security headers
    print("4. Response headers:")
    for h in ['server', 'cf-ray', 'content-security-policy', 'strict-transport-security', 'x-content-type-options']:
        val = r.headers.get(h)
        if val:
            print(f"   {h}: {val}")
    assert 'cloudflare' in r.headers.get('server', '').lower() or 'cf-ray' in r.headers
    print("   [PASS] Verified Cloudflare edge acceleration & SSL active.")

print("\nALL PRODUCTION SMOKE TESTS PASSED! ORQELIS.PRO IS FULLY OPERATIONAL!")

"""Live smoke test with a temporary Supabase identity; never sends email or prints tokens."""
import json
import secrets
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import create_engine, text

from app.config import Settings
from app.schemas import Profile


def main():
    config = Settings()
    base = "https://orqelis.srivishnupriyan24.workers.dev"
    marker = secrets.token_hex(16)
    email = f"cf-smoke-{marker}@example.test"
    password = secrets.token_urlsafe(32)
    uid, oid = secrets.token_hex(16), secrets.token_hex(16)
    provider_id = None
    engine = create_engine(config.database_url)
    admin_headers = {"apikey": config.supabase_service_role_key,
                     "Authorization": "Bearer " + config.supabase_service_role_key}
    report = {"base_url": base, "emails_sent": False}
    client = httpx.Client(base_url=base, timeout=45)
    try:
        response = httpx.post(config.supabase_url + "/auth/v1/admin/users", headers=admin_headers,
                             json={"email": email, "password": password, "email_confirm": True}, timeout=20)
        assert response.status_code in (200, 201), "Temporary identity creation failed"
        provider_id = response.json()["id"]
        with engine.begin() as db:
            db.execute(text("INSERT INTO users(id,email,name,auth_subject,created_at) VALUES(:id,:email,'Deployment test',:subject,now())"),
                       {"id": uid, "email": email, "subject": "supabase:" + provider_id})
            db.execute(text("INSERT INTO organizations(id,name,capability_version,profile,plan) VALUES(:id,'Deployment test workspace',1,CAST(:profile AS json),'FREE')"),
                       {"id": oid, "profile": json.dumps(Profile().model_dump())})
            db.execute(text("INSERT INTO memberships(id,organization_id,user_id,role) VALUES(:id,:org,:user,'OWNER')"),
                       {"id": secrets.token_hex(16), "org": oid, "user": uid})
        response = httpx.post(config.supabase_url + "/auth/v1/token?grant_type=password",
                             headers={"apikey": config.supabase_anon_key},
                             json={"email": email, "password": password}, timeout=20)
        assert response.status_code == 200, "Supabase token exchange failed"
        access = response.json()["access_token"]
        response = client.post("/api/v1/auth/verify", json={"token": access})
        assert response.status_code == 200, f"Live sign-in failed: {response.status_code}"
        client.headers["X-CSRF-Token"] = response.json()["csrf"]
        report["supabase_verified_sign_in"] = "PASS"
        response = client.post("/api/v1/evidence", json={"capability": "ISO 27001", "state": "UNVERIFIED"})
        assert response.status_code == 200, f"Manual evidence failed: {response.status_code}"
        assert client.post("/api/v1/documents", json={}).status_code == 503
        report["manual_evidence_and_upload_block"] = "PASS"
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1050})
            context.add_cookies([{"name": "session", "value": client.cookies.get("session"),
                                  "url": base, "httpOnly": True, "secure": True, "sameSite": "Strict"}])
            page = context.new_page()
            page.set_default_timeout(30000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/dashboard")
            expect(page.locator("#workspace-name")).to_have_text("Deployment test workspace")
            assert not page.get_by_text("We couldn’t open this view").count()
            screenshots = Path("var/screenshots")
            screenshots.mkdir(exist_ok=True)
            page.screenshot(path=str(screenshots / "cloudflare-dashboard.png"), full_page=True)
            page.goto(base + "/evidence")
            expect(page.locator("#upload-form")).to_contain_text("temporarily paused")
            expect(page.locator("#main")).to_contain_text("ISO 27001")
            assert page.locator('input[type="file"]').count() == 0
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(screenshots / "cloudflare-evidence-mobile.png"), full_page=True)
            assert not errors, "Browser JavaScript error detected"
            browser.close()
        report["desktop_mobile_browser"] = "PASS"
        response = client.get("/api/v1/opportunities?limit=1")
        assert response.status_code == 200
        items = response.json()["items"]
        if items:
            response = client.post(f"/api/v1/opportunities/{items[0]['id']}/analysis")
            assert response.status_code == 200, f"Live assessment failed: {response.status_code}"
            assert response.json()["result"]["eligibility"] != "PASS"
            report["live_assessment"] = "PASS"
        response = client.get("/api/v1/account/export")
        assert response.status_code == 200
        report["data_export"] = "PASS"
        response = client.delete("/api/v1/account")
        assert response.status_code == 200
        report["account_deletion"] = "PASS"
    finally:
        with engine.begin() as db:
            db.execute(text("DELETE FROM organizations WHERE id=:id AND name='Deployment test workspace'"), {"id": oid})
            db.execute(text("DELETE FROM users WHERE id=:id AND email=:email"), {"id": uid, "email": email})
        if provider_id:
            response = httpx.delete(config.supabase_url + "/auth/v1/admin/users/" + provider_id,
                                    headers=admin_headers, timeout=20)
            assert response.status_code in (200, 204, 404), "Temporary identity cleanup failed"
        engine.dispose()
        client.close()
        report["temporary_data_cleanup"] = "PASS"
        Path("var/cloudflare-live-smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

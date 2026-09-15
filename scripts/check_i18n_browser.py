"""Eight-language browser regression against an isolated local database; sends no email."""

import json
import os
import secrets
import threading
import time
from pathlib import Path


def main():
    root = Path("var") / ("i18n-browser-" + secrets.token_hex(5))
    root.mkdir(parents=True)
    os.environ.update(
        ENVIRONMENT="test",
        DATABASE_URL=f"sqlite:///{root / 'test.db'}",
        AUTH_PROVIDER="local",
        STORAGE_PROVIDER="local",
        STORAGE_PATH=str(root / "objects"),
        BASE_URL="http://127.0.0.1:8019",
        TED_ENABLED="false",
        WORKER_ENABLED="false",
    )
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from app.db import SessionLocal, initialize_database
    from app.ingest import ingest
    from app.main import app, rate_windows
    from scripts.seed_demo import demo_notices

    initialize_database()
    original = "Company profile — <script>window.sourceInjected=true</script> {0}"
    with SessionLocal() as db:
        for i, row in enumerate(demo_notices()):
            if i == 0:
                row["title"] = original
            notice, _ = ingest(db, row, json.dumps(row), source="DEMO")
            if i == 0:
                notice_id = notice.id
        db.commit()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8019, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    assert server.started
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            page.set_default_timeout(10000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            base = "http://127.0.0.1:8019"
            page.goto(base + "/login")
            expect(page.locator("#language option")).to_have_count(8)
            page.select_option("#language", "de")
            expect(page.locator("html")).to_have_attribute("lang", "de")
            page.locator("#name").fill("Language Tester")
            page.locator("#email").fill("language@example.test")
            page.locator("#login-form button").click()
            page.locator("#verify-form button").click()
            page.wait_for_url("**/onboarding")
            expect(page.locator("#language")).to_have_value("de")
            page.locator("#name").fill("Original company name")
            page.locator("#country").fill("DEU")
            page.locator("#onboard-form button[type=submit]").click()
            page.locator("#services").fill("Original services — not translated")
            page.locator("#onboard-form button[type=submit]").click()
            page.locator("#operating_countries").fill("DEU, FRA")
            page.locator("#languages").fill("ENG, DEU")
            page.locator("#onboard-form button[type=submit]").click()
            page.locator("#onboard-form button[type=submit]").click()
            page.locator("#onboard-form button[type=submit]").click()
            page.wait_for_url("**/opportunities")

            counts = {}
            missing = []
            for language in ["en", "de", "fr", "es", "it", "nl", "pl", "pt"]:
                # Independent browser cases share this isolated test process; retain the
                # production limiter and reset only the fixture's accumulated requests.
                rate_windows.clear()
                page.select_option("#language", language)
                expect(page.locator("html")).to_have_attribute("lang", language)
                catalog = json.loads(
                    Path(f"app/static/locales/{language}.json").read_text(encoding="utf8")
                )
                for route in [
                    "dashboard",
                    "company",
                    "opportunities",
                    "watchlist",
                    "evidence",
                    "notifications",
                    "settings",
                ]:
                    page.goto(base + "/" + route)
                    expect(page.locator(".page-header")).to_be_visible()
                    expect(page.locator("#language")).to_have_value(language)
                    assert page.evaluate('localStorage.getItem("orqelis.language")') == language
                    expect(page.locator("[data-nav=opportunities]")).to_contain_text(
                        catalog["Opportunities"]
                    )
                    if route == "company":
                        expect(page.locator("#services")).to_have_value(
                            "Original services — not translated"
                        )
                    if route == "dashboard":
                        assert (
                            page.locator(".check-row").nth(2).get_attribute("href") == "/evidence"
                        )
                    if route == "settings":
                        assert page.locator("#role option").evaluate_all(
                            "(els)=>els.map(e=>e.value)"
                        ) == ["MEMBER", "ADMIN", "VIEWER"]
                    if route == "evidence":
                        page.locator("#add-evidence").click()
                        expect(page.locator("#state option").nth(1)).to_have_attribute(
                            "value", "USER_CONFIRMED"
                        )
                        page.locator("#close-modal").click()
                    missing.extend((language, route, key) for key in page.evaluate("I18N.missing"))
                page.goto(base + "/opportunities/" + notice_id)
                expect(page.locator(".detail-title")).to_have_text(original)
                assert not page.evaluate("Boolean(window.sourceInjected)")
                page.locator("#analyze").click()
                expect(page.locator(".decision-banner")).to_be_visible()
                page.locator("#dismiss").click()
                assert (
                    page.locator("#reason option").first.get_attribute("value")
                    == "Irrelevant scope"
                )
                page.locator("#close-modal").click()
                missing.extend(
                    (language, "assessment", key) for key in page.evaluate("I18N.missing")
                )
                page.set_viewport_size({"width": 390, "height": 844})
                page.goto(base + "/dashboard")
                expect(page.locator(".page-header")).to_be_visible()
                expect(page.locator("#language")).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), language
                page.screenshot(path=str(root / f"{language}-mobile.png"), full_page=True)
                page.set_viewport_size({"width": 1440, "height": 1000})
                counts[language] = "8 views, forms, original content, persistence, mobile passed"
            old_cookie = next(c["value"] for c in context.cookies() if c["name"] == "session")
            page.locator("#logout").click()
            page.wait_for_url("**/login")
            assert not any(c["name"] == "session" for c in context.cookies())
            assert (
                context.request.get(
                    base + "/api/v1/auth/me", headers={"Cookie": "session=" + old_cookie}
                ).status
                == 401
            )
            expect(page.locator("#language")).to_have_value("pt")
            assert not errors, errors
            assert not missing, missing
            browser.close()
            print(
                json.dumps(
                    {
                        "languages": counts,
                        "logout_invalidation": "passed",
                        "browser_errors": errors,
                        "artifacts": str(root),
                    }
                )
            )
    finally:
        server.should_exit = True
        thread.join(timeout=10)


if __name__ == "__main__":
    main()

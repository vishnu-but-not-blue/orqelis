"""Browser privacy/SEO regression. Isolated DB, fake Google tag; no external requests."""

import json
import os
import secrets
import threading
import time
from pathlib import Path


def main():
    root = Path("var") / ("seo-browser-" + secrets.token_hex(4))
    root.mkdir(parents=True)
    os.environ.update(ENVIRONMENT="test", DATABASE_URL=f"sqlite:///{root / 'test.db'}",
                      AUTH_PROVIDER="local", STORAGE_PROVIDER="local", TED_ENABLED="false",
                      WORKER_ENABLED="false", BASE_URL="http://127.0.0.1:8021")
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    from app.main import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8021, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(.1)
    assert server.started
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            google = []

            def route_request(route):
                url = route.request.url
                if url.startswith("https://orqelis.pro/"):
                    response = context.request.fetch(
                        "http://127.0.0.1:8021/" + url.split("orqelis.pro/", 1)[1],
                        method=route.request.method, data=route.request.post_data,
                        headers=route.request.headers,
                    )
                    route.fulfill(response=response)
                elif "googletagmanager.com" in url:
                    google.append(url)
                    route.fulfill(status=200, content_type="application/javascript", body="")
                else:
                    route.abort()

            context.route("**/*", route_request)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto("https://orqelis.pro/?email=private@example.test#OTP-secret")
            expect(page.locator("h1")).to_have_count(1)
            assert not google
            page.locator("[data-analytics-deny]").click()
            page.reload()
            assert not google
            page.locator("[data-analytics-settings]").click()
            page.locator("[data-analytics-allow]").click()
            page.wait_for_function("window.dataLayer && window.dataLayer.length >= 4")
            page.wait_for_timeout(100)
            assert len(google) == 1
            page.evaluate("OrqelisAnalytics.event('auth_start', {email:'private@example.test'})")
            page.evaluate("OrqelisAnalytics.event('arbitrary_private_event')")
            data = page.evaluate("dataLayer.map(x=>Array.from(x))")
            encoded = json.dumps(data, default=str)
            assert "private@example.test" not in encoded and "OTP-secret" not in encoded
            assert "arbitrary_private_event" not in encoded
            assert sum(x[0] == "config" for x in data) == 1
            assert data[2][2]["send_page_view"] is False
            page.goto("https://orqelis.pro/login?token=private-auth-token")
            page.wait_for_function("window.OrqelisAnalytics")
            page.evaluate("OrqelisAnalytics.event('login')")
            data = page.evaluate("dataLayer.map(x=>Array.from(x))")
            assert not any(x[:2] == ["event", "page_view"] for x in data)
            encoded = json.dumps(data, default=str)
            assert "private-auth-token" not in encoded
            assert 'https://orqelis.pro/app' in encoded
            page.locator('.analytics-settings').click()
            page.locator('[data-analytics-deny]').click()
            page.wait_for_timeout(300)
            before = len(google)
            page.reload()
            assert len(google) == before
            for language in ['en', 'de', 'fr', 'es', 'it', 'nl', 'pl', 'pt']:
                path = '/' if language == 'en' else '/' + language + '/'
                page.goto('https://orqelis.pro' + path)
                expect(page.locator('html')).to_have_attribute('lang', language)
                expect(page.locator('head link[hreflang]')).to_have_count(9)
                assert page.evaluate("localStorage.getItem('orqelis.language')") == language
                for width in [1440, 390]:
                    page.set_viewport_size({'width': width, 'height': 900})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors, errors
            page.screenshot(path=str(root / 'public-mobile.png'))
            browser.close()
            print('PASS: consent, withdrawal, payload privacy, private routes, eight languages, mobile, JS errors')
    finally:
        server.should_exit = True
        thread.join(timeout=10)


if __name__ == '__main__':
    main()

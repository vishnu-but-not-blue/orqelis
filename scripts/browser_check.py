"""Real browser journey against a running local server. Uses an isolated test account."""

import json
import secrets
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from app.jobs import run_once

Path("var/screenshots").mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 1050})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8000/login")
    page.get_by_label("Your name").fill("Alex Morgan")
    page.get_by_label("Work email").fill(f"browser-{secrets.token_hex(5)}@example.test")
    page.get_by_role("button", name="Continue with email").click()
    page.get_by_role("button", name="Open your workspace").click()
    page.wait_for_url("**/onboarding")
    page.get_by_label("Company name").fill("Northstar Digital")
    page.get_by_label("Home country code").fill("DEU")
    page.get_by_role("button", name="Continue").click()
    page.get_by_label("Your services").fill("Cloud infrastructure and cybersecurity services")
    page.get_by_label("CPV interests").fill("72000000")
    page.get_by_role("button", name="Continue").click()
    page.get_by_label("Operating countries").fill("DEU, NLD, IRL")
    page.get_by_label("Working languages").fill("ENG, DEU")
    page.get_by_role("button", name="Continue").click()
    page.get_by_label("Bid-team hours available per day").fill("8")
    page.get_by_role("button", name="Continue").click()
    page.get_by_role("button", name="Explore opportunities").click()
    page.wait_for_url("**/opportunities")
    expect(page.locator(".opportunity-card").first).to_be_visible()
    page.goto("http://127.0.0.1:8000/dashboard")
    expect(page.get_by_role("heading", name="A clearer view, Alex.")).to_be_visible()
    page.screenshot(path="var/screenshots/dashboard-desktop.png", full_page=True)
    page.goto("http://127.0.0.1:8000/evidence")
    page.get_by_label("Upload a document").set_input_files(
        {
            "name": "certificate.txt",
            "mimeType": "text/plain",
            "buffer": b"ISO 27001 certificate. Valid until 2028-12-31. Turnover EUR 800000.",
        }
    )
    page.get_by_role("button", name="Upload securely").click()
    expect(page.get_by_text("Quarantined", exact=True)).to_be_visible()
    for _ in range(5):
        if not run_once():
            break
    page.get_by_role("button", name="Refresh document status").click()
    expect(page.get_by_text("Ready", exact=True)).to_be_visible()
    page.get_by_role("button", name="Add evidence").click()
    page.get_by_label("Capability", exact=True).fill("ISO 27001")
    page.get_by_label("Source document", exact=True).select_option(label="certificate.txt")
    page.get_by_label("Valid until", exact=True).fill("2028-12-31")
    page.get_by_label("Page or section").fill("Section 1")
    page.get_by_label("Exact source excerpt").fill("ISO 27001 certificate.")
    page.get_by_label("Verification state").select_option("USER_CONFIRMED")
    page.get_by_role("button", name="Save evidence").click()
    expect(page.get_by_text("User Confirmed", exact=True)).to_be_visible()
    page.goto("http://127.0.0.1:8000/opportunities")
    page.locator(".opportunity-card").filter(has_text="Managed cloud").click()
    page.get_by_role("button", name="Assess this opportunity").click()
    expect(page.get_by_role("heading", name="Requirement & evidence matrix")).to_be_visible()
    page.get_by_role("button", name="Watch changes").click()
    with page.expect_download() as download:
        page.get_by_role("button", name="Export report").click()
    assert download.value.suggested_filename == "decision-report.json"
    page.screenshot(path="var/screenshots/opportunity-desktop.png", full_page=True)
    page.goto("http://127.0.0.1:8000/settings")
    expect(page.get_by_role("heading", name="Your workspace, your control.")).to_be_visible()
    with page.expect_download():
        page.get_by_role("button", name="Download account archive").click()
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("http://127.0.0.1:8000/dashboard")
    expect(page.get_by_role("heading", name="A clearer view, Alex.")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path="var/screenshots/dashboard-mobile.png", full_page=True)
    assert not errors, errors
    browser.close()
print(
    json.dumps(
        {
            "browser": "chromium",
            "journey": "passed",
            "console_errors": errors,
            "screenshots": "var/screenshots",
        }
    )
)

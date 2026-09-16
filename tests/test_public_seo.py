import json
import re
from xml.etree import ElementTree

import pytest

from app.public import CONTENT, GUIDES, LANGUAGES, ORIGIN, indexable_paths, language_path


@pytest.mark.parametrize("language", LANGUAGES)
def test_public_language_is_rendered_without_javascript(client, language):
    path = language_path(language)
    response = client.get(path)
    assert response.status_code == 200
    assert f'<html lang="{language}">' in response.text
    assert CONTENT[language]["heading"] in response.text
    assert f'href="{ORIGIN}{path}"' in response.text
    assert "noindex" not in response.headers.get("x-robots-tag", "")
    assert response.text.count('rel="alternate"') == 9
    assert len(re.findall(r"<h1>", response.text)) == 1
    schema = json.loads(re.search(r'application/ld\+json"[^>]*>(.*?)</script>',
                                  response.text, re.S)[1])
    assert schema["@graph"][-1]["inLanguage"] == language
    nonce = re.search(r'nonce="([^"]+)"', response.text)[1]
    assert f"'nonce-{nonce}'" in response.headers["content-security-policy"]
    assert "unsafe-inline" not in response.headers["content-security-policy"]


def test_sitemap_has_only_indexable_canonical_pages(client):
    response = client.get("/sitemap.xml")
    root = ElementTree.fromstring(response.content)
    urls = [node.text for node in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert set(urls) == {ORIGIN + path for path in indexable_paths()}
    assert len(urls) == len(set(urls)) == 12
    for url in urls:
        result = client.get(url.removeprefix(ORIGIN))
        assert result.status_code == 200
        assert "noindex" not in result.headers.get("x-robots-tag", "")
    assert client.head("/sitemap.xml").status_code == 200
    assert "Sitemap: https://orqelis.pro/sitemap.xml" in client.get("/robots.txt").text


@pytest.mark.parametrize("path", ["/login", "/login?token=sensitive", "/dashboard",
                                  "/opportunities/private-id", "/evidence", "/settings",
                                  "/onboarding", "/api/v1/auth/me", "/api/v1/documents",
                                  "/legal/privacy", "/liveness", "/readiness"])
def test_private_and_auth_routes_cannot_be_indexed(client, path):
    response = client.get(path)
    assert "noindex" in response.headers["x-robots-tag"]
    if path.startswith("/api/"):
        assert response.status_code == 401


def test_canonical_redirects_and_safe_404(client):
    response = client.get("https://www.orqelis.pro/de/", follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"] == ORIGIN + "/de/"
    assert client.get("/de", follow_redirects=False).headers["location"] == "/de/"
    assert client.get("/en/", follow_redirects=False).headers["location"] == "/"
    assert "noindex" in client.get("/?email=private").headers["x-robots-tag"]
    assert "noindex" in client.get("https://orqelis.onrender.com/").headers["x-robots-tag"]
    response = client.get("/missing-secret-name", headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert "missing-secret-name" not in response.text
    assert 'href="/"' in response.text
    assert client.get("/api/v1/missing").status_code == 404


def test_english_guides_do_not_claim_nonexistent_translations(client):
    for slug in GUIDES:
        response = client.get("/guides/" + slug)
        assert response.status_code == 200
        assert 'rel="alternate"' not in response.text
        assert GUIDES[slug]["heading"] in response.text


def test_anonymous_content_is_identical_with_session_cookie(client):
    client.cookies.set("session", "not-a-real-session")
    assert client.get("/").status_code == 200
    assert CONTENT["en"]["heading"] in client.get("/").text

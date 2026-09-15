import json
import re
from pathlib import Path

import pytest

LOCALES = Path("app/static/locales")
LANGUAGES = ("en", "de", "fr", "es", "it", "nl", "pl", "pt")


@pytest.mark.parametrize("language", LANGUAGES)
def test_catalog_complete_and_interpolations_preserved(language):
    english = json.loads((LOCALES / "en.json").read_text(encoding="utf8"))
    catalog = json.loads((LOCALES / f"{language}.json").read_text(encoding="utf8"))
    assert catalog.keys() == english.keys()
    for key, value in catalog.items():
        assert isinstance(value, str) and value.strip(), key
        assert sorted(re.findall(r"\{\d+\}", key)) == sorted(re.findall(r"\{\d+\}", value)), key
        assert not re.search(r"<\s*/?\s*[a-zA-Z]+[\s>]", value), key


def test_explicit_ui_messages_have_catalog_entries():
    english = json.loads((LOCALES / "en.json").read_text(encoding="utf8"))
    for filename in ["app.js", "review.js", "i18n.js"]:
        source = Path("app/static", filename).read_text(encoding="utf8")
        for _, key in re.findall(r'\b(?:t|htmlMessage)\(([\'"])(.*?)\1', source):
            assert key in english, (filename, key)


def test_language_assets_served_with_existing_security_headers(client):
    response = client.get("/login")
    assert 'id="language"' in response.text
    assert re.search(r"/static/[a-f0-9]{16}/i18n.js", response.text)
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "unsafe-eval" not in response.headers["content-security-policy"]
    versioned = re.search(r"/static/[a-f0-9]{16}", response.text).group()
    for filename in ["app.js", "review.js", "i18n.js", "i18n.css", "locales/de.json"]:
        asset = client.get(f"{versioned}/{filename}")
        assert asset.status_code == 200
        assert asset.content == Path("app/static", filename).read_bytes()
    for language in LANGUAGES:
        response = client.get(f"/static/locales/{language}.json")
        assert response.status_code == 200
        assert response.headers["x-content-type-options"] == "nosniff"

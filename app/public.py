"""Server-rendered public content. No procurement or account data is used here."""

import json
from pathlib import Path

ORIGIN = "https://orqelis.pro"
LANGUAGES = {"en": "English", "de": "Deutsch", "fr": "Français", "es": "Español",
             "it": "Italiano", "nl": "Nederlands", "pl": "Polski", "pt": "Português"}
CONTENT = json.loads((Path(__file__).parent / "content" / "marketing.json").read_text("utf-8"))
GUIDES = json.loads((Path(__file__).parent / "content" / "guides.json").read_text("utf-8"))


def language_path(language):
    return "/" if language == "en" else f"/{language}/"


def indexable_paths():
    return {language_path(lang) for lang in LANGUAGES} | {
        "/guides/" + slug for slug in GUIDES
    } | {"/legal/sources"}


def structured_data(language, path, title, description):
    return {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "Organization", "@id": ORIGIN + "/#organization", "name": "Orqelis",
             "url": ORIGIN + "/", "logo": ORIGIN + "/static/mark.svg"},
            {"@type": "WebSite", "@id": ORIGIN + "/#website", "name": "Orqelis",
             "url": ORIGIN + "/", "inLanguage": list(LANGUAGES),
             "publisher": {"@id": ORIGIN + "/#organization"}},
            {"@type": "WebPage", "@id": ORIGIN + path + "#page", "url": ORIGIN + path,
             "name": title, "description": description, "inLanguage": language,
             "isPartOf": {"@id": ORIGIN + "/#website"}},
        ],
    }

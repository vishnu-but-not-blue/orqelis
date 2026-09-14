"""Read-only public API contract probe; save a bounded response for inspection."""

import json
from pathlib import Path

import httpx

from app.db import Base, SessionLocal, engine
from app.ingest import ingest, register_sources
from app.ted import FIELDS, normalize_api

r = httpx.post(
    "https://api.ted.europa.eu/v3/notices/search",
    json={
        "query": "publication-date >= 20260901",
        "fields": FIELDS,
        "limit": 2,
        "page": 1,
        "scope": "LATEST",
    },
    timeout=30,
)
r.raise_for_status()
Path("var").mkdir(exist_ok=True)
Path("var/ted-probe.json").write_text(r.text, encoding="utf-8")
print(json.dumps({"status": r.status_code, "notices": len(r.json().get("notices", []))}))
Base.metadata.create_all(engine)
with SessionLocal() as db:
    register_sources(db)
    for row in r.json().get("notices", []):
        normalized = normalize_api(row)
        ingest(db, normalized, json.dumps(row, sort_keys=True))
        print(
            json.dumps(
                {
                    "publication": normalized["publication_number"],
                    "deadline": normalized["deadline"],
                    "criteria": len(normalized["requirements"]),
                }
            )
        )
    db.commit()
publication = r.json()["notices"][0]["publication-number"]
xml = httpx.get(f"https://ted.europa.eu/en/notice/{publication}/xml", timeout=30)
xml.raise_for_status()
Path("var/ted-probe.xml").write_bytes(xml.content)
print(
    json.dumps(
        {"xml_status": xml.status_code, "bytes": len(xml.content), "publication": publication}
    )
)

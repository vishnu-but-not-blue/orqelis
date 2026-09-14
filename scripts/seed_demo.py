"""Explicitly labeled fixtures. Never loaded automatically into live search."""

import json
from datetime import UTC, datetime, timedelta

from app.db import Base, SessionLocal, engine
from app.ingest import ingest, register_sources
from app.requirements import extract_clauses


def demo_notices():
    at = datetime.now(UTC)
    examples = [
        (
            "Managed cloud infrastructure & security services",
            "Municipal Digital Services — Example",
            "DEU",
            420000,
            [
                "ISO 27001 certification is required.",
                "Annual turnover must be at least EUR 500,000.",
            ],
            "72000000",
        ),
        (
            "Digital accessibility audit and remediation",
            "Regional Public Services — Example",
            "IRL",
            185000,
            [
                "At least 3 similar project references are required.",
                "Professional indemnity insurance of at least EUR 1 million is required.",
            ],
            "72000000",
        ),
        (
            "Sustainable workplace furniture framework",
            "City Procurement Office — Example",
            "NLD",
            680000,
            ["ISO 14001 certification should be provided."],
            "39000000",
        ),
        (
            "Public-sector data platform modernization",
            "Regional Innovation Agency — Example",
            "FRA",
            950000,
            [
                "ISO 27001 certification is required.",
                "Average annual turnover of at least EUR 2 million during each of the last 3 years is required.",
            ],
            "72000000",
        ),
        (
            "Energy performance consultancy for public buildings",
            "Municipal Climate Office — Example",
            "BEL",
            275000,
            ["The supplier must provide 5 similar project references."],
            "79400000",
        ),
    ]
    for i, (title, buyer, country, value, criteria, cpv) in enumerate(examples):
        yield {
            "source_id": f"example-{i + 1}",
            "source_version": "1",
            "publication_number": f"EXAMPLE-{i + 1}",
            "source_url": "/legal/sources",
            "title": title,
            "description": "Demonstration procurement fixture for testing your workflow. This is not a published tender. "
            + " ".join(criteria),
            "buyer": buyer,
            "country": country,
            "published": at.date().isoformat(),
            "deadline": (at + timedelta(days=20 + i * 7)).isoformat(),
            "value": value,
            "currency": "EUR",
            "cpv_codes": [cpv],
            "nuts_codes": [],
            "requirements": extract_clauses(criteria, "Example fixture / Selection criteria"),
            "requirements_complete": True,
            "lots": [],
            "languages": ["ENG"],
            "status": "ACTIVE",
            "completeness_score": 95,
            "parser_confidence": 0.95,
            "source_format": "DEMO_FIXTURE",
            "extraction_warnings": ["This is example data, not a published opportunity."],
        }


def main():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        register_sources(db)
        for row in demo_notices():
            ingest(db, row, json.dumps(row, sort_keys=True), source="DEMO")
        db.commit()
    print("Loaded 5 clearly labeled example opportunities.")


if __name__ == "__main__":
    main()

"""Generate parity fixtures from the retained Python decision implementation (no DB access)."""

import json
import random
from datetime import UTC, datetime
from pathlib import Path

from app.decision import analyze_lots
from app.requirements import extract


def main():
    rng = random.Random(42)
    at = datetime(2026, 9, 15, tzinfo=UTC)
    cases = []
    clauses = [
        "ISO 27001 is required",
        "ISO 9001:2015 is required",
        "Annual turnover of at least EUR 2 million in each of the last 3 years",
        "Insurance of at least EUR 500000 is required",
        "At least 3 similar projects",
        "ISO 14001 is optional",
        "ISO 27001 or equivalent is required",
    ]
    for i in range(48):
        reqs = [extract(text, f"s/{j}").model_dump() for j, text in enumerate(clauses[: i % 7 + 1])]
        notice = {
            "requirements": reqs,
            "requirements_complete": i % 3 != 0,
            "deadline": [
                "2026-11-20T23:00:00+02:00",
                "2026-09-14T12:00:00Z",
                None,
                "2026-11-20T00:30:00+02:00",
            ][i % 4],
            "country": "DE",
            "languages": ["EN"],
            "cpv_codes": ["72000000", "48000000"],
            "value": 1000000,
            "currency": "EUR",
            "completeness_score": 90,
            "status": "CANCELLED" if i == 47 else "ACTIVE",
            "document_count": i % 4,
        }
        profile = {
            "operating_countries": ["DE"] if i % 2 else [],
            "languages": ["EN"],
            "cpv_interests": ["72000000"],
            "bid_hours_per_day": rng.choice([2, 8, 24]),
            "expected_margin": rng.choice([None, 10, 30]),
            "effort_multiplier": 1,
        }
        evidence = [
            {
                "id": str(j),
                "capability": r["capability"],
                "document_id": "d" if i % 5 else None,
                "document_available": i % 6 != 0,
                "state": ["UNVERIFIED", "USER_CONFIRMED", "EXPIRED"][i % 3],
                "valid_until": "2027-01-01" if i % 4 else "2026-10-01",
                "data": {
                    "value": rng.choice([2, 10, 3000000]),
                    "currency": "EUR",
                    "annual_values": {"2025": 3000000, "2024": 3000000, "2023": 3000000},
                },
            }
            for j, r in enumerate(reqs)
        ]
        if i % 8 == 0:
            notice["lots"] = [{"id": "LOT-1"}, {"id": "LOT-2", "value": 400000}]
        result = analyze_lots(notice, profile, evidence, at)
        cases.append(
            {
                "notice": notice,
                "profile": profile,
                "evidence": evidence,
                "at": at.isoformat(),
                "expected": result,
            }
        )
    target = Path("cloudflare/test/fixtures/decision.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(cases), encoding="utf-8")
    print(f"Generated {len(cases)} Python decision parity cases.")


if __name__ == "__main__":
    main()

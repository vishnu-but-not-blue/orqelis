import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.requirements import canonical

ALGORITHM_VERSION = "decision-1.0"
WEIGHTS = {
    "technical_fit": 0.25,
    "evidence_coverage": 0.3,
    "financial_fit": 0.15,
    "geography": 0.1,
    "deadline": 0.15,
    "capacity": 0.05,
}
ATTRACTIVENESS_WEIGHTS = {
    "size_fit": 0.4,
    "margin": 0.25,
    "bid_cost_ratio": 0.2,
    "strategic_fit": 0.15,
}


def parse_datetime(value):
    if not value:
        return None
    if "T" not in value and " " not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def cache_key(notice_hash, capability_version, corrections, day=None):
    # A daily time dependency prevents expired evidence/deadlines from retaining a cached PASS.
    return hashlib.sha256(
        json.dumps(
            [
                notice_hash,
                capability_version,
                ALGORITHM_VERSION,
                "deterministic",
                corrections,
                str(day or date.today()),
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()


def evaluate(req, evidence, deadline, today=None):
    today = today or datetime.now(UTC).date()
    target = deadline.date() if deadline else today
    base = {
        "requirement": req,
        "state": "UNKNOWN",
        "evidence_ids": [],
        "reason": "No confirmed documentary evidence proves this requirement.",
        "next_action": "Add evidence for " + req["capability"],
    }
    if req.get("not_applicable"):
        return base | {
            "state": "NOT_APPLICABLE",
            "reason": "Source explicitly states this is not required.",
            "next_action": None,
        }
    if req.get("ambiguous") or req["capability"] == "UNKNOWN":
        return base | {
            "reason": "Ambiguous or unsupported clause. Review the original source and obtain clarification.",
            "next_action": "Clarify: " + req["text"],
        }
    candidates = [
        e
        for e in evidence
        if canonical(e["capability"]) == canonical(req["capability"])
        and e.get("state") in {"USER_CONFIRMED", "SYSTEM_VERIFIED", "EXPIRED"}
        and e.get("document_id")
        and e.get("document_available", True)
    ]
    failures = []
    for e in candidates:
        if e.get("valid_from") and date.fromisoformat(e["valid_from"]) > today:
            continue
        if e.get("state") == "EXPIRED" or (
            e.get("valid_until") and date.fromisoformat(e["valid_until"]) < target
        ):
            failures.append(
                (e["id"], "Evidence expires before the required date; renewal is not assumed.")
            )
            continue
        data = e.get("data", {})
        if req.get("edition") and req["edition"] not in data.get("original_capability", ""):
            continue
        if req["category"] == "CERTIFICATION" and not e.get("valid_until"):
            continue
        if req.get("currency") and req["currency"] != data.get("currency"):
            continue  # No implicit FX comparison.
        if req.get("threshold") is not None:
            values = [data.get("value")]
            if req.get("years"):
                annual = data.get("annual_values", {})
                required_years = [str(target.year - n) for n in range(1, req["years"] + 1)]
                if not all(year in annual for year in required_years):
                    continue
                values = [annual[year] for year in required_years]
                if req.get("period_mode") == "average":
                    values = [sum(values) / len(values)]
                elif req.get("period_mode") == "aggregate":
                    values = [sum(values)]
            if any(v is None for v in values):
                continue
            threshold = Decimal(str(req["threshold"]))
            comparisons = {
                "gte": lambda v: v >= threshold,
                "gt": lambda v: v > threshold,
                "lte": lambda v: v <= threshold,
            }
            compare = comparisons.get(req.get("comparator"))
            if compare is None:
                continue
            if not all(compare(Decimal(str(v))) for v in values):
                failures.append(
                    (e["id"], "Confirmed documentary value does not meet the source threshold.")
                )
                continue
        return base | {
            "state": "PASS",
            "reason": "Confirmed document satisfies the normalized predicate and validity window.",
            "evidence_ids": [e["id"]],
            "next_action": None,
        }
    if failures:
        return base | {
            "state": "FAIL",
            "reason": failures[0][1],
            "evidence_ids": [v[0] for v in failures],
        }
    return base


def business_days(start, end):
    if end <= start:
        return 0
    total = (end - start).days
    weeks, remainder = divmod(total, 7)
    return weeks * 5 + sum(
        (start + timedelta(days=weeks * 7 + i)).weekday() < 5 for i in range(remainder)
    )


def analyze(notice, profile, evidence, at=None, lot_id=None):
    at = at or datetime.now(UTC)
    requirements = [r for r in notice.get("requirements", []) if r.get("lot_id") in (None, lot_id)]
    deadline = parse_datetime(notice.get("deadline"))
    results = [evaluate(r, evidence, deadline, at.date()) for r in requirements]
    relevant = [r for r in results if r["state"] != "NOT_APPLICABLE"]
    total = sum(3 if r["requirement"]["hard_gate"] else 1 for r in relevant)
    verified = sum(
        3 if r["requirement"]["hard_gate"] else 1 for r in relevant if r["state"] == "PASS"
    )
    coverage = round(verified / total * 100) if total else 0
    failures = [r for r in results if r["state"] == "FAIL" and r["requirement"]["hard_gate"]]
    unknown = [r for r in results if r["state"] == "UNKNOWN" and r["requirement"]["hard_gate"]]
    complete = notice.get("requirements_complete", False)
    eligibility = "FAIL" if failures else "UNKNOWN" if unknown or not complete else "PASS"
    friction = []
    countries = profile.get("operating_countries", [])
    if notice.get("country") and notice["country"] not in countries:
        friction.append(
            {
                "reason": "Buyer country is outside declared operating countries. Confirm the place of performance.",
                "source": "buyer_country",
                "kind": "GEOGRAPHY",
            }
        )
    languages = notice.get("languages", [])
    if languages and not set(languages).intersection(profile.get("languages", [])):
        friction.append(
            {
                "reason": "The source language is outside declared working languages; confirm submission language and translation needs.",
                "source": "languages",
                "kind": "LANGUAGE",
            }
        )
    for key, label in [
        ("onsite", "Onsite delivery is specified."),
        ("site_visit", "A mandatory site visit is specified."),
    ]:
        if notice.get(key):
            friction.append({"reason": label, "source": key, "kind": "LOGISTICS"})
    missing = len([r for r in results if r["state"] in ("UNKNOWN", "FAIL")])
    effort_base = (
        12
        + len(requirements) * 2
        + missing * 3
        + notice.get("document_count", 0) * 2
        + len(friction) * 5
    )
    effort = [round(effort_base * 0.8), round(effort_base * 1.3)]
    if profile.get("effort_multiplier"):
        effort = [round(v * profile["effort_multiplier"]) for v in effort]
    available = (
        business_days(at.date(), deadline.date())
        * profile.get("bid_hours_per_day", 2)
        * profile.get("availability_factor", 0.8)
        if deadline
        else None
    )
    deadline_score = (
        0
        if deadline and deadline <= at
        else 50
        if available is None
        else min(100, round(available / max(effort[1], 1) * 100))
    )
    cpvs, interests = notice.get("cpv_codes", []), profile.get("cpv_interests", [])
    overlap = sum(any(str(c)[:2] == str(p)[:2] for p in interests) for c in cpvs)
    technical = round(overlap / len(cpvs) * 100) if cpvs and interests else 0
    financial_results = [r for r in results if r["requirement"]["category"] == "FINANCIAL"]
    financial = (
        round(sum(r["state"] == "PASS" for r in financial_results) / len(financial_results) * 100)
        if financial_results
        else 50
    )
    components = {
        "technical_fit": technical,
        "evidence_coverage": coverage,
        "financial_fit": financial,
        "geography": max(0, 100 - len(friction) * 25),
        "deadline": deadline_score,
        "capacity": deadline_score,
    }
    feasibility = round(sum(components[k] * w for k, w in WEIGHTS.items()))
    hourly = profile.get("hourly_cost", 60)
    external = profile.get("external_bid_cost", 0)
    cost = [round(h * hourly + external) for h in effort]
    value, currency = notice.get("value"), notice.get("currency")
    comparable = value is not None and currency == profile.get("currency", "EUR")
    minimum, maximum = profile.get("min_contract", 0), profile.get("max_contract", 1000000)
    size_fit = 100 if comparable and minimum <= value <= maximum else 20 if comparable else 50
    margin = profile.get("expected_margin")
    attr = {
        "size_fit": size_fit,
        "margin": min(100, margin * 3) if margin is not None else 50,
        "bid_cost_ratio": max(0, 100 - cost[1] / value * 1000) if comparable and value > 0 else 50,
        "strategic_fit": profile.get("strategic_fit", 50),
    }
    attractiveness = round(sum(attr[k] * w for k, w in ATTRACTIVENESS_WEIGHTS.items()))
    confidence = round(
        (
            notice.get("completeness_score", 0) * 0.4
            + coverage * 0.4
            + (
                sum(r["confidence"] for r in requirements) / len(requirements) * 100
                if requirements
                else 0
            )
            * 0.2
        )
    )
    decision, explanation = (
        "REVIEW",
        "Resolve missing or ambiguous evidence before committing bid resources.",
    )
    if failures or notice.get("status") == "CANCELLED" or (deadline and deadline <= at):
        decision, explanation = (
            "NO_BID",
            "A mandatory failure, cancellation, or elapsed deadline prevents a supported bid recommendation.",
        )
    elif eligibility == "PASS" and confidence >= 75 and deadline and available >= effort[1]:
        if feasibility >= 85 and attractiveness >= 75:
            decision, explanation = (
                "STRONG_BID",
                "Verified eligibility, strong fit, and sufficient estimated capacity support pursuing this opportunity.",
            )
        elif feasibility >= 65 and attractiveness >= 50:
            decision, explanation = (
                "BID",
                "Verified eligibility and practical fit support a bid, subject to your final review.",
            )
    elif (
        eligibility == "PASS"
        and confidence >= 65
        and available is not None
        and effort[0] <= available < effort[1]
    ):
        decision, explanation = (
            "CONDITIONAL_BID",
            "Eligibility is supported; allocate additional bid capacity before proceeding.",
        )
    if available is not None and available < effort[0] and decision != "NO_BID":
        decision, explanation = (
            "REVIEW",
            "Estimated minimum effort exceeds available bid-team hours.",
        )
    return {
        "decision": decision,
        "explanation": explanation,
        "eligibility": eligibility,
        "feasibility": feasibility,
        "attractiveness": attractiveness,
        "confidence": confidence,
        "coverage": coverage,
        "coverage_numerator": verified,
        "coverage_denominator": total,
        "components": {
            k: {
                "score": v,
                "weight": WEIGHTS[k],
                "basis": "Documentary coverage"
                if k == "evidence_coverage"
                else "Declared profile and source facts; heuristic",
            }
            for k, v in components.items()
        },
        "attractiveness_components": {
            k: {"score": round(v), "weight": ATTRACTIVENESS_WEIGHTS[k]} for k, v in attr.items()
        },
        "requirements": results,
        "friction": friction,
        "effort_hours": effort,
        "available_hours": available,
        "cost_range": cost,
        "cost_currency": profile.get("currency", "EUR"),
        "cost_inputs": {"hourly_cost": hourly, "external_known_cost": external},
        "unmodeled_costs": [
            "Translation, certification, travel and partner costs unless included in your external-cost assumption."
        ],
        "missing_evidence": [r["next_action"] for r in results if r["next_action"]],
        "uncertainty": (
            [] if complete else ["Full tender documentation has not been confirmed complete."]
        )
        + ([] if deadline else ["Authoritative deadline or timezone missing."])
        + [
            "Competition and incumbency are unavailable unless supported by historical awards.",
            "Effort and attractiveness are estimates, not a win probability.",
        ],
        "sensitivity": "ROBUST"
        if decision in ("BID", "STRONG_BID")
        and available is not None
        and available >= effort[1] * 1.25
        else "FRAGILE",
        "algorithm_version": ALGORITHM_VERSION,
        "model_version": "deterministic",
        "lot_id": lot_id,
        "analyzed_at": at.isoformat(),
    }


def analyze_lots(notice, profile, evidence, at=None):
    lots = notice.get("lots", [])
    if not lots:
        return analyze(notice, profile, evidence, at)
    results = [analyze(notice | lot, profile, evidence, at, lot["id"]) for lot in lots]
    summary = analyze(notice, profile, evidence, at)
    summary["lots"] = results
    summary["decision"] = "REVIEW"
    summary["explanation"] = (
        "Lot-level assessments govern eligibility. Select the lots you intend to bid for; tender-wide aggregation is not assumed."
    )
    return summary

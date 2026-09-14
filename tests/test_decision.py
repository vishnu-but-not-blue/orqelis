from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from app.decision import analyze, analyze_lots, business_days, cache_key, evaluate
from app.requirements import extract

AT = datetime(2026, 9, 14, tzinfo=UTC)
DEADLINE = datetime(2026, 11, 20, tzinfo=UTC)


def certificate(**kwargs):
    return {
        "id": "e1",
        "capability": "ISO 27001",
        "state": "USER_CONFIRMED",
        "document_id": "d1",
        "valid_until": "2027-01-01",
        "data": {},
    } | kwargs


def test_unknown_never_passes():
    req = extract("ISO 27001 is required", "section 3").model_dump()
    assert evaluate(req, [], DEADLINE, AT.date())["state"] == "UNKNOWN"
    assert (
        evaluate(req, [certificate(state="UNVERIFIED")], DEADLINE, AT.date())["state"] == "UNKNOWN"
    )
    assert evaluate(req, [certificate(document_id=None)], DEADLINE, AT.date())["state"] == "UNKNOWN"
    assert (
        evaluate(req, [certificate(document_available=False)], DEADLINE, AT.date())["state"]
        == "UNKNOWN"
    )


def test_certificate_valid_at_deadline():
    req = extract("ISO 27001 is required", "section 3").model_dump()
    assert evaluate(req, [certificate()], DEADLINE, AT.date())["state"] == "PASS"
    assert (
        evaluate(req, [certificate(valid_until="2026-10-01")], DEADLINE, AT.date())["state"]
        == "FAIL"
    )
    assert evaluate(req, [certificate(valid_until=None)], DEADLINE, AT.date())["state"] == "UNKNOWN"


def test_currency_and_annual_requirements():
    req = extract(
        "Average annual turnover of at least EUR 2 million during each of the last 3 years", "s"
    ).model_dump()
    evidence = certificate(
        capability="TURNOVER",
        data={
            "currency": "EUR",
            "value": 3000000,
            "annual_values": {"2025": 3000000, "2024": 3000000, "2023": 1000000},
        },
    )
    assert evaluate(req, [evidence], DEADLINE, AT.date())["state"] == "FAIL"
    assert (
        evaluate(
            req, [evidence | {"data": evidence["data"] | {"currency": "GBP"}}], DEADLINE, AT.date()
        )["state"]
        == "UNKNOWN"
    )
    assert (
        evaluate(
            req, [evidence | {"data": {"currency": "EUR", "value": 3000000}}], DEADLINE, AT.date()
        )["state"]
        == "UNKNOWN"
    )


def tender():
    return {
        "requirements": [extract("ISO 27001 is required", "s").model_dump()],
        "requirements_complete": True,
        "deadline": DEADLINE.isoformat(),
        "country": "DEU",
        "cpv_codes": ["72000000"],
        "value": 400000,
        "currency": "EUR",
        "completeness_score": 100,
        "status": "ACTIVE",
    }


def profile():
    return {
        "operating_countries": ["DEU"],
        "cpv_interests": ["72000000"],
        "hourly_cost": 60,
        "bid_hours_per_day": 8,
        "max_contract": 1000000,
        "expected_margin": 30,
    }


def test_hard_failure_cannot_be_outscored():
    result = analyze(tender(), profile(), [certificate(valid_until="2026-10-01")], AT)
    assert result["decision"] == "NO_BID"
    assert result["eligibility"] == "FAIL"


def test_real_supported_bid_and_unknown_metadata():
    result = analyze(tender(), profile(), [certificate()], AT)
    assert result["decision"] in {"BID", "STRONG_BID"}
    assert result["coverage_numerator"] == result["coverage_denominator"] == 3
    assert (
        analyze(tender() | {"requirements_complete": False}, profile(), [certificate()], AT)[
            "decision"
        ]
        == "REVIEW"
    )
    assert (
        analyze(tender() | {"deadline": "2026-11-20"}, profile(), [certificate()], AT)["decision"]
        == "REVIEW"
    )


def test_lots_are_evaluated_independently():
    a = extract("ISO 27001 is required", "lotA", "A").model_dump()
    b = extract("ISO 9001 is required", "lotB", "B").model_dump()
    result = analyze_lots(
        tender() | {"requirements": [a, b], "lots": [{"id": "A"}, {"id": "B"}]},
        profile(),
        [certificate()],
        AT,
    )
    assert result["lots"][0]["eligibility"] == "PASS"
    assert result["lots"][1]["eligibility"] == "UNKNOWN"
    assert result["decision"] == "REVIEW"


def test_cross_border_is_not_legal_failure():
    result = analyze(tender(), profile() | {"operating_countries": ["FRA"]}, [certificate()], AT)
    assert result["eligibility"] == "PASS" and result["friction"]


def test_cache_and_business_days():
    assert cache_key("hash", 1, []) != cache_key("hash", 2, [])
    assert cache_key("hash", 1, [], "2026-09-14") != cache_key("hash", 1, [], "2026-09-15")
    assert business_days(AT.date(), DEADLINE.date()) == 49


@given(st.floats(min_value=0, max_value=1e6, allow_nan=False, allow_infinity=False))
def test_scores_bounded(hourly):
    result = analyze(tender(), profile() | {"hourly_cost": hourly}, [certificate()], AT)
    for key in ["coverage", "feasibility", "attractiveness", "confidence"]:
        assert 0 <= result[key] <= 100

import json
from pathlib import Path

import pytest

from app.requirements import extract
from app.ted import normalize_xml

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "case", json.loads((FIXTURES / "golden.json").read_text()), ids=lambda c: c["name"]
)
def test_golden_requirement(case):
    parsed = extract(case["text"], "golden/" + case["name"]).model_dump()
    for key, expected in case["expected"].items():
        assert parsed[key] == expected


def test_eforms_preserves_lot_structure_and_timezones():
    n = normalize_xml((FIXTURES / "eforms.xml").read_bytes(), "123456-2026")
    assert n["title"] == "Secure public cloud services"
    assert n["value"] == 400000 and n["currency"] == "EUR"
    assert n["lots"][0]["deadline"] == "2026-11-20T12:00:00+01:00"
    assert n["requirements"][0]["lot_id"] == "LOT-0001"
    assert n["requirements"][1]["lot_id"] == "LOT-0002"
    assert n["requirements"][1]["threshold"] == 2000000
    assert not n["requirements_complete"]


def test_legacy_attributes_and_provenance():
    n = normalize_xml((FIXTURES / "legacy.xml").read_bytes())
    assert n["country"] == "FRA"
    assert n["cpv_codes"] == ["72000000"]
    assert n["source_id"] == "123456-2020"
    assert n["source_format"] == "LEGACY_XML"


def test_multilingual_criteria_require_review():
    xml = (
        (FIXTURES / "eforms.xml")
        .read_text()
        .replace('languageID="ENG"', 'languageID="DEU"')
        .replace("ISO 27001 must be provided.", "ISO 27001 ist nicht erforderlich.")
    )
    n = normalize_xml(xml.encode())
    assert n["requirements"][0]["ambiguous"]
    assert n["requirements"][0]["verification_state"] == "REVIEW_REQUIRED"


def test_cancelled_notice():
    xml = (
        (FIXTURES / "eforms.xml")
        .read_text()
        .replace(
            "</ContractNotice>",
            "<cbc:CompetitionTerminatedIndicator>true</cbc:CompetitionTerminatedIndicator></ContractNotice>",
        )
    )
    assert normalize_xml(xml.encode())["status"] == "CANCELLED"

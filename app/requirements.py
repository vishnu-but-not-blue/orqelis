"""Conservative, source-bound extraction. Unrecognized clauses remain review items."""

import hashlib
import re
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field

PARSER_VERSION = "requirements-1.0"


def canonical(value: str) -> str:
    text = value.upper().strip()
    iso = re.search(r"ISO\s*(?:/\s*IEC\s*)?(\d{4,5}(?:-\d+)?)", text)
    if iso:
        return "ISO " + iso[1]
    return {
        "REVENUE": "TURNOVER",
        "ANNUAL TURNOVER": "TURNOVER",
        "PROFESSIONAL INDEMNITY": "INSURANCE",
    }.get(text, text)


def number(text: str) -> Decimal | None:
    match = re.search(
        r"(?<![\d-])(\d[\d\s.,]*)(?:\s*(million|billion|thousand|m\b|k\b))?", text.lower()
    )
    if not match:
        return None
    raw = re.sub(r"\s", "", match[1]).rstrip(".,")
    if "," in raw and "." in raw:
        decimal = "," if raw.rfind(",") > raw.rfind(".") else "."
        raw = raw.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    elif "," in raw or "." in raw:
        sep = "," if "," in raw else "."
        chunks = raw.split(sep)
        raw = "".join(chunks) if all(len(c) == 3 for c in chunks[1:]) else raw.replace(",", ".")
    try:
        result = Decimal(raw) * {
            "million": 1000000,
            "m": 1000000,
            "billion": 1000000000,
            "thousand": 1000,
            "k": 1000,
        }.get(match[2], 1)
        return result if result >= 0 else None
    except InvalidOperation:
        return None


class Requirement(BaseModel):
    id: str
    category: str = "OTHER"
    edition: str | None = None
    text: str
    capability: str = "UNKNOWN"
    comparator: str = "exists"
    threshold: float | None = Field(default=None, ge=0)
    currency: str | None = None
    unit: str | None = None
    years: int | None = None
    period_mode: str | None = None
    hard_gate: bool = True
    not_applicable: bool = False
    ambiguous: bool = False
    lot_id: str | None = None
    confidence: float = Field(default=0.9, ge=0, le=1)
    source_locator: str
    verification_state: str = "EXTRACTED"
    combination_rule: str = "must_be_prime"
    remediability: str = "DOCUMENT_CAN_PROVE"


def extract(text: str, locator: str, lot_id=None) -> Requirement:
    lower = text.lower()
    req = Requirement(
        id=hashlib.sha256(f"{locator}|{text}|{lot_id}".encode()).hexdigest()[:20],
        text=text,
        source_locator=locator,
        lot_id=lot_id,
    )
    req.not_applicable = bool(re.search(r"\b(not required|no .{0,35} required|need not)\b", lower))
    optional = bool(re.search(r"\b(may|should|optional|recommended)\b", lower))
    req.hard_gate = not (req.not_applicable or optional)
    req.ambiguous = bool(
        re.search(r"\b(unless|except|either|only if|consortium| or |between)\b", lower)
    )
    if "consortium" in lower or "subcontract" in lower:
        req.combination_rule = "unknown_combination_rule"
        req.remediability = "CLARIFICATION_NEEDED"
    cert = re.search(r"ISO\s*(?:/\s*IEC\s*)?\d{4,5}(?:-\d+)?(?::\d{4})?", text, re.I)
    if cert:
        req.category, req.capability = "CERTIFICATION", canonical(cert[0])
        edition = re.search(r":(\d{4})", cert[0])
        req.edition = edition[1] if edition else None
        if re.search(r"turnover|insurance|references|staff", lower):
            req.ambiguous = True
    elif "turnover" in lower or "revenue" in lower:
        req.category, req.capability, req.unit = "FINANCIAL", "TURNOVER", "money"
    elif "insurance" in lower or "indemnity" in lower:
        req.category, req.capability, req.unit = "INSURANCE", "INSURANCE", "money"
    elif re.search(r"\b(references|reference projects|similar projects)\b", lower):
        req.category, req.capability, req.unit = "EXPERIENCE", "REFERENCES", "count"
    elif "language" in lower or "submitted in" in lower:
        req.category, req.capability = "LANGUAGE", "LANGUAGE"
        req.ambiguous = True
    else:
        req.ambiguous = True
        req.confidence = 0.4
    if req.unit:
        money = re.search(
            r"(?:EUR|GBP|USD|€|£|\$)\s*(\d[\d., ]*(?:\s*(?:million|billion|thousand|[mk]\b))?)",
            text,
            re.I,
        )
        trailing = re.search(
            r"(\d[\d., ]*(?:\s*(?:million|billion|thousand|[mk]\b))?)\s*(?:EUR|GBP|USD|€|£|\$)",
            text,
            re.I,
        )
        numeric = money or trailing
        count_match = re.search(
            r"(\d+)\s+(?:similar\s+|project\s+|completed\s+)*(?:references|projects)", text, re.I
        )
        value = number(
            count_match[1]
            if req.unit == "count" and count_match
            else numeric[1]
            if numeric
            else text
        )
        if req.unit == "count" and numeric:
            req.ambiguous = (
                True  # Project count and minimum project values need separate predicates.
            )
        req.threshold = float(value) if value is not None else None
        req.comparator = "gte"
        if re.search(r"more than|greater than|exceeding", lower) and "not exceeding" not in lower:
            req.comparator = "gt"
        if re.search(r"not exceeding|at most|maximum", lower):
            req.comparator = "lte"
        if req.unit == "money":
            req.currency = next(
                (
                    v
                    for k, v in [
                        ("eur", "EUR"),
                        ("€", "EUR"),
                        ("gbp", "GBP"),
                        ("£", "GBP"),
                        ("usd", "USD"),
                        ("$", "USD"),
                    ]
                    if k in lower
                ),
                None,
            )
            if not numeric or not req.currency:
                req.ambiguous = True
        years = re.search(r"(?:last|previous|past)\s+(\d+)\s+years", lower)
        if years:
            req.years = int(years[1])
            req.period_mode = (
                "each"
                if "each" in lower
                else "average"
                if "average" in lower
                else "aggregate"
                if "aggregate" in lower
                else "unspecified"
            )
            if req.period_mode == "unspecified":
                req.ambiguous = True
        if req.threshold is None:
            req.ambiguous = True
    if req.ambiguous:
        req.confidence = min(req.confidence, 0.5)
        req.verification_state = "REVIEW_REQUIRED"
    return req


def extract_clauses(clauses, locator="criteria", lot_id=None):
    return [
        extract(str(text), f"{locator}/{i + 1}", lot_id).model_dump()
        for i, text in enumerate(clauses)
        if str(text).strip()
    ]


def validate_model_extraction(output: dict, source: str) -> Requirement:
    req = Requirement.model_validate(output)
    if req.text not in source or not req.source_locator:
        raise ValueError("Extraction is not bound to the supplied source")
    # Model output can propose candidates, never independently verify a legal gate.
    req.verification_state = "REVIEW_REQUIRED"
    req.ambiguous = True
    req.confidence = min(req.confidence, 0.5)
    return req

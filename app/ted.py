import asyncio
import hashlib
import io
import ipaddress
import json
import random
import re
import socket
import time
import zipfile
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.requirements import extract_clauses

FIELDS = [
    "publication-number",
    "notice-title",
    "publication-date",
    "buyer-country",
    "classification-cpv",
    "deadline-receipt-tender-date-lot",
    "estimated-value-proc",
    "estimated-value-cur-proc",
    "buyer-name",
    "notice-type",
    "procedure-type",
    "links",
    "notice-identifier",
    "notice-version",
    "change-notice-version-identifier",
    "deadline-receipt-tender-time-lot",
    "description-proc",
    "selection-criterion-description-lot",
    "selection-criteria-source",
    "submission-language",
    "submission-url-lot",
    "competition-termination-proc",
    "contract-duration-period-lot",
    "option-description-lot",
    "non-award-justification",
    "official-language",
]


def safe_url(url, resolve=True):
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname
        not in {"api.ted.europa.eu", "ted.europa.eu", "ted.europa.eu", "data.europa.eu"}
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Only allowlisted official HTTPS sources may be fetched")
    if resolve:
        for result in socket.getaddrinfo(parsed.hostname, 443):
            ip = ipaddress.ip_address(result[4][0])
            if not ip.is_global:
                raise ValueError("Source resolves to a non-public address")
    return url


class TedClient:
    def __init__(self, client=None, sleep=asyncio.sleep):
        self.client = client or httpx.AsyncClient(
            timeout=30, follow_redirects=False, trust_env=False
        )
        self.sleep = sleep
        self.semaphore = asyncio.Semaphore(settings().ted_concurrency)
        self.rate_lock = asyncio.Lock()
        self.last_request = 0.0
        self.failures = 0
        self.open_until = 0.0

    async def request(self, url, payload=None):
        safe_url(url)
        if not settings().ted_enabled:
            raise RuntimeError("TED source disabled")
        if self.open_until > time.monotonic():
            raise RuntimeError("TED circuit breaker is open; cached records remain available")
        async with self.semaphore:
            for attempt in range(4):
                async with self.rate_lock:
                    wait = 60 / max(settings().ted_requests_per_minute, 1) - (
                        time.monotonic() - self.last_request
                    )
                    if wait > 0:
                        await self.sleep(wait)
                    self.last_request = time.monotonic()
                try:
                    async with self.client.stream(
                        "POST" if payload is not None else "GET", url, json=payload
                    ) as response:
                        if response.status_code in {202, 429} or response.status_code >= 500:
                            self.failures += 1
                            delay = min(60, 2**attempt + random.random())
                            retry = response.headers.get("retry-after")
                            if retry:
                                try:
                                    delay = max(delay, float(retry))
                                except ValueError:
                                    delay = max(
                                        delay,
                                        (
                                            parsedate_to_datetime(retry) - datetime.now(UTC)
                                        ).total_seconds(),
                                    )
                            if delay > 60:
                                self.open_until = time.monotonic() + delay
                                raise RuntimeError("TED requested an extended retry delay")
                            await self.sleep(max(delay, 0))
                            continue
                        response.raise_for_status()
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > 25 * 1024 * 1024:
                                raise ValueError("Upstream response exceeds size limit")
                            chunks.append(chunk)
                        self.failures = 0
                        return b"".join(chunks)
                except (httpx.TimeoutException, httpx.NetworkError):
                    self.failures += 1
                    await self.sleep(2**attempt + random.random())
            self.open_until = time.monotonic() + 120
            raise RuntimeError("TED temporarily unavailable; retry queued")

    async def search(self, query, page=1):
        return json.loads(
            await self.request(
                "https://api.ted.europa.eu/v3/notices/search",
                {"query": query, "fields": FIELDS, "limit": 50, "page": page, "scope": "LATEST"},
            )
        )

    async def xml(self, publication):
        if not re.fullmatch(r"\d+-\d{4}", publication):
            raise ValueError("Invalid publication number")
        return await self.request(f"https://ted.europa.eu/en/notice/{publication}/xml")

    async def close(self):
        await self.client.aclose()


def flatten(value):
    if isinstance(value, dict):
        if "eng" in value:
            return flatten(value["eng"])
        return [v for item in value.values() for v in flatten(item)]
    if isinstance(value, list):
        return [v for item in value for v in flatten(item)]
    return [str(value)] if value is not None else []


def first(row, key, default=""):
    values = flatten(row.get(key))
    return values[0] if values else default


def source_datetime(date_value, time_value=None):
    """TED xsd:date + xsd:time. Date alone is not a precise deadline."""
    if not date_value:
        return None
    if "T" in date_value:
        combined = date_value
    elif time_value:
        offset = re.search(r"(Z|[+-]\d{2}:\d{2})$", date_value)
        combined = date_value[:10] + "T" + time_value
        if not re.search(r"(Z|[+-]\d{2}:\d{2})$", time_value) and offset:
            combined += offset[1]
    else:
        return None
    try:
        parsed = datetime.fromisoformat(combined.replace("Z", "+00:00"))
        return parsed.isoformat() if parsed.tzinfo else None
    except ValueError:
        return None


def normalize_api(row):
    publication = first(row, "publication-number")
    if not re.fullmatch(r"\d+-\d{4}", publication):
        raise ValueError("Missing or invalid authoritative publication number")
    value = first(row, "estimated-value-proc", None)
    try:
        value = float(value) if value else None
    except ValueError:
        value = None
    normalized = {
        "source_id": first(row, "notice-identifier", publication),
        "source_version": first(row, "notice-version", publication),
        "publication_number": publication,
        "source_url": f"https://ted.europa.eu/en/notice/-/detail/{publication}",
        "title": first(row, "notice-title", "Untitled procurement notice"),
        "description": first(row, "description-proc"),
        "buyer": first(row, "buyer-name", "Not provided"),
        "country": first(row, "buyer-country"),
        "cpv_codes": list(dict.fromkeys(flatten(row.get("classification-cpv")))),
        "nuts_codes": [],
        "published": first(row, "publication-date")[:10],
        "source_publication_date": first(row, "publication-date"),
        "deadline": None,
        "source_deadline_dates": flatten(row.get("deadline-receipt-tender-date-lot")),
        "value": value,
        "currency": first(row, "estimated-value-cur-proc", None),
        "notice_type": first(row, "notice-type"),
        "procedure": first(row, "procedure-type"),
        "status": "CANCELLED"
        if first(row, "competition-termination-proc").lower() == "true"
        else "AWARDED"
        if first(row, "notice-type").startswith("can-")
        else "ACTIVE",
        "lots": [],
        "requirements": [],
        "requirements_complete": False,
        "languages": [v.upper() for v in flatten(row.get("submission-language"))],
        "official_languages": [v.upper() for v in flatten(row.get("official-language"))],
        "submission_urls": [
            u for u in flatten(row.get("submission-url-lot")) if urlparse(u).scheme == "https"
        ],
        "duration": flatten(row.get("contract-duration-period-lot")),
        "renewal_options": flatten(row.get("option-description-lot")),
        "change_reference": first(row, "change-notice-version-identifier", None),
        "source_format": "TED_SEARCH_JSON",
        "parser_confidence": 0.85,
        "extraction_warnings": [
            "Search metadata is not the full tender dossier. Selection criteria and linked documents need review."
        ],
        "completeness_score": 45,
        "source_fields": row,
    }
    dates = list(dict.fromkeys(flatten(row.get("deadline-receipt-tender-date-lot"))))
    times = list(dict.fromkeys(flatten(row.get("deadline-receipt-tender-time-lot"))))
    if len(dates) == 1 and len(times) == 1:
        normalized["deadline"] = source_datetime(dates[0], times[0])
    clauses = list(dict.fromkeys(flatten(row.get("selection-criterion-description-lot"))))
    normalized["requirements"] = extract_clauses(
        clauses, f"TED/{publication}/selection-criterion-description-lot"
    )
    for requirement in normalized["requirements"]:
        requirement["ambiguous"] = True
        requirement["verification_state"] = "REVIEW_REQUIRED"
        requirement["confidence"] = min(requirement["confidence"], 0.5)
    if clauses:
        normalized["completeness_score"] = 65
        normalized["extraction_warnings"].append(
            "Search arrays omit structural lot associations. Confirm original-language conditions and lot scope against the full dossier."
        )
    return normalized


def normalize_xml(data, publication=None):
    from app.xml_parser import parse_xml

    return parse_xml(data, publication)


def archive_members(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        items = archive.infolist()
        if len(items) > 1000 or sum(i.file_size for i in items) > 100 * 1024 * 1024:
            raise ValueError("Archive expansion limit exceeded")
        for item in items:
            if item.is_dir():
                continue
            if (
                ".." in item.filename.replace("\\", "/").split("/")
                or item.filename.startswith(("/", "\\"))
                or ":" in item.filename
            ):
                raise ValueError("Unsafe archive member")
            if (
                item.file_size > 25 * 1024 * 1024
                or item.file_size / max(item.compress_size, 1) > 200
            ):
                raise ValueError("Archive compression limit exceeded")
            if item.filename.lower().endswith(".xml"):
                yield item.filename, archive.read(item)


def content_hash(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()

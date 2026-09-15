import hashlib
import io
import re
import secrets
import shlex
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Protocol

import httpx
from fastapi import HTTPException
from pypdf import PdfReader

from app.config import settings


class ObjectStorage(Protocol):
    def put(self, data: bytes) -> str: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str): ...
    def metadata(self, key: str) -> dict: ...
    def health(self) -> bool: ...


class LocalStorage:
    def __init__(self, root=None):
        self.root = Path(root or settings().storage_path).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key):
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ValueError("Invalid object key")
        path = (self.root / key).resolve()
        if path.parent != self.root:
            raise ValueError("Object outside storage")
        return path

    def put(self, data):
        key = secrets.token_hex(32)
        path = self.path(key)
        with path.open("xb") as stream:
            stream.write(data)
        return key

    def get(self, key):
        return self.path(key).read_bytes()

    def delete(self, key):
        self.path(key).unlink(missing_ok=True)

    def metadata(self, key):
        data = self.get(key)
        return {"size": len(data), "content_hash": hashlib.sha256(data).hexdigest()}

    def health(self):
        return self.root.is_dir()


class SupabaseStorage:
    """Production object storage adapter for Supabase Storage (Phase 10 boundary).
    Stores objects in the Supabase documents bucket via authenticated REST API.
    """

    def __init__(self, bucket_name: str | None = None):
        self.bucket_name = bucket_name or settings().supabase_storage_bucket
        self.url = settings().supabase_url.rstrip("/")
        self.key = settings().supabase_service_role_key

    def _headers(self, content_type: str = "application/octet-stream"):
        return {
            "Authorization": f"Bearer {self.key}",
            "apikey": self.key,
            "Content-Type": content_type,
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

    def put(self, data: bytes) -> str:
        key = secrets.token_hex(32)
        target_url = f"{self.url}/storage/v1/object/{self.bucket_name}/{key}"
        res = httpx.post(target_url, headers=self._headers(), content=data, timeout=20)
        if res.status_code not in (200, 201):
            raise HTTPException(502, "Private storage upload failed. Please retry.")
        return key

    def get(self, key: str) -> bytes:
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ValueError("Invalid object key")
        target_url = f"{self.url}/storage/v1/object/{self.bucket_name}/{key}"
        res = httpx.get(
            target_url,
            params={"t": int(time.time() * 1000)},
            headers=self._headers(),
            timeout=20,
        )
        if res.status_code == 404 or (
            res.status_code == 400
            and any(w in res.text.lower() for w in ["not_found", "nosuchkey"])
        ):
            raise KeyError(f"Object not found: {key}")
        if res.status_code != 200:
            raise HTTPException(502, "Private storage download failed. Please retry.")
        return res.content

    def delete(self, key: str):
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ValueError("Invalid object key")
        target_url = f"{self.url}/storage/v1/object/{self.bucket_name}/{key}"
        response = httpx.delete(target_url, headers=self._headers(), timeout=10)
        if response.status_code not in {200, 204, 404}:
            raise HTTPException(
                502, "Private storage deletion failed; retry before considering this file deleted."
            )

    def metadata(self, key: str) -> dict:
        data = self.get(key)
        return {"size": len(data), "content_hash": hashlib.sha256(data).hexdigest()}

    def health(self) -> bool:
        if not self.url or not self.key:
            return False
        try:
            res = httpx.get(
                f"{self.url}/storage/v1/bucket/{self.bucket_name}",
                headers={"Authorization": f"Bearer {self.key}", "apikey": self.key},
                timeout=5,
            )
            return res.status_code == 200 and res.json().get("public") is False
        except Exception:
            return False


def get_storage() -> ObjectStorage:
    if settings().storage_provider == "supabase":
        return SupabaseStorage()
    return LocalStorage()


def validate_upload(data, filename):
    if not data or len(data) > settings().max_upload_bytes:
        raise HTTPException(413, "File is empty or exceeds the upload limit.")
    if any(c in filename for c in ("/", "\\", "\x00")) or filename in {".", ".."}:
        raise HTTPException(422, "Unsafe filename.")
    if data.startswith(b"%PDF-"):
        if re.search(rb"/(JavaScript|JS|Launch|EmbeddedFile|OpenAction|AA|RichMedia)\b", data):
            raise HTTPException(
                422, "PDF contains active content. Export a flattened PDF and retry."
            )
        return "application/pdf"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            415, "Supported formats: non-active PDF and UTF-8 plain text."
        ) from None
    if b"\x00" in data or re.search(r"<\s*(?:html|script|svg|iframe|!doctype)|^#!|MZ", text, re.I):
        raise HTTPException(415, "Executable or active markup is not supported.")
    return "text/plain"


def process_document(storage, doc):
    if not settings().document_processing_enabled:
        raise RuntimeError(
            "Document processing is temporarily disabled; document remains quarantined"
        )
    data = storage.get(doc.object_key)
    if hashlib.sha256(data).hexdigest() != doc.content_hash:
        raise ValueError("Stored file checksum mismatch")
    command = settings().malware_command
    if command:
        # Scanner runs on bounded private temporary bytes, independent of storage provider.
        with tempfile.TemporaryDirectory(prefix="orqelis-scan-") as directory:
            path = Path(directory) / "upload.bin"
            path.write_bytes(data)
            result = subprocess.run(
                [*shlex.split(command), str(path)],
                shell=False,
                capture_output=True,
                timeout=60,
            )
        if result.returncode == 1:
            doc.status = "REJECTED"
            return
        if result.returncode != 0:
            raise RuntimeError("Malware scanner unavailable; document remains quarantined")
    elif settings().environment == "production":
        raise RuntimeError("Malware scanner required")
    if doc.mime == "application/pdf":
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted or len(reader.pages) > 150:
            raise ValueError("Encrypted or over-150-page PDF unsupported")
        # Check parsed object graph as well as raw bytes (compressed actions included).
        visited = set()

        def inspect(obj, depth=0):
            if depth > 50:
                raise ValueError("PDF object nesting limit exceeded")
            if hasattr(obj, "get_object"):
                obj = obj.get_object()
            if id(obj) in visited:
                return
            visited.add(id(obj))
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if str(key) in {
                        "/JS",
                        "/JavaScript",
                        "/Launch",
                        "/EmbeddedFiles",
                        "/OpenAction",
                        "/AA",
                        "/RichMedia",
                    }:
                        raise ValueError("Active PDF content rejected")
                    inspect(value, depth + 1)
            elif isinstance(obj, list):
                for value in obj:
                    inspect(value, depth + 1)

        inspect(reader.trailer)
        pages = []
        for i, page in enumerate(reader.pages):
            stream = page.get_contents()
            if stream and len(stream.get_data()) > 5 * 1024 * 1024:
                raise ValueError("PDF page decompression limit exceeded")
            pages.append(f"[Page {i + 1}]\n" + (page.extract_text() or "")[:50000])
        doc.text = "\n".join(pages)[:500000]
    else:
        doc.text = "[Section 1]\n" + data.decode("utf-8")[:500000]
    doc.status = "READY" if doc.text.strip() else "REVIEW_REQUIRED"

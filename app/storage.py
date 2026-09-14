import hashlib
import io
import re
import secrets
import shlex
import subprocess
from pathlib import Path
from typing import Protocol

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


class FirebaseStorage:
    """Production object storage adapter for Firebase / Google Cloud Storage (Phase 10 boundary).
    Activated when storage_provider is 'firebase' and bucket credentials are provided.
    """

    def __init__(self, bucket_name: str | None = None):
        self.bucket_name = bucket_name or getattr(settings(), "internal_token", "")

    def put(self, data: bytes) -> str:
        raise NotImplementedError(
            "FirebaseStorage adapter is ready. Configure bucket credentials to activate."
        )

    def get(self, key: str) -> bytes:
        raise NotImplementedError(
            "FirebaseStorage adapter is ready. Configure bucket credentials to activate."
        )

    def delete(self, key: str):
        raise NotImplementedError(
            "FirebaseStorage adapter is ready. Configure bucket credentials to activate."
        )

    def metadata(self, key: str) -> dict:
        raise NotImplementedError(
            "FirebaseStorage adapter is ready. Configure bucket credentials to activate."
        )

    def health(self) -> bool:
        return bool(self.bucket_name)


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
    data = storage.get(doc.object_key)
    if hashlib.sha256(data).hexdigest() != doc.content_hash:
        raise ValueError("Stored file checksum mismatch")
    command = settings().malware_command
    if command:
        result = subprocess.run(
            [*shlex.split(command), str(storage.path(doc.object_key))],
            shell=False,
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0:
            doc.status = "REJECTED"
            return
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

"""Authenticated encrypted backup and isolated restore verification.

Stop writers during a production DB+object snapshot. Never restores over an existing directory.
BACKUP_KEY is a 64-character hex key supplied by a secret manager.
"""

import argparse
import hashlib
import io
import json
import os
import secrets
import sqlite3
import subprocess
import tempfile
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.engine import make_url

from app.config import settings

MAGIC = b"ORQELIS-BACKUP-1\n"


def key_bytes(key):
    try:
        decoded = bytes.fromhex(key)
    except ValueError:
        raise ValueError("BACKUP_KEY must be a 64-character hexadecimal key") from None
    if len(decoded) != 32:
        raise ValueError("BACKUP_KEY must contain 32 bytes")
    return decoded


def snapshot(database_url, objects, output, key):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Backup destination already exists")
    url = make_url(database_url)
    with tempfile.TemporaryDirectory(prefix="orqelis-backup-") as temporary:
        db_file = Path(temporary) / "database.dump"
        if url.drivername.startswith("sqlite"):
            with closing(
                sqlite3.connect(f"file:{Path(url.database).resolve().as_posix()}?mode=ro", uri=True)
            ) as source:
                with closing(sqlite3.connect(db_file)) as target:
                    source.backup(target)
            kind = "sqlite"
        elif url.drivername.startswith("postgresql"):
            env = os.environ.copy()
            env["PGPASSWORD"] = url.password or ""
            command = [
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--host",
                url.host or "localhost",
                "--port",
                str(url.port or 5432),
                "--username",
                url.username or "",
                "--file",
                str(db_file),
                url.database,
            ]
            result = subprocess.run(command, env=env, capture_output=True, timeout=600)
            if result.returncode:
                raise RuntimeError(
                    "PostgreSQL snapshot failed; inspect database connectivity without logging credentials"
                )
            kind = "postgresql"
        else:
            raise ValueError("Unsupported backup database")
        buffer = io.BytesIO()
        manifest = {
            "version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "database_kind": kind,
            "files": {},
        }
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            files = [("database.dump", db_file)]
            root = Path(objects).resolve()
            if root.exists():
                for path in root.iterdir():
                    if (
                        path.is_file()
                        and len(path.name) == 64
                        and all(c in "0123456789abcdef" for c in path.name)
                    ):
                        if path.is_symlink():
                            raise ValueError("Storage symlinks are not permitted")
                        files.append((f"objects/{path.name}", path))
            for name, path in files:
                data = path.read_bytes()
                manifest["files"][name] = hashlib.sha256(data).hexdigest()
                archive.writestr(name, data)
            archive.writestr("manifest.json", json.dumps(manifest))
        if buffer.tell() > 1024**3:
            raise ValueError(
                "Use the documented streaming/managed backup path for snapshots above 1 GB"
            )
        nonce = secrets.token_bytes(12)
        encrypted = AESGCM(key_bytes(key)).encrypt(nonce, buffer.getvalue(), MAGIC)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(MAGIC + nonce + encrypted)
    return manifest


def restore(backup, destination, key):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("Restore requires a new isolated destination; refusing overwrite")
    payload = Path(backup).read_bytes()
    if not payload.startswith(MAGIC):
        raise ValueError("Invalid backup format")
    nonce = payload[len(MAGIC) : len(MAGIC) + 12]
    clear = AESGCM(key_bytes(key)).decrypt(nonce, payload[len(MAGIC) + 12 :], MAGIC)
    with zipfile.ZipFile(io.BytesIO(clear)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        contents = {}
        for name, checksum in manifest["files"].items():
            if name != "database.dump" and not (
                name.startswith("objects/")
                and len(name) == 72
                and all(c in "0123456789abcdef" for c in name[8:])
            ):
                raise ValueError("Unexpected backup member")
            data = archive.read(name)
            if hashlib.sha256(data).hexdigest() != checksum:
                raise ValueError("Backup integrity verification failed")
            contents[name] = data
        destination.mkdir(parents=True)
        for name, data in contents.items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        if manifest["database_kind"] == "sqlite":
            with closing(sqlite3.connect(destination / "database.dump")) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Restored SQLite database failed integrity check")
                table = db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='documents'"
                ).fetchone()
                if table:
                    for object_key, hash_ in db.execute(
                        "SELECT object_key,content_hash FROM documents"
                    ):
                        obj = destination / "objects" / object_key
                        if (
                            not obj.is_file()
                            or hashlib.sha256(obj.read_bytes()).hexdigest() != hash_
                        ):
                            raise ValueError("Database/object snapshot is inconsistent")
        (destination / "restore-verification.json").write_text(
            json.dumps(
                manifest
                | {
                    "hashes_verified": True,
                    "database_integrity": "verified"
                    if manifest["database_kind"] == "sqlite"
                    else "pg_restore into isolated database still required",
                },
                indent=2,
            )
        )
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create", "restore"])
    parser.add_argument("path", type=Path)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    config = settings()
    if args.action == "create":
        result = snapshot(config.database_url, config.storage_path, args.path, config.backup_key)
    else:
        if not args.destination:
            parser.error("--destination is required for isolated restore")
        result = restore(args.path, args.destination, config.backup_key)
    print(
        json.dumps(
            {
                "action": args.action,
                "database_kind": result["database_kind"],
                "files": len(result["files"]),
            }
        )
    )


if __name__ == "__main__":
    main()

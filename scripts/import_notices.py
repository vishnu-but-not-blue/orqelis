"""Resumable local XML/ZIP/JSON import; never blindly extracts archive paths."""

import argparse
import hashlib
import json
from pathlib import Path

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.ingest import ingest, register_sources
from app.models import SourceRegistry
from app.ted import archive_members, normalize_api, normalize_xml


def import_path(path: Path, factory=SessionLocal):
    path = path.resolve(strict=True)
    if path.stat().st_size > 100 * 1024 * 1024:
        raise ValueError("Split imports into packages smaller than 100 MB")
    payload = path.read_bytes()
    checksum = hashlib.sha256(payload).hexdigest()
    if path.suffix.lower() == ".zip":
        items = archive_members(payload)
    elif path.suffix.lower() == ".xml":
        items = [(path.name, payload)]
    elif path.suffix.lower() == ".json":
        data = json.loads(payload)
        rows = data.get("notices", []) if isinstance(data, dict) else data
        items = [(f"{i}.json", json.dumps(row).encode()) for i, row in enumerate(rows)]
    else:
        raise ValueError("Expected XML, ZIP or official TED Search JSON")
    imported = 0
    with factory() as db:
        source = db.scalar(select(SourceRegistry).where(SourceRegistry.name == "TED"))
        if not source or not source.enabled:
            raise ValueError("TED source is disabled or unregistered")
        checkpoint = dict(source.checkpoint or {})
        completed = checkpoint.get("bulk", {}).get(checksum, -1)
        for index, (name, raw) in enumerate(items):
            if index <= completed:
                continue
            normalized = (
                normalize_api(json.loads(raw)) if name.endswith(".json") else normalize_xml(raw)
            )
            _, created = ingest(db, normalized, raw)
            imported += int(created)
            checkpoint["bulk"] = dict(checkpoint.get("bulk", {})) | {checksum: index}
            source.checkpoint = dict(checkpoint)
            db.commit()
    return imported


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        register_sources(db)
    print(json.dumps({"imported": import_path(args.path)}))


if __name__ == "__main__":
    main()

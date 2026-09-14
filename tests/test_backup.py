import secrets
import sqlite3

import pytest
from cryptography.exceptions import InvalidTag

from scripts.backup import restore, snapshot


def test_encrypted_backup_restores_database_and_objects(tmp_path):
    db = tmp_path / "source.db"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE proof (value TEXT)")
        connection.execute("INSERT INTO proof VALUES ('private-content')")
    objects = tmp_path / "objects"
    objects.mkdir()
    (objects / ("a" * 64)).write_bytes(b"evidence-content")
    backup = tmp_path / "snapshot.enc"
    key = secrets.token_hex(32)
    snapshot(f"sqlite:///{db}", objects, backup, key)
    assert b"private-content" not in backup.read_bytes()
    destination = tmp_path / "restored"
    restore(backup, destination, key)
    with sqlite3.connect(destination / "database.dump") as connection:
        assert connection.execute("SELECT value FROM proof").fetchone()[0] == "private-content"
    assert (destination / "objects" / ("a" * 64)).read_bytes() == b"evidence-content"
    with pytest.raises(ValueError, match="refusing overwrite"):
        restore(backup, destination, key)
    with pytest.raises(InvalidTag):
        restore(backup, tmp_path / "wrong-key", secrets.token_hex(32))


def test_backup_tampering_is_detected(tmp_path):
    db = tmp_path / "source.db"
    sqlite3.connect(db).close()
    key = secrets.token_hex(32)
    archive = tmp_path / "backup.enc"
    snapshot(f"sqlite:///{db}", tmp_path / "objects", archive, key)
    payload = bytearray(archive.read_bytes())
    payload[-1] ^= 1
    archive.write_bytes(payload)
    with pytest.raises(InvalidTag):
        restore(archive, tmp_path / "restore", key)

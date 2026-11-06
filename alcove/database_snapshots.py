"""Operational snapshots of the entire local SQLite database."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from django.conf import settings


class SnapshotError(Exception):
    pass


def backup_database(destination: Path) -> None:
    """Back up committed state before acquiring any write lock for a restore."""
    _snapshot(_database_path(), destination)


def restore_database(source: Path) -> None:
    """Install a backup into an unused database path with the server stopped."""
    _snapshot(source, _database_path())


def _database_path() -> Path:
    name = settings.DATABASES["default"]["NAME"]
    if not isinstance(name, (str, Path)) or not name or name == ":memory:":
        raise SnapshotError("Configure an on-disk SQLite database.")
    return Path(name)


def _snapshot(source: Path, destination: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = Path(f"{destination}{suffix}")
        if path.exists() or path.is_symlink():
            raise SnapshotError(f"Destination already exists: {path}")

    try:
        with TemporaryDirectory(
            prefix=".alcove-snapshot-", dir=destination.parent
        ) as directory:
            snapshot = Path(directory) / "database.sqlite3"
            source_uri = source.absolute().as_uri() + "?mode=ro"
            with (
                closing(sqlite3.connect(source_uri, uri=True)) as original,
                closing(sqlite3.connect(snapshot)) as copy,
            ):
                deadline = monotonic() + 5

                def check_lock(status: int, remaining: int, total: int) -> None:
                    if (
                        status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
                        and monotonic() >= deadline
                    ):
                        raise SnapshotError("SQLite database is locked.")

                original.backup(copy, progress=check_lock)
                copy.execute("PRAGMA journal_mode=DELETE").fetchone()
                copy.execute("SELECT 1 FROM alcove_collection LIMIT 0")
                if copy.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise SnapshotError("SQLite integrity check failed.")

            snapshot.chmod(0o600)
            # Publish a complete file in one step and never replace a destination.
            os.link(snapshot, destination)
    except (OSError, sqlite3.Error) as exc:
        raise SnapshotError(str(exc)) from exc

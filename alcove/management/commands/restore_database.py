from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from alcove.database_snapshots import SnapshotError, restore_database


class Command(BaseCommand):
    help = "Restore a SQLite backup to an unused database path with the server stopped."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("source", type=Path)

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            restore_database(options["source"])
        except SnapshotError as exc:
            raise CommandError(f"Restore failed: {exc}") from exc
        self.stdout.write("Database restored. Start Alcove to apply any migrations.")

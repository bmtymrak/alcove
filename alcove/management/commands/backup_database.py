from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from alcove.database_snapshots import SnapshotError, backup_database


class Command(BaseCommand):
    help = "Write a consistent SQLite backup to a new file."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("destination", type=Path)

    def handle(self, *args: Any, **options: Any) -> None:
        destination = options["destination"]
        try:
            backup_database(destination)
        except SnapshotError as exc:
            raise CommandError(f"Backup failed: {exc}") from exc
        self.stdout.write(f"Database backup written to {destination}.")

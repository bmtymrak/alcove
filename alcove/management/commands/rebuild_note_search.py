from typing import Any

from django.core.management.base import BaseCommand

from alcove import note_search


class Command(BaseCommand):
    help = "Rebuild the SQLite Note search index from the current Collection records."

    def handle(self, *args: Any, **options: Any) -> None:
        note_search.rebuild()
        self.stdout.write("Note search index rebuilt.")

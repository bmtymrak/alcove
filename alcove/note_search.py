"""Full-text queries over the derived SQLite Note search index."""

from itertools import groupby
from unicodedata import category

from django.db import connection, transaction
from django.db.models import QuerySet
from django.db.models.expressions import RawSQL

from .models import Note


def _word_character(character: str) -> bool:
    kind = category(character)
    return kind[0] in "LNM" or kind == "Co"


def matching_notes(results: QuerySet[Note], query: str) -> QuerySet[Note]:
    if not query.strip():
        return results
    # Match whole words. Quoting each term keeps FTS operators and wildcards
    # out of the query language, and the column filter excludes internal IDs.
    terms = [
        f'"{"".join(run)}"' for word, run in groupby(query, _word_character) if word
    ]
    if not terms:
        return results.none()
    pattern = "document : (" + " ".join(terms) + ")"
    return results.filter(
        pk__in=RawSQL(
            "SELECT note_id FROM alcove_note_search WHERE alcove_note_search MATCH %s",
            (pattern,),
        )
    )


@transaction.atomic
def rebuild() -> None:
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM alcove_note_search")
        cursor.execute(
            "INSERT INTO alcove_note_search (note_id, document) "
            "SELECT note_id, document FROM alcove_note_search_documents"
        )

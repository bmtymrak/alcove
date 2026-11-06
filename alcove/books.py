from uuid import UUID

from django.db import transaction
from django.db.models import F
from django.http import Http404
from django.utils import timezone

from . import reading
from .errors import NoteError
from .models import Book, Collection, Note

MAX_METADATA_LENGTH = 300


def validated_metadata(value: str, field: str) -> str:
    value = value.strip()
    if (
        (field == "title" and not value)
        or len(value) > MAX_METADATA_LENGTH
        or "\x00" in value
    ):
        raise NoteError(
            "Invalid Book metadata.",
            fields={
                field: [
                    "Use 1–300 characters for a title, or up to 300 for an author, "
                    "without null characters."
                ]
            },
        )
    return value


def create(collection: Collection, title: str, author: str = "") -> Book:
    return Book.objects.create(
        collection=collection,
        title=validated_metadata(title, "title"),
        author=validated_metadata(author, "author"),
    )


def edit(
    collection: Collection,
    book_id: UUID,
    *,
    title: str | None = None,
    author: str | None = None,
) -> Book:
    fields = {
        key: validated_metadata(value, key)
        for key, value in {"title": title, "author": author}.items()
        if value is not None
    }
    Book.objects.filter(collection=collection, pk=book_id).update(**fields)
    return reading.book(collection, book_id)


def lock_for_write(collection: Collection, book_id: UUID) -> None:
    # Acquire SQLite's write lock before reading the Book's dependent records.
    if not Book.objects.filter(collection=collection, pk=book_id).update(
        title=F("title")
    ):
        raise Http404("Book not found.")


@transaction.atomic
def remove(collection: Collection, book_id: UUID) -> None:
    lock_for_write(collection, book_id)
    Note.objects.filter(collection=collection, book_id=book_id).update(
        book=None,
        chapter=None,
        revision=F("revision") + 1,
        updated_at=timezone.now(),
    )
    Book.objects.filter(collection=collection, pk=book_id).delete()

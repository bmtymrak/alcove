from uuid import UUID

from . import reading
from .models import Book, Collection
from .notes import NoteError

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

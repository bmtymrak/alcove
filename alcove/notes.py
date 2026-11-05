from enum import Enum
from typing import Any
from uuid import UUID

from django.db import transaction
from django.http import Http404
from django.utils import timezone

from . import note_content, reading
from .models import Collection, Note

MAX_CONTENT_LENGTH = note_content.MAX_CONTENT_LENGTH
# Leave room for the increment in SQLite's signed 64-bit integer storage.
MAX_EXPECTED_REVISION = 2**63 - 2


class NoteError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid",
        status: int = 400,
        fields: dict[str, list[str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.fields = fields or {}


def plain_text_content(text: str) -> dict[str, Any]:
    return {"version": 1, "format": "plain-text", "text": text}


def validated_content(value: Any) -> tuple[dict[str, Any], str]:
    try:
        return note_content.validate(value)
    except note_content.InvalidContent as exc:
        raise NoteError(str(exc), fields={"content": [str(exc)]}) from exc


class SourceChange(Enum):
    UNCHANGED = "unchanged"


def validated_book(collection: Collection, book_id: UUID | None) -> UUID | None:
    if book_id is not None:
        try:
            reading.book(collection, book_id)
        except Http404 as exc:
            raise NoteError(
                "Choose a Book from your Collection.",
                fields={"book": ["Choose a Book from your Collection."]},
            ) from exc
    return book_id


def capture(collection: Collection, content: Any, book: UUID | None = None) -> Note:
    document, text = validated_content(content)
    book_id = validated_book(collection, book)
    return Note.objects.create(
        collection=collection,
        book_id=book_id,
        content=document,
        plain_text=text,
    )


def edit(
    collection: Collection,
    note_id: UUID,
    content: Any,
    revision: int,
    book: UUID | None | SourceChange = SourceChange.UNCHANGED,
) -> Note:
    if type(revision) is not int or not 1 <= revision <= MAX_EXPECTED_REVISION:
        raise NoteError(
            "Invalid revision.",
            fields={
                "revision": [f"Use a revision between 1 and {MAX_EXPECTED_REVISION}."],
            },
        )
    changes: dict[str, Any] = {
        "revision": revision + 1,
        "updated_at": timezone.now(),
    }
    if content is not None:
        document, text = validated_content(content)
        changes.update(content=document, plain_text=text)
    if not isinstance(book, SourceChange):
        changes["book_id"] = validated_book(collection, book)
    # Validate references before the transaction so the first transactional
    # database operation takes SQLite's write lock, including for source edits.
    with transaction.atomic():
        changed = Note.objects.filter(
            collection=collection,
            pk=note_id,
            revision=revision,
        ).update(**changes)
        note = reading.note(collection, note_id)
        if not changed:
            raise NoteError(
                "This Note changed elsewhere. Your text has not been saved. "
                "Open the current Note before trying again.",
                code="conflict",
                status=409,
            )
        return note

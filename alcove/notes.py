from typing import Any, TypedDict
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from . import reading
from .models import Collection, Note

MAX_CONTENT_LENGTH = 100_000
# Leave room for the increment in SQLite's signed 64-bit integer storage.
MAX_EXPECTED_REVISION = 2**63 - 2


class Content(TypedDict):
    version: int
    format: str
    text: str


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


def plain_text_content(text: str) -> Content:
    return {"version": 1, "format": "plain-text", "text": text}


def validated_content(value: Any) -> Content:
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "format", "text"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or value["format"] != "plain-text"
        or not isinstance(value["text"], str)
    ):
        raise NoteError(
            "Unsupported content.",
            fields={
                "content": ["Use a version 1 plain-text document with a text string."],
            },
        )
    text = value["text"]
    if not text.strip():
        raise NoteError(
            "Write something before saving.",
            fields={
                "content": ["Write something before saving."],
            },
        )
    if len(text) > MAX_CONTENT_LENGTH or "\x00" in text:
        raise NoteError(
            "Invalid content.",
            fields={
                "content": ["Use at most 100,000 characters without null characters."],
            },
        )
    return plain_text_content(text)


def capture(collection: Collection, content: Any) -> Note:
    document = validated_content(content)
    return Note.objects.create(
        collection=collection,
        content=document,
        plain_text=document["text"],
    )


@transaction.atomic
def edit(collection: Collection, note_id: UUID, content: Any, revision: int) -> Note:
    if type(revision) is not int or not 1 <= revision <= MAX_EXPECTED_REVISION:
        raise NoteError(
            "Invalid revision.",
            fields={
                "revision": [f"Use a revision between 1 and {MAX_EXPECTED_REVISION}."],
            },
        )
    document = validated_content(content)
    # Take the SQLite write lock before reading inside this transaction. A
    # deferred read-then-write upgrade can fail immediately under concurrent saves.
    changed = Note.objects.filter(
        collection=collection,
        pk=note_id,
        revision=revision,
    ).update(
        content=document,
        plain_text=document["text"],
        revision=revision + 1,
        updated_at=timezone.now(),
    )
    note = reading.note(collection, note_id)
    if not changed:
        raise NoteError(
            "This Note changed elsewhere. Your text has not been saved. "
            "Open the current Note before trying again.",
            code="conflict",
            status=409,
        )
    return note

import json
from collections.abc import Sequence
from enum import Enum
from hashlib import sha256
from typing import Any, Literal
from uuid import UUID

from django.db import transaction
from django.db.models import Case, F, When
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from . import note_content, reading, topics
from .errors import NoteError as NoteError
from .models import Chapter, Collection, Note, NoteLink, RetiredCapture

MAX_CONTENT_LENGTH = note_content.MAX_CONTENT_LENGTH
# Leave room for the increment in SQLite's signed 64-bit integer storage.
MAX_EXPECTED_REVISION = 2**63 - 2
MAX_PAGE_NUMBER = 2**31 - 1


class NoteConflict(NoteError):
    def __init__(self, current_revision: int) -> None:
        super().__init__(
            "This Note changed elsewhere. Your text has not been saved. "
            "Review the current Note before trying again.",
            code="conflict",
            status=409,
        )
        self.current_revision = current_revision


def _unavailable_capture_error() -> NoteError:
    return NoteError(
        "This capture belongs to a Note that was moved to trash or deleted.",
        code="capture_conflict",
        status=409,
    )


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


def validated_chapter(
    collection: Collection, book_id: UUID | None, chapter_id: UUID | None
) -> UUID | None:
    if chapter_id is not None and (
        book_id is None
        or not Chapter.objects.filter(
            pk=chapter_id, book_id=book_id, book__collection=collection
        ).exists()
    ):
        message = "Choose a Chapter from the selected Book."
        raise NoteError(message, fields={"chapter": [message]})
    return chapter_id


def validated_page_number(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 1 <= value <= MAX_PAGE_NUMBER:
        message = f"Enter a whole Page Number from 1 to {MAX_PAGE_NUMBER}."
        raise NoteError(message, fields={"page_number": [message]})
    return value


def validated_source_reference(value: Any) -> str:
    if not note_content.valid_string(value):
        message = "Enter a valid text Source Reference."
        raise NoteError(message, fields={"source_reference": [message]})
    return value.replace("\r\n", "\n").replace("\r", "\n")


@transaction.atomic
def set_trashed(collection: Collection, note_id: UUID, *, trashed: bool) -> None:
    owned = Note.objects.filter(collection=collection, pk=note_id)
    now = timezone.now()
    # Moving to trash requires a null timestamp. Restoring requires a set one.
    if owned.filter(trashed_at__isnull=trashed).update(
        trashed_at=now if trashed else None, updated_at=now, revision=F("revision") + 1
    ):
        return
    if not owned.exists():
        raise Http404("Note not found.")
    message = "This Note is already in trash." if trashed else "This Note is active."
    raise NoteError(message, code="invalid_note_state", status=409)


def require_trashed_note(collection: Collection, note_id: UUID) -> Note:
    note = get_object_or_404(Note, collection=collection, pk=note_id)
    if note.trashed_at is None:
        raise NoteError(
            "Move this Note to trash before deleting it permanently.",
            code="invalid_note_state",
            status=409,
        )
    return note


def deletion_confirmation(note: Note) -> str:
    return salted_hmac(
        "alcove.note-deletion", f"{note.id}:{note.revision}", algorithm="sha256"
    ).hexdigest()


@transaction.atomic
def delete_permanently(
    collection: Collection, note_id: UUID, *, confirmation: str | None = None
) -> None:
    # Serialize the state check, cascades, and capture retirement with writes.
    Collection.objects.filter(pk=collection.pk).update(id=F("id"))
    note = require_trashed_note(collection, note_id)
    if confirmation is not None and not constant_time_compare(
        confirmation, deletion_confirmation(note)
    ):
        raise NoteError(
            "This Note changed after you opened it.",
            code="stale_preview",
            status=409,
        )
    if note.capture_id is not None:
        # A delayed capture retry must not recreate the deleted Note.
        RetiredCapture.objects.create(collection=collection, capture_id=note.capture_id)
    note.delete()


@transaction.atomic
def change_link(
    collection: Collection,
    note_id: UUID,
    related_note: UUID,
    *,
    action: Literal["add", "remove"],
) -> None:
    # Take the SQLite write lock before validating endpoints and mutating the pair.
    Collection.objects.filter(pk=collection.pk).update(id=F("id"))
    owned_ids = set(
        reading.active_notes(collection)
        .filter(pk__in=(note_id, related_note))
        .values_list("pk", flat=True)
    )
    if note_id not in owned_ids:
        raise Http404("Note not found.")

    first, second = sorted((note_id, related_note))
    if action == "remove":
        if (
            related_note not in owned_ids
            or not NoteLink.objects.filter(
                first_note_id=first, second_note_id=second
            ).delete()[0]
        ):
            raise Http404("Note Link not found.")
        return

    if note_id == related_note:
        message = "Choose a different Note."
        raise NoteError(message, code="self_link", fields={"related_note": [message]})
    if related_note not in owned_ids:
        message = "Choose a Note from your Collection."
        raise NoteError(message, fields={"related_note": [message]})
    _, created = NoteLink.objects.get_or_create(
        first_note_id=first, second_note_id=second
    )
    if not created:
        message = "These Notes are already linked."
        raise NoteError(
            message,
            code="duplicate_link",
            status=409,
            fields={"related_note": [message]},
        )


@transaction.atomic
def capture(
    collection: Collection,
    content: Any,
    book: UUID | None = None,
    capture_id: UUID | None = None,
    *,
    chapter: UUID | None = None,
    page_number: int | None = None,
    source_reference: str = "",
    topic_changes: Sequence[topics.AssignmentChange] = (),
) -> tuple[Note, bool]:
    document, text = validated_content(content)
    page_number = validated_page_number(page_number)
    source_reference = validated_source_reference(source_reference)
    fields = {
        "content": document,
        "plain_text": text,
        "page_number": page_number,
        "source_reference": source_reference,
    }
    # Take SQLite's write lock before looking up a prior capture. Its Note and
    # Topic Assignments must either be created together or both roll back.
    Collection.objects.filter(pk=collection.pk).update(id=F("id"))
    # Compare against the original input, even if the saved Note has been edited.
    original_fields: list[object] = [str(book) if book else None, document]
    # Preserve fingerprints for captures made before these fields existed.
    if page_number is not None or source_reference:
        original_fields.extend([page_number, source_reference])
    if chapter is not None:
        original_fields.append({"chapter": str(chapter)})
    if topic_changes:
        original_fields.append(
            {
                "topic_changes": [
                    {"action": change.action, "topic": str(change.topic)}
                    for change in topic_changes
                ]
            }
        )
    original_input = json.dumps(original_fields, sort_keys=True)
    fingerprint = sha256(original_input.encode()).hexdigest()
    if capture_id is not None:
        prior = Note.objects.filter(
            collection=collection, capture_id=capture_id
        ).first()
        if prior is not None:
            if prior.capture_fingerprint != fingerprint:
                raise NoteError(
                    "This capture identity was already used for different input.",
                    code="capture_conflict",
                    status=409,
                )
            if prior.trashed_at is not None:
                raise _unavailable_capture_error()
            reading.load_topics(collection, [prior])
            return prior, False
        if RetiredCapture.objects.filter(
            collection=collection, capture_id=capture_id
        ).exists():
            raise _unavailable_capture_error()

    book_id = validated_book(collection, book)
    note = Note.objects.create(
        collection=collection,
        book_id=book_id,
        chapter_id=validated_chapter(collection, book_id, chapter),
        capture_id=capture_id,
        capture_fingerprint=fingerprint if capture_id is not None else "",
        **fields,
    )
    topics.apply_assignment_changes(note, topic_changes)
    reading.load_topics(collection, [note])
    return note, True


def edit(
    collection: Collection,
    note_id: UUID,
    *,
    revision: int,
    content: Any = None,
    book: UUID | None | SourceChange = SourceChange.UNCHANGED,
    chapter: UUID | None | SourceChange = SourceChange.UNCHANGED,
    page_number: int | None | SourceChange = SourceChange.UNCHANGED,
    source_reference: str | SourceChange = SourceChange.UNCHANGED,
    topic_changes: Sequence[topics.AssignmentChange] = (),
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
        if isinstance(chapter, SourceChange):
            # Keep the Chapter only when the source Book is unchanged.
            changes["chapter_id"] = Case(When(book_id=book, then=F("chapter_id")))
    if not isinstance(chapter, SourceChange):
        book_id = None
        if not isinstance(book, SourceChange):
            book_id = book
        elif chapter is not None:
            current = reading.note(collection, note_id)
            if current.revision != revision:
                raise NoteConflict(current.revision)
            book_id = current.book_id
        changes["chapter_id"] = validated_chapter(collection, book_id, chapter)
    if not isinstance(page_number, SourceChange):
        changes["page_number"] = validated_page_number(page_number)
    if not isinstance(source_reference, SourceChange):
        changes["source_reference"] = validated_source_reference(source_reference)
    # Validate references before the transaction so the first transactional
    # database operation takes SQLite's write lock, including for source edits.
    with transaction.atomic():
        changed = (
            reading.active_notes(collection)
            .filter(
                pk=note_id,
                revision=revision,
            )
            .update(**changes)
        )
        note = reading.note(collection, note_id)
        if not changed:
            raise NoteConflict(note.revision)
        topics.apply_assignment_changes(note, topic_changes)
        reading.load_topics(collection, [note])
        return note

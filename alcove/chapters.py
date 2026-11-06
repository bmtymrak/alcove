from uuid import UUID

from django.db import transaction
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404

from . import note_content
from .models import Book, Chapter, Collection
from .notes import NoteError

MAX_LABEL_LENGTH = 300


def validated_label(value: str) -> str:
    value = value.strip()
    if (
        not value
        or len(value) > MAX_LABEL_LENGTH
        or not note_content.valid_string(value)
    ):
        message = f"Enter a Chapter label of 1–{MAX_LABEL_LENGTH} characters."
        raise NoteError(message, fields={"label": [message]})
    return value


def lock_book(collection: Collection, book_id: UUID) -> None:
    # Acquire SQLite's write lock before reading positions. Append and move
    # transactions then operate on the latest complete sequence.
    if not Book.objects.filter(collection=collection, pk=book_id).update(
        title=F("title")
    ):
        raise Http404("Book not found.")


@transaction.atomic
def create(collection: Collection, book_id: UUID, label: str) -> Chapter:
    lock_book(collection, book_id)
    return Chapter.objects.create(
        book_id=book_id,
        label=validated_label(label),
        position=Chapter.objects.filter(book_id=book_id).count() + 1,
    )


@transaction.atomic
def edit(
    collection: Collection,
    book_id: UUID,
    chapter_id: UUID,
    *,
    label: str | None = None,
    position: int | None = None,
) -> Chapter:
    lock_book(collection, book_id)
    sequence = Chapter.objects.filter(book_id=book_id)
    chapter = get_object_or_404(sequence, pk=chapter_id)
    if label is not None:
        chapter.label = validated_label(label)
    if position is not None:
        if not 1 <= position <= sequence.count():
            message = "Choose a position within this Book's Chapter sequence."
            raise NoteError(message, fields={"position": [message]})
        if position < chapter.position:
            sequence.filter(
                position__gte=position, position__lt=chapter.position
            ).update(position=F("position") + 1)
        elif position > chapter.position:
            sequence.filter(
                position__gt=chapter.position, position__lte=position
            ).update(position=F("position") - 1)
        chapter.position = position
    chapter.save(update_fields=["label", "position"])
    return chapter

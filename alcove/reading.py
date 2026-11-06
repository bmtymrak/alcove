from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from django.core.paginator import InvalidPage, Page, Paginator
from django.db import transaction
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404

from . import topics
from .models import Book, Chapter, Collection, Note, TopicAssignment

PAGE_SIZE = 20
CAPTURE_ORDER = ("captured_at", "id")
PAGE_ORDER = (F("page_number").asc(nulls_last=True), *CAPTURE_ORDER)
BOOK_NOTE_ORDERING = {
    "oldest": CAPTURE_ORDER,
    "newest": ("-captured_at", "-id"),
    "page": PAGE_ORDER,
    "chapter": (F("chapter__position").asc(nulls_last=True), *PAGE_ORDER),
}


@transaction.atomic
def notes(collection: Collection, page: int | str = 1) -> Page[Note]:
    try:
        result = Paginator(
            Note.objects.filter(collection=collection).select_related(
                "book", "chapter"
            ),
            PAGE_SIZE,
        ).page(page)
        result.object_list = list(result.object_list)
        load_topics(collection, result.object_list)
        return result
    except InvalidPage as exc:
        raise Http404("Page not found.") from exc


def note(collection: Collection, note_id: UUID) -> Note:
    return get_object_or_404(
        Note.objects.select_related("book", "chapter"),
        collection=collection,
        pk=note_id,
    )


def library(collection: Collection, page: int | str = 1) -> Page[Book]:
    try:
        return Paginator(Book.objects.filter(collection=collection), PAGE_SIZE).page(
            page
        )
    except InvalidPage as exc:
        raise Http404("Page not found.") from exc


def book(collection: Collection, book_id: UUID) -> Book:
    return get_object_or_404(Book, collection=collection, pk=book_id)


def book_chapters(collection: Collection, book_id: UUID) -> list[Chapter]:
    return list(Chapter.objects.filter(book=book(collection, book_id)))


def chapter_options(collection: Collection) -> dict[str, list[dict[str, str | int]]]:
    options: dict[str, list[dict[str, str | int]]] = {}
    for chapter in Chapter.objects.filter(book__collection=collection):
        options.setdefault(str(chapter.book_id), []).append(
            {
                "id": str(chapter.id),
                "label": chapter.label,
                "position": chapter.position,
            }
        )
    return options


def book_options(collection: Collection) -> list[tuple[str, str]]:
    return [
        (str(book.id), f"{book.title} — {book.author}" if book.author else book.title)
        for book in Book.objects.filter(collection=collection)
    ]


@transaction.atomic
def book_notes(
    collection: Collection, book_id: UUID, page: int | str = 1, order: str = "oldest"
) -> Page[Note]:
    book(collection, book_id)
    if order not in BOOK_NOTE_ORDERING:
        raise Http404("Order not found.")
    try:
        result = Paginator(
            Note.objects.filter(collection=collection, book_id=book_id)
            .select_related("book", "chapter")
            .order_by(*BOOK_NOTE_ORDERING[order]),
            PAGE_SIZE,
        ).page(page)
        result.object_list = list(result.object_list)
        load_topics(collection, result.object_list)
        return result
    except InvalidPage as exc:
        raise Http404("Page not found.") from exc


@transaction.atomic
def note_with_topics(collection: Collection, note_id: UUID) -> Note:
    result = note(collection, note_id)
    load_topics(collection, [result])
    return result


def load_topics(collection: Collection, results: Sequence[Note]) -> None:
    assigned: dict[UUID, list[UUID]] = defaultdict(list)
    for note_id, topic_id in TopicAssignment.objects.filter(
        note_id__in=[result.id for result in results], topic__collection=collection
    ).values_list("note_id", "topic_id"):
        assigned[note_id].append(topic_id)

    entries = topics.tree(collection) if assigned else []
    positions = {entry.id: index for index, entry in enumerate(entries)}
    for result in results:
        result.topics = [
            entries[positions[topic_id]]
            for topic_id in sorted(assigned[result.id], key=positions.__getitem__)
        ]

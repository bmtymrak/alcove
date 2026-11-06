from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import groupby
from uuid import UUID

from django.core.paginator import InvalidPage, Page, Paginator
from django.db import transaction
from django.db.models import (
    Exists,
    F,
    FilteredRelation,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
)
from django.http import Http404
from django.shortcuts import get_object_or_404

from . import topics
from .models import Book, Chapter, Collection, Note, Topic, TopicAssignment

PAGE_SIZE = 20
CAPTURE_ORDER = ("captured_at", "id")
PAGE_ORDER = (F("page_number").asc(nulls_last=True), *CAPTURE_ORDER)
BOOK_NOTE_ORDERING = {
    "oldest": CAPTURE_ORDER,
    "newest": ("-captured_at", "-id"),
    "page": PAGE_ORDER,
    "chapter": (F("chapter__position").asc(nulls_last=True), *PAGE_ORDER),
}
TOPIC_MODES = ("branch", "direct")


def _note_page(
    collection: Collection,
    queryset: QuerySet[Note],
    page: int | str,
    entries: Sequence[topics.TopicPath] | None = None,
) -> Page[Note]:
    try:
        result = Paginator(queryset.select_related("book", "chapter"), PAGE_SIZE).page(
            page
        )
    except InvalidPage as exc:
        raise Http404("Page not found.") from exc
    result.object_list = list(result.object_list)
    load_topics(collection, result.object_list, entries)
    return result


@transaction.atomic
def notes(collection: Collection, page: int | str = 1) -> Page[Note]:
    return _note_page(collection, Note.objects.filter(collection=collection), page)


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
    return _note_page(
        collection,
        Note.objects.filter(collection=collection, book_id=book_id).order_by(
            *BOOK_NOTE_ORDERING[order]
        ),
        page,
    )


@dataclass(frozen=True)
class BookNoteGroup:
    topic: topics.TopicPath | None
    notes: list[Note]


@dataclass(frozen=True)
class BookNoteGroups:
    page: Page[tuple[UUID | None, UUID]]
    groups: list[BookNoteGroup]


@transaction.atomic
def book_note_groups(
    collection: Collection, book_id: UUID, page: int | str = 1
) -> BookNoteGroups:
    book(collection, book_id)
    entries = topics.tree(collection)
    by_id = {entry.id: entry for entry in entries}
    ordered = sorted(
        entries, key=lambda entry: (topics.label_key(entry.full_path), entry.id)
    )
    rank: dict[UUID | None, int] = {
        entry.id: index for index, entry in enumerate(ordered)
    }
    rank[None] = len(ordered)

    book_results = Note.objects.filter(collection=collection, book_id=book_id)
    # Sort only placement IDs, then load content for the requested page.
    placements = list(
        book_results.annotate(
            owned_assignment=FilteredRelation(
                "topicassignment",
                condition=Q(
                    topicassignment__topic_id__in=Subquery(
                        Topic.objects.filter(collection=collection).values("id")
                    )
                ),
            )
        )
        .order_by(*CAPTURE_ORDER)
        .values_list("owned_assignment__topic_id", "id")
    )
    placements.sort(key=lambda placement: rank[placement[0]])
    try:
        result = Paginator(placements, PAGE_SIZE).page(page)
    except InvalidPage as exc:
        raise Http404("Page not found.") from exc

    note_ids = {note_id for _, note_id in result}
    page_notes = book_results.select_related("book", "chapter").in_bulk(note_ids)
    load_topics(collection, list(page_notes.values()), entries)
    groups = [
        BookNoteGroup(
            by_id[topic_id] if topic_id is not None else None,
            [page_notes[note_id] for _, note_id in members],
        )
        for topic_id, members in groupby(result, key=lambda placement: placement[0])
    ]
    return BookNoteGroups(result, groups)


@dataclass(frozen=True)
class TopicNotes:
    topic: topics.TopicPath
    tree: list[topics.TopicPath]
    notes: Page[Note]


@transaction.atomic
def topic_notes(
    collection: Collection, topic_id: UUID, page: int | str = 1, mode: str = "branch"
) -> TopicNotes:
    if mode not in TOPIC_MODES:
        raise Http404("Mode not found.")
    entries = topics.tree(collection)
    selected = next((entry for entry in entries if entry.id == topic_id), None)
    if selected is None:
        raise Http404("Topic not found.")
    topic_ids = [topic_id]
    if mode == "branch":
        topic_ids.extend(entry.id for entry in entries if topic_id in entry.ancestors)
    assignments = TopicAssignment.objects.filter(
        note_id=OuterRef("pk"), topic_id__in=topic_ids
    )
    results = Note.objects.filter(collection=collection).filter(Exists(assignments))
    return TopicNotes(selected, entries, _note_page(collection, results, page, entries))


@transaction.atomic
def note_with_topics(collection: Collection, note_id: UUID) -> Note:
    result = note(collection, note_id)
    load_topics(collection, [result])
    return result


def load_topics(
    collection: Collection,
    results: Sequence[Note],
    entries: Sequence[topics.TopicPath] | None = None,
) -> None:
    assigned: dict[UUID, list[UUID]] = defaultdict(list)
    for note_id, topic_id in TopicAssignment.objects.filter(
        note_id__in=[result.id for result in results], topic__collection=collection
    ).values_list("note_id", "topic_id"):
        assigned[note_id].append(topic_id)

    if entries is None:
        entries = topics.tree(collection) if assigned else []
    positions = {entry.id: index for index, entry in enumerate(entries)}
    for result in results:
        result.topics = [
            entries[positions[topic_id]]
            for topic_id in sorted(assigned[result.id], key=positions.__getitem__)
        ]

from uuid import UUID

from django.core.paginator import InvalidPage, Page, Paginator
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404

from .models import Book, Chapter, Collection, Note

PAGE_SIZE = 20
CAPTURE_ORDER = ("captured_at", "id")
PAGE_ORDER = (F("page_number").asc(nulls_last=True), *CAPTURE_ORDER)
BOOK_NOTE_ORDERING = {
    "oldest": CAPTURE_ORDER,
    "newest": ("-captured_at", "-id"),
    "page": PAGE_ORDER,
    "chapter": (F("chapter__position").asc(nulls_last=True), *PAGE_ORDER),
}


def notes(collection: Collection, page: int | str = 1) -> Page[Note]:
    try:
        return Paginator(
            Note.objects.filter(collection=collection).select_related(
                "book", "chapter"
            ),
            PAGE_SIZE,
        ).page(page)
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


def book_notes(
    collection: Collection, book_id: UUID, page: int | str = 1, order: str = "oldest"
) -> Page[Note]:
    book(collection, book_id)
    if order not in BOOK_NOTE_ORDERING:
        raise Http404("Order not found.")
    try:
        return Paginator(
            Note.objects.filter(collection=collection, book_id=book_id)
            .select_related("book", "chapter")
            .order_by(*BOOK_NOTE_ORDERING[order]),
            PAGE_SIZE,
        ).page(page)
    except InvalidPage as exc:
        raise Http404("Page not found.") from exc

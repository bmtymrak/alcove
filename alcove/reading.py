from uuid import UUID

from django.core.paginator import InvalidPage, Page, Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404

from .models import Collection, Note

PAGE_SIZE = 20


def notes(collection: Collection, page: int | str = 1) -> Page[Note]:
    try:
        return Paginator(Note.objects.filter(collection=collection), PAGE_SIZE).page(
            page
        )
    except InvalidPage as exc:
        raise Http404("Page not found.") from exc


def note(collection: Collection, note_id: UUID) -> Note:
    return get_object_or_404(Note, collection=collection, pk=note_id)

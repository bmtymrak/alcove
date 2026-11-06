import json
from collections.abc import Sequence
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.crypto import salted_hmac
from django.views.decorators.http import require_GET, require_http_methods

from . import books, collections, notes, reading, topics
from .forms import BookForm, CaptureForm, EditForm, TopicCreateForm, TopicRenameForm
from .models import Collection


class SignOutView(LogoutView):
    def post(
        self, request: HttpRequest, *args: object, **kwargs: object
    ) -> HttpResponse:
        authenticated = request.user.is_authenticated
        response = super().post(request, *args, **kwargs)
        if authenticated:
            response["Clear-Site-Data"] = '"storage"'
        return response


def draft_scope(request: HttpRequest, collection: Collection) -> str:
    # Isolate drafts across owners and sign-ins without exposing the session key.
    return salted_hmac(
        "alcove.draft-scope", f"{collection.id}:{request.session.session_key}"
    ).hexdigest()


@login_required
@require_GET
def note_list(request: HttpRequest) -> HttpResponse:
    collection = collections.for_owner(request.user)
    return render(
        request,
        "alcove/index.html",
        {
            "notes": reading.notes(collection, request.GET.get("page", "1")),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def capture(request: HttpRequest, book_id: UUID | None = None) -> HttpResponse:
    collection = collections.for_owner(request.user)
    book = reading.book(collection, book_id) if book_id else None
    form = CaptureForm(
        request.POST if request.method == "POST" else None,
        initial={"book": book.id} if book else None,
        book_options=reading.book_options(collection),
        chapter_options=reading.chapter_options(collection),
        topic_options=topics.tree(collection),
    )
    status = 400 if form.is_bound else 200
    if request.method == "POST" and form.is_valid():
        try:
            note, _ = notes.capture(
                collection,
                form.cleaned_data["document"],
                book=form.cleaned_data["book"],
                capture_id=form.cleaned_data["capture_id"],
                chapter=form.cleaned_data["chapter"],
                page_number=form.cleaned_data["page_number"],
                source_reference=form.cleaned_data["source_reference"],
                topic_changes=form.cleaned_data["topic_changes"],
            )
        except notes.NoteError as exc:
            status = exc.status
            form.add_note_error(exc)
        else:
            if "add_another" in request.POST:
                if form.cleaned_data["book"]:
                    return redirect("book-capture", book_id=form.cleaned_data["book"])
                return redirect("capture")
            return redirect("note", note_id=note.id)
    return render(
        request,
        "alcove/note_form.html",
        {
            "form": form,
            "source_book": book,
            "draft_scope": draft_scope(request, collection),
        },
        status=status,
    )


@login_required
@require_GET
def detail(request: HttpRequest, note_id: UUID) -> HttpResponse:
    note = reading.note_with_topics(collections.for_owner(request.user), note_id)
    return render(request, "alcove/note.html", {"note": note})


@login_required
@require_http_methods(["GET", "POST"])
def edit(request: HttpRequest, note_id: UUID) -> HttpResponse:
    collection = collections.for_owner(request.user)
    note = reading.note_with_topics(collection, note_id)
    form = EditForm(
        request.POST if request.method == "POST" else None,
        initial={
            "content": note.plain_text,
            "content_document": (
                json.dumps(note.content) if note.content["format"] == "tiptap" else ""
            ),
            "revision": note.revision,
            "book": note.book_id,
            "chapter": note.chapter_id,
            "page_number": note.page_number,
            "source_reference": note.source_reference,
        },
        book_options=reading.book_options(collection),
        chapter_options=reading.chapter_options(collection),
        topic_options=topics.tree(collection),
        assigned_topics=tuple(note.topics),
    )
    status = 400 if form.is_bound else 200
    if request.method == "POST" and form.is_valid():
        try:
            notes.edit(
                collection,
                note_id,
                content=form.cleaned_data["document"],
                revision=form.cleaned_data["revision"],
                book=form.cleaned_data["book"],
                topic_changes=form.cleaned_data["topic_changes"],
                **{
                    field: form.cleaned_data[field]
                    for field in ("chapter", "page_number", "source_reference")
                    if field in request.POST
                },
            )
        except notes.NoteError as exc:
            form.add_note_error(exc)
            status = exc.status
        else:
            return redirect("note", note_id=note.id)
    return render(
        request,
        "alcove/note_form.html",
        {
            "form": form,
            "note": note,
            "save_conflict": status == 409,
            "draft_scope": draft_scope(request, collection),
        },
        status=status,
    )


def csrf_failure(request: HttpRequest, reason: str = "") -> HttpResponse:
    return render(request, "alcove/csrf_failure.html", status=403)


@login_required
@require_GET
def index(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "alcove/library.html",
        {
            "books": reading.library(
                collections.for_owner(request.user), request.GET.get("page", "1")
            )
        },
    )


@login_required
@require_GET
def book_detail(request: HttpRequest, book_id: UUID) -> HttpResponse:
    collection = collections.for_owner(request.user)
    book = reading.book(collection, book_id)
    page = request.GET.get("page", "1")
    order = request.GET.get("order", "oldest")
    browsing: dict[str, object] = (
        {"grouped": reading.book_note_groups(collection, book_id, page)}
        if order == "topic"
        else {"notes": reading.book_notes(collection, book_id, page, order)}
    )
    return render(
        request,
        "alcove/book.html",
        {
            "book": book,
            "chapters": reading.book_chapters(collection, book_id),
            "order": order,
            **browsing,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def book_form(request: HttpRequest, book_id: UUID | None = None) -> HttpResponse:
    collection = collections.for_owner(request.user)
    book = reading.book(collection, book_id) if book_id else None
    form = BookForm(
        request.POST if request.method == "POST" else None,
        initial={"title": book.title, "author": book.author} if book else None,
    )
    if request.method == "POST" and form.is_valid():
        try:
            if book:
                book = books.edit(collection, book.id, **form.cleaned_data)
            else:
                book = books.create(collection, **form.cleaned_data)
        except notes.NoteError as exc:
            for field, messages in exc.fields.items():
                for message in messages:
                    form.add_error(field, message)
        else:
            return redirect("book", book_id=book.id)
    return render(
        request,
        "alcove/book_form.html",
        {"book": book, "form": form},
        status=400 if form.is_bound else 200,
    )


@login_required
@require_http_methods(["GET", "POST"])
def topic_tree(request: HttpRequest) -> HttpResponse:
    collection = collections.for_owner(request.user)
    entries = topics.tree(collection)
    form = TopicCreateForm(
        request.POST if request.method == "POST" else None,
        parent_options=[(str(entry.id), entry.full_path) for entry in entries],
    )
    if form.is_valid():
        try:
            topics.create(collection, **form.cleaned_data)
        except notes.NoteError as exc:
            for field, messages in exc.fields.items():
                for message in messages:
                    form.add_error(field, message)
        else:
            return redirect("topic-tree")
    return render(
        request,
        "alcove/topic_tree.html",
        {"rows": topic_rows(entries), "form": form},
        status=400 if form.is_bound else 200,
    )


def topic_rows(
    entries: Sequence[topics.TopicPath],
) -> list[tuple[topics.TopicPath, bool, range]]:
    rows = []
    for entry, following in zip(entries, [*entries[1:], None]):
        depth = len(entry.ancestors)
        next_depth = len(following.ancestors) if following else 0
        rows.append((entry, next_depth > depth, range(depth - next_depth)))
    return rows


@login_required
@require_GET
def topic_detail(request: HttpRequest, topic_id: UUID) -> HttpResponse:
    mode = request.GET.get("mode", "branch")
    result = reading.topic_notes(
        collections.for_owner(request.user),
        topic_id,
        request.GET.get("page", "1"),
        mode,
    )
    return render(
        request,
        "alcove/topic.html",
        {
            "topic": result.topic,
            "rows": topic_rows(result.tree),
            "notes": result.notes,
            "mode": mode,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def topic_rename(request: HttpRequest, topic_id: UUID) -> HttpResponse:
    collection = collections.for_owner(request.user)
    topic = topics.path_for(collection, topic_id)
    form = TopicRenameForm(
        request.POST if request.method == "POST" else None,
        initial={"label": topic.label},
    )
    if form.is_valid():
        try:
            topics.rename(collection, topic_id, **form.cleaned_data)
        except notes.NoteError as exc:
            for message in exc.fields["label"]:
                form.add_error("label", message)
        else:
            return redirect("topic-tree")
    return render(
        request,
        "alcove/topic_rename.html",
        {"topic": topic, "form": form},
        status=400 if form.is_bound else 200,
    )

import json
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.crypto import salted_hmac
from django.views.decorators.http import require_GET, require_http_methods

from . import books, collections, notes, reading
from .forms import BookForm, CaptureForm, EditForm
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
    )
    status = 400 if form.is_bound else 200
    if request.method == "POST" and form.is_valid():
        try:
            note, _ = notes.capture(
                collection,
                form.cleaned_data["document"],
                book=form.cleaned_data["book"],
                capture_id=form.cleaned_data["capture_id"],
            )
        except notes.NoteError as exc:
            status = exc.status
            if not exc.fields:
                form.add_error(None, str(exc))
            for field, messages in exc.fields.items():
                for message in messages:
                    form.add_error(field, message)
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
    note = reading.note(collections.for_owner(request.user), note_id)
    return render(request, "alcove/note.html", {"note": note})


@login_required
@require_http_methods(["GET", "POST"])
def edit(request: HttpRequest, note_id: UUID) -> HttpResponse:
    collection = collections.for_owner(request.user)
    note = reading.note(collection, note_id)
    form = EditForm(
        request.POST if request.method == "POST" else None,
        initial={
            "content": note.plain_text,
            "content_document": (
                json.dumps(note.content) if note.content["format"] == "tiptap" else ""
            ),
            "revision": note.revision,
            "book": note.book_id,
        },
        book_options=reading.book_options(collection),
    )
    status = 400 if form.is_bound else 200
    if request.method == "POST" and form.is_valid():
        try:
            notes.edit(
                collection,
                note_id,
                form.cleaned_data["document"],
                form.cleaned_data["revision"],
                book=form.cleaned_data["book"],
            )
        except notes.NoteError as exc:
            form.add_error(None, str(exc))
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
    book = reading.book(collections.for_owner(request.user), book_id)
    return render(
        request,
        "alcove/book.html",
        {
            "book": book,
            "notes": reading.book_notes(
                collections.for_owner(request.user),
                book_id,
                request.GET.get("page", "1"),
                request.GET.get("order", "oldest"),
            ),
            "order": request.GET.get("order", "oldest"),
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

from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from . import collections, notes, reading
from .forms import CaptureForm, EditForm


@login_required
@require_GET
def index(request: HttpRequest) -> HttpResponse:
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
def capture(request: HttpRequest) -> HttpResponse:
    collection = collections.for_owner(request.user)
    form = CaptureForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            note = notes.capture(
                collection,
                notes.plain_text_content(form.cleaned_data["content"]),
            )
        except notes.NoteError as exc:
            form.add_error("content", str(exc))
        else:
            return redirect("note", note_id=note.id)
    return render(
        request,
        "alcove/note_form.html",
        {"form": form},
        status=400 if form.is_bound else 200,
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
        initial={"content": note.plain_text, "revision": note.revision},
    )
    status = 400 if form.is_bound else 200
    if request.method == "POST" and form.is_valid():
        try:
            notes.edit(
                collection,
                note_id,
                notes.plain_text_content(form.cleaned_data["content"]),
                form.cleaned_data["revision"],
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
        },
        status=status,
    )


def csrf_failure(request: HttpRequest, reason: str = "") -> HttpResponse:
    return render(request, "alcove/csrf_failure.html", status=403)

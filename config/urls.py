from django.contrib.auth.views import LoginView
from django.urls import path
from drf_spectacular.views import SpectacularAPIView
from rest_framework.permissions import IsAuthenticated

from alcove import api, views

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", views.SignOutView.as_view(), name="logout"),
    path("", views.index, name="index"),
    path("books/<uuid:book_id>/notes/new/", views.capture, name="book-capture"),
    path(
        "api/v1/books/<uuid:book_id>/notes/",
        api.BookNotesView.as_view(),
        name="api-book-notes",
    ),
    path("books/new/", views.book_form, name="book-create"),
    path("books/<uuid:book_id>/", views.book_detail, name="book"),
    path("books/<uuid:book_id>/edit/", views.book_form, name="book-edit"),
    path("notes/", views.note_list, name="notes"),
    path("api/v1/books/", api.BooksView.as_view(), name="api-books"),
    path("api/v1/books/<uuid:book_id>/", api.BookView.as_view(), name="api-book"),
    path("notes/new/", views.capture, name="capture"),
    path("notes/<uuid:note_id>/", views.detail, name="note"),
    path("notes/<uuid:note_id>/edit/", views.edit, name="edit"),
    path("api/v1/notes/", api.NotesView.as_view(), name="api-notes"),
    path("api/v1/notes/<uuid:note_id>/", api.NoteView.as_view(), name="api-note"),
    path(
        "api/v1/schema/",
        SpectacularAPIView.as_view(
            permission_classes=[IsAuthenticated],
        ),
        name="schema",
    ),
]

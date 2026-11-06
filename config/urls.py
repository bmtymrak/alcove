from django.contrib.auth.views import LoginView
from django.urls import path
from drf_spectacular.views import SpectacularAPIView
from rest_framework.permissions import IsAuthenticated

from alcove import api, views

urlpatterns = [
    path("healthz", views.health, name="health"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", views.SignOutView.as_view(), name="logout"),
    path("", views.index, name="index"),
    path("books/<uuid:book_id>/notes/new/", views.capture, name="book-capture"),
    path(
        "api/v1/books/<uuid:book_id>/notes/",
        api.BookNotesView.as_view(),
        name="api-book-notes",
    ),
    path(
        "api/v1/books/<uuid:book_id>/note-groups/",
        api.BookNoteGroupsView.as_view(),
        name="api-book-note-groups",
    ),
    path("books/new/", views.book_form, name="book-create"),
    path("books/<uuid:book_id>/", views.book_detail, name="book"),
    path("books/<uuid:book_id>/edit/", views.book_form, name="book-edit"),
    path("books/<uuid:book_id>/remove/", views.book_remove, name="book-remove"),
    path("notes/", views.note_list, name="notes"),
    path("notes/trash/", views.note_trash, name="note-trash"),
    path("topics/", views.topic_tree, name="topic-tree"),
    path("topics/<uuid:topic_id>/", views.topic_detail, name="topic"),
    path("topics/<uuid:topic_id>/rename/", views.topic_rename, name="topic-rename"),
    path(
        "topics/<uuid:topic_id>/move/",
        views.topic_reorganize,
        {"operation": "move"},
        name="topic-move",
    ),
    path(
        "topics/<uuid:topic_id>/remove/",
        views.topic_reorganize,
        {"operation": "remove"},
        name="topic-remove",
    ),
    path("api/v1/topics/", api.TopicsView.as_view(), name="api-topics"),
    path(
        "api/v1/topics/<uuid:topic_id>/notes/",
        api.TopicNotesView.as_view(),
        name="api-topic-notes",
    ),
    path("api/v1/topics/<uuid:topic_id>/", api.TopicView.as_view(), name="api-topic"),
    path(
        "api/v1/topics/<uuid:topic_id>/move/preview/",
        api.TopicMovePreviewView.as_view(),
        name="api-topic-move-preview",
    ),
    path(
        "api/v1/topics/<uuid:topic_id>/move/",
        api.TopicMoveView.as_view(),
        name="api-topic-move",
    ),
    path(
        "api/v1/topics/<uuid:topic_id>/remove/preview/",
        api.TopicRemovalPreviewView.as_view(),
        name="api-topic-removal-preview",
    ),
    path(
        "api/v1/topics/<uuid:topic_id>/remove/",
        api.TopicRemovalView.as_view(),
        name="api-topic-remove",
    ),
    path("api/v1/books/", api.BooksView.as_view(), name="api-books"),
    path("api/v1/books/<uuid:book_id>/", api.BookView.as_view(), name="api-book"),
    path(
        "api/v1/books/<uuid:book_id>/chapters/",
        api.BookChaptersView.as_view(),
        name="api-book-chapters",
    ),
    path(
        "api/v1/books/<uuid:book_id>/chapters/<uuid:chapter_id>/",
        api.BookChapterView.as_view(),
        name="api-book-chapter",
    ),
    path("notes/new/", views.capture, name="capture"),
    path("notes/<uuid:note_id>/", views.detail, name="note"),
    path("notes/<uuid:note_id>/edit/", views.edit, name="edit"),
    path(
        "notes/<uuid:note_id>/trash/",
        views.change_note_state,
        {"trashed": True},
        name="trash-note",
    ),
    path(
        "notes/<uuid:note_id>/restore/",
        views.change_note_state,
        {"trashed": False},
        name="restore-note",
    ),
    path(
        "notes/<uuid:note_id>/delete-permanently/",
        views.delete_note_permanently,
        name="delete-note-permanently",
    ),
    path(
        "notes/<uuid:note_id>/link/",
        views.note_link_picker,
        name="note-link-picker",
    ),
    path(
        "notes/<uuid:note_id>/links/<uuid:related_note_id>/remove/",
        views.remove_note_link,
        name="remove-note-link",
    ),
    path("api/v1/notes/", api.NotesView.as_view(), name="api-notes"),
    path("api/v1/notes/trash/", api.NoteTrashView.as_view(), name="api-note-trash"),
    path("api/v1/notes/<uuid:note_id>/", api.NoteView.as_view(), name="api-note"),
    path(
        "api/v1/notes/<uuid:note_id>/restore/",
        api.NoteRestoreView.as_view(),
        name="api-restore-note",
    ),
    path(
        "api/v1/notes/<uuid:note_id>/delete-permanently/",
        api.NotePermanentDeletionView.as_view(),
        name="api-delete-note-permanently",
    ),
    path(
        "api/v1/notes/<uuid:note_id>/link-candidates/",
        api.NoteLinkCandidatesView.as_view(),
        name="api-note-link-candidates",
    ),
    path(
        "api/v1/notes/<uuid:note_id>/links/",
        api.NoteLinksView.as_view(),
        name="api-note-links",
    ),
    path(
        "api/v1/notes/<uuid:note_id>/links/<uuid:related_note_id>/",
        api.NoteLinkView.as_view(),
        name="api-note-link",
    ),
    path(
        "api/v1/schema/",
        SpectacularAPIView.as_view(
            permission_classes=[IsAuthenticated],
        ),
        name="schema",
    ),
]

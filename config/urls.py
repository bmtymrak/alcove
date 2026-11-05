from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path
from drf_spectacular.views import SpectacularAPIView
from rest_framework.permissions import IsAuthenticated

from alcove import api, views

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("", views.index, name="index"),
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

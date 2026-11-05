from typing import Any
from uuid import UUID

from django.core.paginator import Page
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.serializers import Serializer
from rest_framework.views import APIView

from . import books, collections, notes, reading
from .serializers import (
    BookCreateSerializer,
    BookEditSerializer,
    BookPageSerializer,
    BookSerializer,
    CaptureSerializer,
    EditSerializer,
    ErrorSerializer,
    NotePageSerializer,
    NoteSerializer,
)

ERRORS = {
    403: OpenApiResponse(ErrorSerializer, description="Sign-in or CSRF required."),
    404: OpenApiResponse(ErrorSerializer, description="Not found in your Collection."),
    405: OpenApiResponse(ErrorSerializer, description="Method not allowed."),
}
WRITE_ERRORS = {
    **ERRORS,
    400: OpenApiResponse(ErrorSerializer, description="Invalid fields or JSON."),
    415: OpenApiResponse(ErrorSerializer, description="Send application/json."),
}


def page_response(page: Page[Any], serializer: type[Serializer]) -> Response:
    return Response(
        {
            "count": page.paginator.count,
            "page": page.number,
            "page_size": reading.PAGE_SIZE,
            "results": serializer(page.object_list, many=True).data,
        }
    )


class NotesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="notes_list",
        parameters=[
            OpenApiParameter("page", int, description="1-based page; 20 Notes.")
        ],
        responses={200: NotePageSerializer, **ERRORS},
    )
    def get(self, request: Request) -> Response:
        page = reading.notes(
            collections.for_owner(request.user),
            request.query_params.get("page", "1"),
        )
        return page_response(page, NoteSerializer)

    @extend_schema(
        operation_id="notes_capture",
        request=CaptureSerializer,
        responses={201: NoteSerializer, **WRITE_ERRORS},
    )
    def post(self, request: Request) -> Response:
        collection = collections.for_owner(request.user)
        payload = CaptureSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        note = notes.capture(collection, **payload.validated_data)
        return Response(
            NoteSerializer(note).data,
            status=201,
            headers={
                "Location": reverse("api-note", kwargs={"note_id": note.id}),
            },
        )


class NoteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="notes_read", responses={200: NoteSerializer, **ERRORS})
    def get(self, request: Request, note_id: UUID) -> Response:
        note = reading.note(collections.for_owner(request.user), note_id)
        return Response(NoteSerializer(note).data)

    @extend_schema(
        operation_id="notes_edit",
        request=EditSerializer,
        responses={
            200: NoteSerializer,
            **WRITE_ERRORS,
            409: OpenApiResponse(
                ErrorSerializer, description="Stale revision; no change."
            ),
        },
    )
    def patch(self, request: Request, note_id: UUID) -> Response:
        collection = collections.for_owner(request.user)
        reading.note(collection, note_id)
        payload = EditSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        note = notes.edit(
            collection,
            note_id,
            payload.validated_data.get("content"),
            payload.validated_data["revision"],
            book=payload.validated_data.get("book", notes.SourceChange.UNCHANGED),
        )
        return Response(NoteSerializer(note).data)


class BooksView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="books_list",
        parameters=[
            OpenApiParameter(
                "page",
                int,
                description="1-based page; 20 Books ordered by title then UUID.",
            )
        ],
        responses={200: BookPageSerializer, **ERRORS},
    )
    def get(self, request: Request) -> Response:
        page = reading.library(
            collections.for_owner(request.user), request.query_params.get("page", "1")
        )
        return page_response(page, BookSerializer)

    @extend_schema(
        operation_id="books_create",
        request=BookCreateSerializer,
        responses={201: BookSerializer, **WRITE_ERRORS},
    )
    def post(self, request: Request) -> Response:
        payload = BookCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        book = books.create(
            collections.for_owner(request.user), **payload.validated_data
        )
        return Response(
            BookSerializer(book).data,
            status=201,
            headers={"Location": reverse("api-book", kwargs={"book_id": book.id})},
        )


class BookView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="books_read", responses={200: BookSerializer, **ERRORS})
    def get(self, request: Request, book_id: UUID) -> Response:
        return Response(
            BookSerializer(
                reading.book(collections.for_owner(request.user), book_id)
            ).data
        )

    @extend_schema(
        operation_id="books_edit",
        request=BookEditSerializer,
        responses={200: BookSerializer, **WRITE_ERRORS},
    )
    def patch(self, request: Request, book_id: UUID) -> Response:
        collection = collections.for_owner(request.user)
        reading.book(collection, book_id)
        payload = BookEditSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        book = books.edit(collection, book_id, **payload.validated_data)
        return Response(BookSerializer(book).data)


class BookNotesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="books_notes",
        parameters=[
            OpenApiParameter("page", int, description="1-based page; 20 Notes."),
            OpenApiParameter(
                "order",
                str,
                enum=["oldest", "newest"],
                description=(
                    "Default oldest. Capture timestamp then UUID; newest reverses both."
                ),
            ),
        ],
        responses={200: NotePageSerializer, **ERRORS},
    )
    def get(self, request: Request, book_id: UUID) -> Response:
        page = reading.book_notes(
            collections.for_owner(request.user),
            book_id,
            request.query_params.get("page", "1"),
            request.query_params.get("order", "oldest"),
        )
        return page_response(page, NoteSerializer)

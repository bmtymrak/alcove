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

from . import books, chapters, collections, notes, reading, topics
from .serializers import (
    BookCreateSerializer,
    BookEditSerializer,
    BookNoteGroupPageSerializer,
    BookPageSerializer,
    BookSerializer,
    CaptureSerializer,
    ChapterCreateSerializer,
    ChapterEditSerializer,
    ChapterSerializer,
    ConflictSerializer,
    EditSerializer,
    ErrorSerializer,
    NoteLinkSerializer,
    NotePageSerializer,
    NoteSerializer,
    RelatedNotePageSerializer,
    RelatedNoteSerializer,
    TopicCreateSerializer,
    TopicMoveDestinationSerializer,
    TopicMoveSerializer,
    TopicPreviewSerializer,
    TopicRemovalModeSerializer,
    TopicRemovalSerializer,
    TopicRenameSerializer,
    TopicSerializer,
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
LIFECYCLE_ERRORS = {
    **WRITE_ERRORS,
    409: OpenApiResponse(ErrorSerializer, description="Note is in the wrong state."),
}


def validate_lifecycle_request(request: Request) -> None:
    if request.data != {}:
        raise notes.NoteError("Note lifecycle actions accept no request fields.")


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
        parameters=[
            OpenApiParameter(
                "Location",
                str,
                location=OpenApiParameter.HEADER,
                response=[200, 201],
                description="Relative URL of the saved Note.",
            ),
        ],
        responses={
            200: OpenApiResponse(NoteSerializer, description="Replayed capture."),
            201: NoteSerializer,
            **WRITE_ERRORS,
            409: OpenApiResponse(
                ErrorSerializer,
                description=(
                    "Capture UUID already used for other input or a deleted Note."
                ),
            ),
        },
    )
    def post(self, request: Request) -> Response:
        collection = collections.for_owner(request.user)
        payload = CaptureSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        note, created = notes.capture(collection, **payload.validated_data)
        return Response(
            NoteSerializer(note).data,
            status=201 if created else 200,
            headers={
                "Location": reverse("api-note", kwargs={"note_id": note.id}),
            },
        )


class NoteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="notes_read", responses={200: NoteSerializer, **ERRORS})
    def get(self, request: Request, note_id: UUID) -> Response:
        note = reading.note_with_topics(collections.for_owner(request.user), note_id)
        return Response(NoteSerializer(note).data)

    @extend_schema(
        operation_id="notes_edit",
        request=EditSerializer,
        responses={
            200: NoteSerializer,
            **WRITE_ERRORS,
            409: OpenApiResponse(
                ConflictSerializer,
                description=(
                    "Stale revision; no change. Review the current Note via GET."
                ),
            ),
        },
    )
    def patch(self, request: Request, note_id: UUID) -> Response:
        collection = collections.for_owner(request.user)
        reading.note(collection, note_id)
        payload = EditSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        note = notes.edit(collection, note_id, **payload.validated_data)
        return Response(NoteSerializer(note).data)

    @extend_schema(
        operation_id="notes_trash",
        description="Move an active Note to trash, retaining its associations.",
        responses={204: None, **LIFECYCLE_ERRORS},
    )
    def delete(self, request: Request, note_id: UUID) -> Response:
        validate_lifecycle_request(request)
        notes.set_trashed(collections.for_owner(request.user), note_id, trashed=True)
        return Response(status=204)


class NoteTrashView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="notes_trash_list",
        parameters=[
            OpenApiParameter("page", int, description="1-based page; 20 Notes."),
        ],
        responses={200: NotePageSerializer, **ERRORS},
    )
    def get(self, request: Request) -> Response:
        page = reading.trash(
            collections.for_owner(request.user), request.query_params.get("page", "1")
        )
        return page_response(page, NoteSerializer)


class NoteRestoreView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="notes_restore",
        description="Restore a trashed Note with its surviving associations.",
        request=None,
        responses={204: None, **LIFECYCLE_ERRORS},
    )
    def post(self, request: Request, note_id: UUID) -> Response:
        validate_lifecycle_request(request)
        notes.set_trashed(collections.for_owner(request.user), note_id, trashed=False)
        return Response(status=204)


class NotePermanentDeletionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="notes_delete_permanently",
        description="Permanently delete a trashed Note and remove its Note Links.",
        responses={204: None, **LIFECYCLE_ERRORS},
    )
    def delete(self, request: Request, note_id: UUID) -> Response:
        validate_lifecycle_request(request)
        notes.delete_permanently(collections.for_owner(request.user), note_id)
        return Response(status=204)


class NoteLinkCandidatesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="note_link_candidates",
        parameters=[
            OpenApiParameter(
                "q", str, description="Literal substring of Note text or context."
            ),
            OpenApiParameter("page", int, description="1-based page; 20 Notes."),
        ],
        responses={200: RelatedNotePageSerializer, **ERRORS},
    )
    def get(self, request: Request, note_id: UUID) -> Response:
        page = reading.link_candidates(
            collections.for_owner(request.user),
            note_id,
            request.query_params.get("q", ""),
            request.query_params.get("page", "1"),
        )
        return page_response(page, RelatedNoteSerializer)


class NoteLinksView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="note_links_list",
        parameters=[
            OpenApiParameter("page", int, description="1-based page; 20 Notes.")
        ],
        responses={200: RelatedNotePageSerializer, **ERRORS},
    )
    def get(self, request: Request, note_id: UUID) -> Response:
        page = reading.related_notes(
            collections.for_owner(request.user),
            note_id,
            request.query_params.get("page", "1"),
        )
        return page_response(page, RelatedNoteSerializer)

    @extend_schema(
        operation_id="note_links_create",
        request=NoteLinkSerializer,
        responses={
            201: NoteLinkSerializer,
            **WRITE_ERRORS,
            400: OpenApiResponse(
                ErrorSerializer,
                description="Invalid fields, invalid target, or self-link.",
            ),
            409: OpenApiResponse(
                ErrorSerializer, description="These Notes are already linked."
            ),
        },
    )
    def post(self, request: Request, note_id: UUID) -> Response:
        collection = collections.for_owner(request.user)
        payload = NoteLinkSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        notes.change_link(
            collection, note_id, payload.validated_data["related_note"], action="add"
        )
        return Response(payload.data, status=201)


class NoteLinkView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="note_links_remove",
        responses={
            204: None,
            **ERRORS,
            404: OpenApiResponse(
                ErrorSerializer, description="Note or Note Link not found."
            ),
        },
    )
    def delete(
        self, request: Request, note_id: UUID, related_note_id: UUID
    ) -> Response:
        notes.change_link(
            collections.for_owner(request.user),
            note_id,
            related_note_id,
            action="remove",
        )
        return Response(status=204)


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


class BookChaptersView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="book_chapters_list",
        responses={200: ChapterSerializer(many=True), **ERRORS},
    )
    def get(self, request: Request, book_id: UUID) -> Response:
        sequence = reading.book_chapters(collections.for_owner(request.user), book_id)
        return Response(ChapterSerializer(sequence, many=True).data)

    @extend_schema(
        operation_id="book_chapters_append",
        request=ChapterCreateSerializer,
        responses={201: ChapterSerializer, **WRITE_ERRORS},
    )
    def post(self, request: Request, book_id: UUID) -> Response:
        collection = collections.for_owner(request.user)
        reading.book(collection, book_id)
        payload = ChapterCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        chapter = chapters.create(collection, book_id, **payload.validated_data)
        return Response(ChapterSerializer(chapter).data, status=201)


class BookChapterView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="book_chapters_edit",
        request=ChapterEditSerializer,
        responses={200: ChapterSerializer, **WRITE_ERRORS},
    )
    def patch(self, request: Request, book_id: UUID, chapter_id: UUID) -> Response:
        collection = collections.for_owner(request.user)
        reading.book(collection, book_id)
        payload = ChapterEditSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        chapter = chapters.edit(
            collection, book_id, chapter_id, **payload.validated_data
        )
        return Response(ChapterSerializer(chapter).data)


class BookNotesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="books_notes",
        parameters=[
            OpenApiParameter("page", int, description="1-based page; 20 Notes."),
            OpenApiParameter(
                "order",
                str,
                enum=list(reading.BOOK_NOTE_ORDERING),
                description=(
                    "Default oldest. Newest reverses capture order. Page sorts "
                    "numerically with missing pages last and oldest captures first "
                    "for ties. Chapter follows the Book's sequence with missing "
                    "Chapters last, then the same page and capture ordering. "
                    "UUID breaks final ties."
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


class BookNoteGroupsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="books_note_groups",
        parameters=[
            OpenApiParameter(
                "page",
                int,
                description=(
                    "1-based page; 20 Note appearances. Groups follow case-insensitive "
                    "full Topic paths with Unassigned last. Notes within each group "
                    "follow capture time then UUID. A group may continue on another "
                    "page. Count includes each appearance."
                ),
            )
        ],
        responses={200: BookNoteGroupPageSerializer, **ERRORS},
    )
    def get(self, request: Request, book_id: UUID) -> Response:
        result = reading.book_note_groups(
            collections.for_owner(request.user),
            book_id,
            request.query_params.get("page", "1"),
        )
        return Response(BookNoteGroupPageSerializer(result).data)


class TopicsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="topics_list",
        parameters=[
            OpenApiParameter("q", str, description="Match Topic labels or full paths.")
        ],
        responses={200: TopicSerializer(many=True), **ERRORS},
    )
    def get(self, request: Request) -> Response:
        collection = collections.for_owner(request.user)
        matches = topics.tree(collection, request.query_params.get("q", ""))
        return Response(TopicSerializer(matches, many=True).data)

    @extend_schema(
        operation_id="topics_create",
        request=TopicCreateSerializer,
        responses={201: TopicSerializer, **WRITE_ERRORS},
    )
    def post(self, request: Request) -> Response:
        collection = collections.for_owner(request.user)
        payload = TopicCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        topic = topics.create(collection, **payload.validated_data)
        return Response(
            TopicSerializer(topic).data,
            status=201,
            headers={"Location": reverse("api-topic", kwargs={"topic_id": topic.id})},
        )


class TopicNotesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="topics_notes",
        parameters=[
            OpenApiParameter(
                "page",
                int,
                description="1-based page; 20 unique Notes in capture order.",
            ),
            OpenApiParameter(
                "mode",
                str,
                enum=list(reading.TOPIC_MODES),
                description="Default branch includes descendants. Direct requires an "
                "explicit assignment to this Topic.",
            ),
        ],
        responses={200: NotePageSerializer, **ERRORS},
    )
    def get(self, request: Request, topic_id: UUID) -> Response:
        result = reading.topic_notes(
            collections.for_owner(request.user),
            topic_id,
            request.query_params.get("page", "1"),
            request.query_params.get("mode", "branch"),
        )
        return page_response(result.notes, NoteSerializer)


class TopicView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="topics_read", responses={200: TopicSerializer, **ERRORS}
    )
    def get(self, request: Request, topic_id: UUID) -> Response:
        topic = topics.path_for(collections.for_owner(request.user), topic_id)
        return Response(TopicSerializer(topic).data)

    @extend_schema(
        operation_id="topics_rename",
        request=TopicRenameSerializer,
        responses={200: TopicSerializer, **WRITE_ERRORS},
    )
    def patch(self, request: Request, topic_id: UUID) -> Response:
        collection = collections.for_owner(request.user)
        topics.get(collection, topic_id)
        payload = TopicRenameSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        topic = topics.rename(collection, topic_id, **payload.validated_data)
        return Response(TopicSerializer(topic).data)


TOPIC_APPLY_ERRORS = {
    **WRITE_ERRORS,
    409: OpenApiResponse(ErrorSerializer, description="The Topic preview is stale."),
}


class TopicMovePreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="topics_preview_move",
        request=TopicMoveDestinationSerializer,
        responses={200: TopicPreviewSerializer, **WRITE_ERRORS},
    )
    def post(self, request: Request, topic_id: UUID) -> Response:
        collection = collections.for_owner(request.user)
        topics.get(collection, topic_id)
        payload = TopicMoveDestinationSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        preview = topics.preview_move(collection, topic_id, **payload.validated_data)
        return Response(TopicPreviewSerializer(preview).data)


class TopicMoveView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="topics_move",
        request=TopicMoveSerializer,
        responses={200: TopicSerializer, **TOPIC_APPLY_ERRORS},
    )
    def post(self, request: Request, topic_id: UUID) -> Response:
        collection = collections.for_owner(request.user)
        topics.get(collection, topic_id)
        payload = TopicMoveSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        topic = topics.move(collection, topic_id, **payload.validated_data)
        return Response(TopicSerializer(topic).data)


class TopicRemovalPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="topics_preview_removal",
        request=TopicRemovalModeSerializer,
        responses={200: TopicPreviewSerializer, **WRITE_ERRORS},
    )
    def post(self, request: Request, topic_id: UUID) -> Response:
        collection = collections.for_owner(request.user)
        topics.get(collection, topic_id)
        payload = TopicRemovalModeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        preview = topics.preview_removal(collection, topic_id, **payload.validated_data)
        return Response(TopicPreviewSerializer(preview).data)


class TopicRemovalView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="topics_remove",
        request=TopicRemovalSerializer,
        responses={204: None, **TOPIC_APPLY_ERRORS},
    )
    def post(self, request: Request, topic_id: UUID) -> Response:
        collection = collections.for_owner(request.user)
        topics.get(collection, topic_id)
        payload = TopicRemovalSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        topics.remove(collection, topic_id, **payload.validated_data)
        return Response(status=204)

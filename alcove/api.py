from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from . import collections, notes, reading
from .serializers import (
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
        return Response(
            {
                "count": page.paginator.count,
                "page": page.number,
                "page_size": reading.PAGE_SIZE,
                "results": NoteSerializer(page.object_list, many=True).data,
            }
        )

    @extend_schema(
        operation_id="notes_capture",
        request=CaptureSerializer,
        responses={201: NoteSerializer, **WRITE_ERRORS},
    )
    def post(self, request: Request) -> Response:
        collection = collections.for_owner(request.user)
        payload = CaptureSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        note = notes.capture(collection, payload.validated_data["content"])
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
            payload.validated_data["content"],
            payload.validated_data["revision"],
        )
        return Response(NoteSerializer(note).data)

from typing import Any

from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .notes import NoteError


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, NoteError):
        return Response(
            {
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                    "fields": exc.fields,
                }
            },
            status=exc.status,
        )
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    detail = response.data.get("detail") if isinstance(response.data, dict) else None
    response.data = {
        "error": {
            "code": str(getattr(detail, "code", "invalid")),
            "message": str(detail) if detail else "Check the submitted fields.",
            "fields": {} if detail else response.data,
        }
    }
    return response

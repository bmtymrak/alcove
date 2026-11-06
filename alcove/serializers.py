from typing import Any
from uuid import UUID

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from . import notes


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if isinstance(data, dict):
            unknown = data.keys() - self.fields.keys()
            if unknown:
                raise serializers.ValidationError(
                    {key: ["Unknown field."] for key in sorted(unknown)}
                )
        return super().to_internal_value(data)


@extend_schema_field({"$ref": "#/components/schemas/NoteContent"})
class ContentField(serializers.JSONField):
    def to_internal_value(self, data: Any) -> dict[str, Any]:
        return notes.validated_content(data)[0]


class CaptureIdentityField(serializers.UUIDField):
    def to_internal_value(self, data: Any) -> UUID:
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class CaptureSerializer(StrictSerializer):
    content = ContentField()
    book = serializers.UUIDField(required=False, allow_null=True)
    capture_id = CaptureIdentityField(
        required=False,
        help_text=(
            "Use a new UUID for each capture. Retry the same content and source "
            "with the same UUID to receive the existing Note."
        ),
    )


class RevisionField(serializers.IntegerField):
    def to_internal_value(self, data: Any) -> int:
        if type(data) is not int:
            self.fail("invalid")
        return super().to_internal_value(data)


class EditSerializer(StrictSerializer):
    content = ContentField(required=False)
    book = serializers.UUIDField(required=False, allow_null=True)
    revision = RevisionField(
        min_value=1,
        max_value=notes.MAX_EXPECTED_REVISION,
        help_text=(
            "Required last-read revision. A stale value returns 409 without changes."
        ),
    )


class NoteSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    content = ContentField()
    book = serializers.UUIDField(source="book_id", allow_null=True)
    plain_text = serializers.CharField()
    captured_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    revision = serializers.IntegerField(
        min_value=1,
        help_text="Current saved revision; increases on each successful edit.",
    )


class NotePageSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=0)
    page = serializers.IntegerField(min_value=1)
    page_size = serializers.IntegerField()
    results = NoteSerializer(many=True)


class ErrorDetailSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    # The wire contract uses "fields"; DRF's metaclass collects this declaration.
    fields = serializers.DictField(child=serializers.JSONField())  # type: ignore[assignment]


class ErrorSerializer(serializers.Serializer):
    error = ErrorDetailSerializer()


class ConflictDetailSerializer(ErrorDetailSerializer):
    current_revision = serializers.IntegerField(
        min_value=1,
        help_text=(
            "Saved revision at conflict detection. Fetch and review before retrying."
        ),
    )


class ConflictSerializer(serializers.Serializer):
    error = ConflictDetailSerializer()


class BookCreateSerializer(StrictSerializer):
    title = serializers.CharField(max_length=300)
    author = serializers.CharField(max_length=300, required=False, allow_blank=True)


class BookEditSerializer(StrictSerializer):
    title = serializers.CharField(max_length=300, required=False)
    author = serializers.CharField(max_length=300, required=False, allow_blank=True)


class BookSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    author = serializers.CharField(allow_blank=True)


class BookPageSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=0)
    page = serializers.IntegerField(min_value=1)
    page_size = serializers.IntegerField()
    results = BookSerializer(many=True)

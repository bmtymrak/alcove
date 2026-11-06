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


class StrictIntegerField(serializers.IntegerField):
    def to_internal_value(self, data: Any) -> int:
        if type(data) is not int:
            self.fail("invalid")
        return super().to_internal_value(data)


class SourceReferenceField(serializers.CharField):
    def to_internal_value(self, data: Any) -> str:
        return notes.validated_source_reference(data)


class PageNumberField(serializers.IntegerField):
    def to_internal_value(self, data: Any) -> int:
        value = notes.validated_page_number(data)
        assert value is not None  # DRF handles null before converting a value.
        return value


class NoteSourceSerializer(StrictSerializer):
    book = serializers.UUIDField(required=False, allow_null=True)
    page_number = PageNumberField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=notes.MAX_PAGE_NUMBER,
        help_text="Starting page for numeric ordering. Null clears the anchor.",
    )
    source_reference = SourceReferenceField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text=(
            "Free-text location, such as a page range or footnote. Empty clears it."
        ),
    )


class CaptureSerializer(NoteSourceSerializer):
    content = ContentField()
    capture_id = CaptureIdentityField(
        required=False,
        help_text=(
            "Use a new UUID for each capture. Retry the same content and source "
            "with the same UUID to receive the existing Note."
        ),
    )


class EditSerializer(NoteSourceSerializer):
    content = ContentField(required=False)
    revision = StrictIntegerField(
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
    page_number = serializers.IntegerField(
        allow_null=True, min_value=1, max_value=notes.MAX_PAGE_NUMBER
    )
    source_reference = serializers.CharField(allow_blank=True)
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

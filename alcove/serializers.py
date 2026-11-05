from typing import Any

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


class CaptureSerializer(StrictSerializer):
    content = ContentField()
    book = serializers.UUIDField(required=False, allow_null=True)


class EditSerializer(CaptureSerializer):
    content = ContentField(required=False)
    revision = serializers.IntegerField(
        min_value=1,
        max_value=notes.MAX_EXPECTED_REVISION,
    )


class NoteSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    content = ContentField()
    book = serializers.UUIDField(source="book_id", allow_null=True)
    plain_text = serializers.CharField()
    captured_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    revision = serializers.IntegerField(min_value=1)


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

from typing import Any

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


class ContentSerializer(serializers.Serializer):
    version = serializers.ChoiceField(choices=[1])
    format = serializers.ChoiceField(choices=["plain-text"])
    text = serializers.CharField(
        min_length=1,
        max_length=notes.MAX_CONTENT_LENGTH,
        trim_whitespace=False,
    )

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        return dict(notes.validated_content(data))


class CaptureSerializer(StrictSerializer):
    content = ContentSerializer()
    book = serializers.UUIDField(required=False, allow_null=True)


class EditSerializer(CaptureSerializer):
    content = ContentSerializer(required=False)
    revision = serializers.IntegerField(
        min_value=1,
        max_value=notes.MAX_EXPECTED_REVISION,
    )


class NoteSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    content = ContentSerializer()
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

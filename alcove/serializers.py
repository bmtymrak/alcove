from typing import Any
from uuid import UUID

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from . import chapters, notes, topics
from .models import TOPIC_LABEL_LENGTH


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


class StrictUUIDField(serializers.UUIDField):
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


class TopicSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    parent = serializers.UUIDField(allow_null=True)  # type: ignore[assignment]
    label = serializers.CharField(max_length=TOPIC_LABEL_LENGTH)  # type: ignore[assignment]
    path = serializers.ListField(child=serializers.CharField())
    ancestors = serializers.ListField(child=serializers.UUIDField())
    full_path = serializers.CharField()


class TopicChangeSerializer(StrictSerializer):
    action = serializers.ChoiceField(choices=["assign", "unassign"])
    topic = StrictUUIDField()


class NoteSourceSerializer(StrictSerializer):
    topic_changes = TopicChangeSerializer(
        many=True,
        required=False,
        help_text=(
            "Apply these operations in order. Assigning a Topic replaces assigned "
            "ancestors and descendants. Omission leaves assignments alone."
        ),
    )

    def validate_topic_changes(
        self, changes: list[dict[str, Any]]
    ) -> list[topics.AssignmentChange]:
        return [topics.AssignmentChange(**change) for change in changes]

    book = serializers.UUIDField(required=False, allow_null=True)
    chapter = StrictUUIDField(
        required=False,
        allow_null=True,
        help_text=(
            "Chapter of the selected Book. Null clears it. An omitted Chapter "
            "is cleared when the Book changes."
        ),
    )
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
    capture_id = StrictUUIDField(
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
    topics = TopicSerializer(many=True)
    id = serializers.UUIDField()
    content = ContentField()
    book = serializers.UUIDField(source="book_id", allow_null=True)
    chapter = serializers.UUIDField(source="chapter_id", allow_null=True)
    chapter_label = serializers.CharField(source="chapter.label", allow_null=True)
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


class NoteLinkSerializer(StrictSerializer):
    related_note = StrictUUIDField()


class RelatedNoteSerializer(NoteSerializer):
    book_title = serializers.CharField(source="book.title", allow_null=True)


class RelatedNotePageSerializer(NotePageSerializer):
    results = RelatedNoteSerializer(many=True)


class BookNoteGroupSerializer(serializers.Serializer):
    topic = TopicSerializer(allow_null=True)
    notes = NoteSerializer(many=True)


class BookNoteGroupPageSerializer(serializers.Serializer):
    count = serializers.IntegerField(source="page.paginator.count", min_value=0)
    page = serializers.IntegerField(source="page.number", min_value=1)
    page_size = serializers.IntegerField(source="page.paginator.per_page")
    results = BookNoteGroupSerializer(source="groups", many=True)


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


class StrictLabelField(serializers.CharField):
    def to_internal_value(self, data: Any) -> str:
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class ChapterCreateSerializer(StrictSerializer):
    label = StrictLabelField(max_length=chapters.MAX_LABEL_LENGTH)  # type: ignore[assignment]


class ChapterEditSerializer(StrictSerializer):
    label = StrictLabelField(  # type: ignore[assignment]
        max_length=chapters.MAX_LABEL_LENGTH, required=False
    )
    position = StrictIntegerField(
        min_value=1,
        required=False,
        help_text="Move to this one-based position. Intervening Chapters shift.",
    )


class ChapterSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    label = serializers.CharField(max_length=chapters.MAX_LABEL_LENGTH)  # type: ignore[assignment]
    position = serializers.IntegerField(min_value=1)


class TopicRenameSerializer(StrictSerializer):
    label = StrictLabelField(max_length=TOPIC_LABEL_LENGTH)  # type: ignore[assignment]


class TopicCreateSerializer(TopicRenameSerializer):
    parent = StrictUUIDField(required=False, allow_null=True)  # type: ignore[assignment]


class TopicMoveDestinationSerializer(StrictSerializer):
    parent = StrictUUIDField(  # type: ignore[assignment]
        allow_null=True, help_text="New parent UUID or null for root."
    )


class TopicMoveSerializer(TopicMoveDestinationSerializer):
    confirmation = serializers.RegexField(r"^[0-9a-f]{64}$", max_length=64)
    resolution = serializers.ChoiceField(
        choices=list(topics.MOVE_RESOLUTIONS),
        required=False,
        help_text="Required when the preview lists conflicting assignments.",
    )


class TopicRemovalModeSerializer(StrictSerializer):
    mode = serializers.ChoiceField(choices=list(topics.REMOVAL_MODES))


class TopicRemovalSerializer(TopicRemovalModeSerializer):
    confirmation = serializers.RegexField(r"^[0-9a-f]{64}$", max_length=64)


class TopicImpactSerializer(serializers.Serializer):
    topic = TopicSerializer()
    new_path = serializers.CharField(
        allow_null=True, help_text="Updated full path, or null for a removed Topic."
    )


class TopicAssignmentImpactSerializer(serializers.Serializer):
    note = serializers.UUIDField()
    note_excerpt = serializers.CharField()
    topic = TopicSerializer()
    ancestor = TopicSerializer(
        allow_null=True, help_text="Conflicting ancestor assignment, if any."
    )


class TopicPreviewSerializer(serializers.Serializer):
    topics = TopicImpactSerializer(many=True)
    assignments = TopicAssignmentImpactSerializer(many=True)
    confirmation = serializers.CharField(
        help_text="Pass this token with the same destination or removal mode to apply."
    )

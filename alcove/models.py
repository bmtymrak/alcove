import uuid
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models

if TYPE_CHECKING:
    from .topics import TopicPath


class Collection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)


class Book(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE)
    title = models.CharField(max_length=300)
    author = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["title", "id"]


class Chapter(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    book = models.ForeignKey(Book, on_delete=models.CASCADE)
    label = models.CharField(max_length=300)
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ["position", "id"]


class Note(models.Model):
    if TYPE_CHECKING:
        topics: list[TopicPath]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE)
    book = models.ForeignKey(Book, null=True, blank=True, on_delete=models.SET_NULL)
    chapter = models.ForeignKey(
        Chapter, null=True, blank=True, on_delete=models.SET_NULL
    )
    page_number = models.PositiveIntegerField(null=True, blank=True)
    source_reference = models.TextField(blank=True, default="")
    content = models.JSONField()
    plain_text = models.TextField()
    captured_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    revision = models.PositiveIntegerField(default=1)
    capture_id = models.UUIDField(null=True, editable=False)
    capture_fingerprint = models.CharField(max_length=64, blank=True, editable=False)

    class Meta:
        ordering = ["captured_at", "id"]
        indexes = [models.Index(fields=["collection", "captured_at", "id"])]
        constraints = [
            models.UniqueConstraint(
                fields=["collection", "capture_id"], name="unique_collection_capture"
            )
        ]


class NoteLink(models.Model):
    first_note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="+")
    second_note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="+")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(first_note__lt=models.F("second_note")),
                name="ordered_note_link_endpoints",
            ),
            models.UniqueConstraint(
                fields=["first_note", "second_note"], name="unique_note_link_pair"
            ),
        ]


TOPIC_LABEL_LENGTH = 300


class Topic(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE)
    label = models.CharField(max_length=TOPIC_LABEL_LENGTH)
    label_key = models.TextField(editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["collection", "parent", "label_key"],
                name="unique_sibling_topic_label",
            ),
            models.UniqueConstraint(
                fields=["collection", "label_key"],
                condition=models.Q(parent__isnull=True),
                name="unique_root_topic_label",
            ),
        ]


class TopicAssignment(models.Model):
    note = models.ForeignKey(Note, on_delete=models.CASCADE)
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["note", "topic"], name="unique_note_topic_assignment"
            )
        ]

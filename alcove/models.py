import uuid

from django.conf import settings
from django.db import models


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


class Note(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    collection = models.ForeignKey(Collection, on_delete=models.CASCADE)
    book = models.ForeignKey(Book, null=True, blank=True, on_delete=models.SET_NULL)
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

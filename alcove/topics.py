from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from unicodedata import normalize
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404

from . import note_content
from .errors import NoteError
from .models import TOPIC_LABEL_LENGTH, Collection, Note, Topic, TopicAssignment


def label_key(value: str) -> str:
    return normalize("NFC", value.casefold())


@dataclass(frozen=True)
class TopicPath:
    id: UUID
    parent: UUID | None
    label: str
    path: tuple[str, ...]
    ancestors: tuple[UUID, ...]

    @property
    def full_path(self) -> str:
        # Escape the separator and escape character inside labels.
        return " › ".join(
            part.replace("\\", "\\\\").replace("›", "\\›") for part in self.path
        )


def tree(collection: Collection, query: str = "") -> list[TopicPath]:
    children: dict[UUID | None, list[Topic]] = defaultdict(list)
    for topic in Topic.objects.filter(collection=collection).order_by(
        "label_key", "id"
    ):
        children[topic.parent_id].append(topic)

    result = []
    needle = label_key(query.strip())
    stack: list[tuple[Topic, tuple[str, ...], tuple[UUID, ...]]] = [
        (topic, (), ()) for topic in reversed(children[None])
    ]
    while stack:
        topic, parent_path, ancestors = stack.pop()
        path = (*parent_path, topic.label)
        entry = TopicPath(topic.id, topic.parent_id, topic.label, path, ancestors)
        if (
            not needle
            or needle in label_key(entry.full_path)
            or any(needle in label_key(part) for part in path)
        ):
            result.append(entry)
        stack.extend(
            (child, path, (*ancestors, topic.id))
            for child in reversed(children[topic.id])
        )
    return result


def get(collection: Collection, topic_id: UUID) -> Topic:
    return get_object_or_404(Topic, collection=collection, pk=topic_id)


def path_for(collection: Collection, topic_id: UUID) -> TopicPath:
    get(collection, topic_id)
    return next(entry for entry in tree(collection) if entry.id == topic_id)


def validated_label(label: str) -> str:
    label = " ".join(label.split())
    if (
        not label
        or len(label) > TOPIC_LABEL_LENGTH
        or not note_content.valid_string(label)
    ):
        message = f"Enter a Topic label of 1–{TOPIC_LABEL_LENGTH} characters."
        raise NoteError(message, fields={"label": [message]})
    return label


def save(topic: Topic, label: str) -> None:
    topic.label = validated_label(label)
    topic.label_key = label_key(topic.label)
    try:
        topic.save()
    except IntegrityError as exc:
        message = "A Topic with this label already exists under this parent."
        raise NoteError(message, fields={"label": [message]}) from exc


@transaction.atomic
def create(collection: Collection, label: str, parent: UUID | None = None) -> TopicPath:
    # Lock before reading parent membership, so the validation and insert agree.
    Collection.objects.filter(pk=collection.pk).update(id=F("id"))
    if (
        parent is not None
        and not Topic.objects.filter(collection=collection, pk=parent).exists()
    ):
        message = "Choose a parent Topic from your Collection."
        raise NoteError(message, fields={"parent": [message]})
    topic = Topic(collection=collection, parent_id=parent)
    save(topic, label)
    return path_for(collection, topic.id)


@transaction.atomic
def rename(collection: Collection, topic_id: UUID, label: str) -> TopicPath:
    if not Topic.objects.filter(collection=collection, pk=topic_id).update(
        label=F("label")
    ):
        raise Http404("Topic not found.")
    topic = get(collection, topic_id)
    save(topic, label)
    return path_for(collection, topic.id)


@dataclass(frozen=True)
class AssignmentChange:
    action: Literal["assign", "unassign"]
    topic: UUID


def apply_assignment_changes(note: Note, changes: Sequence[AssignmentChange]) -> None:
    if not changes:
        return
    parents = dict(
        Topic.objects.filter(collection_id=note.collection_id).values_list(
            "id", "parent_id"
        )
    )
    if any(change.topic not in parents for change in changes):
        message = "Choose Topics from your Collection."
        raise NoteError(message, fields={"topic_changes": [message]})

    assignments = TopicAssignment.objects.filter(note=note)
    previous = set(assignments.values_list("topic_id", flat=True))
    selected = previous.copy()

    def ancestors(topic_id: UUID) -> set[UUID]:
        result: set[UUID] = set()
        parent = parents[topic_id]
        while parent is not None:
            result.add(parent)
            parent = parents[parent]
        return result

    for change in changes:
        if change.action == "unassign":
            selected.discard(change.topic)
        else:
            selected.difference_update(ancestors(change.topic))
            selected = {
                topic_id
                for topic_id in selected
                if change.topic not in ancestors(topic_id)
            }
            selected.add(change.topic)

    assignments.filter(topic_id__in=previous - selected).delete()
    TopicAssignment.objects.bulk_create(
        TopicAssignment(note=note, topic_id=topic_id)
        for topic_id in selected - previous
    )

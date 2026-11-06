import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from typing import Literal
from unicodedata import normalize
from uuid import UUID

from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.db.models import F
from django.db.models.functions import Substr
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

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
        return full_path(self.path)


def full_path(path: tuple[str, ...]) -> str:
    # Escape the separator and escape character inside labels.
    return " › ".join(part.replace("\\", "\\\\").replace("›", "\\›") for part in path)


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
    for entry in tree(collection):
        if entry.id == topic_id:
            return entry
    raise Http404("Topic not found.")


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


MOVE_RESOLUTIONS = {
    "keep_ancestors": "Keep the ancestor assignments",
    "keep_descendants": "Keep the descendant assignments",
}
REMOVAL_MODES = {
    "promote_children": "Move children to this Topic’s parent (or to the root)",
    "remove_subtree": "Remove this Topic and all its descendants",
}


@dataclass(frozen=True)
class TopicImpact:
    topic: TopicPath
    new_path: str | None


@dataclass(frozen=True)
class AssignmentImpact:
    assignment_id: int
    note: UUID
    note_excerpt: str
    topic: TopicPath
    ancestor_assignment_id: int | None = None
    ancestor: TopicPath | None = None


@dataclass(frozen=True)
class TopicPreview:
    topics: list[TopicImpact]
    assignments: list[AssignmentImpact]
    confirmation: str


def branch(
    collection: Collection, topic_id: UUID
) -> tuple[dict[UUID, TopicPath], list[TopicPath]]:
    entries = {entry.id: entry for entry in tree(collection)}
    if topic_id not in entries:
        raise Http404("Topic not found.")
    return entries, [
        entry
        for entry in entries.values()
        if entry.id == topic_id or topic_id in entry.ancestors
    ]


def validate_destination(
    entries: dict[UUID, TopicPath],
    parent: UUID | None,
    moving: Sequence[TopicPath],
    *,
    excluding: set[UUID],
    field: str,
) -> None:
    sibling_keys = {
        label_key(entry.label)
        for entry in entries.values()
        if entry.parent == parent and entry.id not in excluding
    }
    for entry in moving:
        if label_key(entry.label) in sibling_keys:
            message = (
                f"A Topic named “{entry.label}” already exists at the destination."
            )
            raise NoteError(message, fields={field: [message]})


def affected_assignments(
    collection: Collection, entries: dict[UUID, TopicPath], topic_ids: set[UUID]
) -> list[AssignmentImpact]:
    rows = (
        TopicAssignment.objects.filter(
            note__collection=collection, topic_id__in=topic_ids
        )
        .order_by("note_id", "topic_id")
        .values_list("id", "note_id", "topic_id", Substr("note__plain_text", 1, 121))
    )
    return [
        AssignmentImpact(
            assignment_id,
            note_id,
            text[:120] + ("…" if len(text) > 120 else ""),
            entries[topic_id],
        )
        for assignment_id, note_id, topic_id, text in rows
    ]


def make_preview(
    collection: Collection,
    operation: tuple[str, UUID | str | None],
    changes: list[TopicImpact],
    assignments: list[AssignmentImpact],
) -> TopicPreview:
    snapshot = json.dumps(
        [
            collection.id,
            operation,
            [asdict(row) for row in changes],
            [asdict(row) for row in assignments],
        ],
        cls=DjangoJSONEncoder,
        sort_keys=True,
    )
    confirmation = salted_hmac(
        "alcove.topic-preview", snapshot, algorithm="sha256"
    ).hexdigest()
    return TopicPreview(changes, assignments, confirmation)


def plan_move(
    collection: Collection, topic_id: UUID, parent: UUID | None
) -> TopicPreview:
    entries, moving = branch(collection, topic_id)
    topic = entries[topic_id]
    destination = entries.get(parent) if parent is not None else None
    moving_ids = {entry.id for entry in moving}
    if parent is not None and (destination is None or parent in moving_ids):
        message = "Choose a parent in your Collection outside this Topic’s branch."
        raise NoteError(message, fields={"parent": [message]})
    if parent == topic.parent:
        message = "Choose a different parent for this Topic."
        raise NoteError(message, fields={"parent": [message]})
    validate_destination(entries, parent, [topic], excluding=set(), field="parent")

    prefix = destination.path if destination else ()
    changes = [
        TopicImpact(entry, full_path(prefix + entry.path[len(topic.ancestors) :]))
        for entry in moving
    ]
    new_ancestors = (
        set((*destination.ancestors, destination.id)) - set(topic.ancestors)
        if destination
        else set()
    )
    conflicts: list[AssignmentImpact] = []
    if new_ancestors:
        assignments = affected_assignments(
            collection, entries, moving_ids | new_ancestors
        )
        # The destination's ancestors form one branch, so each Note has at most
        # one explicit assignment among them.
        ancestors = {
            row.note: row for row in assignments if row.topic.id in new_ancestors
        }
        conflicts = [
            replace(
                row,
                ancestor_assignment_id=ancestors[row.note].assignment_id,
                ancestor=ancestors[row.note].topic,
            )
            for row in assignments
            if row.topic.id in moving_ids and row.note in ancestors
        ]
    return make_preview(collection, ("move", parent), changes, conflicts)


def plan_removal(collection: Collection, topic_id: UUID, mode: str) -> TopicPreview:
    entries, affected = branch(collection, topic_id)
    topic = entries[topic_id]
    if mode not in REMOVAL_MODES:
        message = "Choose how to handle child Topics."
        raise NoteError(message, fields={"mode": [message]})
    if mode == "promote_children":
        children = [entry for entry in affected if entry.parent == topic_id]
        validate_destination(
            entries, topic.parent, children, excluding={topic_id}, field="mode"
        )
        depth = len(topic.ancestors)
        changes = [TopicImpact(topic, None)] + [
            TopicImpact(entry, full_path(entry.path[:depth] + entry.path[depth + 1 :]))
            for entry in affected
            if entry.id != topic_id
        ]
    else:
        changes = [TopicImpact(entry, None) for entry in affected]
    assignments = affected_assignments(
        collection, entries, {row.topic.id for row in changes if row.new_path is None}
    )
    return make_preview(collection, ("remove", mode), changes, assignments)


preview_move = transaction.atomic(plan_move)
preview_removal = transaction.atomic(plan_removal)


def check_confirmation(preview: TopicPreview, confirmation: str) -> None:
    if not constant_time_compare(preview.confirmation, confirmation):
        raise NoteError(
            "The preview no longer matches this change. Preview it again.",
            code="stale_preview",
            status=409,
        )


def clear_assignments(
    collection: Collection, preview: TopicPreview, *, keep_descendants: bool
) -> None:
    removed = {
        row.ancestor_assignment_id if keep_descendants else row.assignment_id
        for row in preview.assignments
    }
    if removed:
        TopicAssignment.objects.filter(
            note__collection=collection, id__in=removed
        ).delete()
        Note.objects.filter(
            collection=collection, id__in={row.note for row in preview.assignments}
        ).update(revision=F("revision") + 1, updated_at=timezone.now())


@transaction.atomic
def move(
    collection: Collection,
    topic_id: UUID,
    parent: UUID | None,
    confirmation: str,
    resolution: str | None = None,
) -> TopicPath:
    # Take SQLite's write lock before recomputing the confirmed preview.
    Collection.objects.filter(pk=collection.pk).update(id=F("id"))
    preview = plan_move(collection, topic_id, parent)
    check_confirmation(preview, confirmation)
    if preview.assignments and resolution not in MOVE_RESOLUTIONS:
        message = "Choose which conflicting Topic Assignments to keep."
        raise NoteError(message, fields={"resolution": [message]})
    clear_assignments(
        collection, preview, keep_descendants=resolution == "keep_descendants"
    )
    Topic.objects.filter(collection=collection, pk=topic_id).update(parent_id=parent)
    return path_for(collection, topic_id)


@transaction.atomic
def remove(
    collection: Collection, topic_id: UUID, mode: str, confirmation: str
) -> None:
    Collection.objects.filter(pk=collection.pk).update(id=F("id"))
    preview = plan_removal(collection, topic_id, mode)
    check_confirmation(preview, confirmation)
    scoped = Topic.objects.filter(collection=collection)
    if mode == "promote_children":
        topic = preview.topics[0].topic
        children = scoped.filter(parent_id=topic_id)
        if children.filter(label_key=label_key(topic.label)).exists():
            # Free the label for an identically named child while keeping the
            # parent alive until its children have been moved out of the cascade.
            scoped.filter(pk=topic_id).update(label_key=f"\x00{topic_id}")
        children.update(parent_id=topic.parent)
    clear_assignments(collection, preview, keep_descendants=False)
    scoped.filter(
        id__in=[row.topic.id for row in preview.topics if row.new_path is None]
    ).delete()


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

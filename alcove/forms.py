import json
import re
from typing import Any
from uuid import UUID, uuid4

from django import forms

from .models import TOPIC_LABEL_LENGTH
from .notes import (
    MAX_CONTENT_LENGTH,
    MAX_EXPECTED_REVISION,
    NoteError,
    plain_text_content,
    validated_content,
    validated_page_number,
)
from .topics import MOVE_RESOLUTIONS, REMOVAL_MODES, AssignmentChange, TopicPath


class NoteForm(forms.Form):
    document_rejected = False

    def __init__(
        self,
        *args: Any,
        book_options: list[tuple[str, str]],
        chapter_options: dict[str, list[dict[str, str | int]]],
        topic_options: list[TopicPath],
        assigned_topics: tuple[TopicPath, ...] = (),
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fields["book"] = forms.TypedChoiceField(
            label="Source book",
            required=False,
            coerce=UUID,
            empty_value=None,
            choices=[("", "No source book"), *book_options],
        )
        self.chapter_options = chapter_options
        self.fields["chapter"] = forms.UUIDField(
            required=False,
            widget=forms.Select(
                choices=[
                    ("", "No chapter"),
                    *(
                        (title, [(item["id"], item["label"]) for item in chapters])
                        for book_id, title in book_options
                        if (chapters := chapter_options.get(book_id))
                    ),
                ]
            ),
        )
        topic_choices = [(str(topic.id), topic.full_path) for topic in topic_options]
        self.fields["assign_topics"] = forms.TypedMultipleChoiceField(
            label="Assign Topics", required=False, choices=topic_choices, coerce=UUID
        )
        unassign_widget = forms.SelectMultiple()
        unassign_ids = {str(topic.id) for topic in assigned_topics}
        if self.is_bound:
            # A stale form can refer to a formerly assigned Topic. Retain that
            # choice so the shared revision check can report the conflict.
            unassign_ids.update(
                unassign_widget.value_from_datadict(
                    self.data, self.files, self.add_prefix("unassign_topics")
                )
            )
        unassign_choices = [
            choice for choice in topic_choices if choice[0] in unassign_ids
        ]
        self.has_unassign_choices = bool(unassign_choices)
        self.fields["unassign_topics"] = forms.TypedMultipleChoiceField(
            label="Unassign Topics",
            required=False,
            choices=unassign_choices,
            coerce=UUID,
            widget=unassign_widget,
        )
        self.topic_picker_data = {
            "options": [
                {
                    "id": str(topic.id),
                    "ancestors": [str(topic_id) for topic_id in topic.ancestors],
                    "full_path": topic.full_path,
                }
                for topic in topic_options
            ],
            "assigned": [str(topic.id) for topic in assigned_topics],
        }
        if self.initial.get("content_document"):
            self.fields["content"].widget.attrs["readonly"] = True

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        data["topic_changes"] = [
            *(
                AssignmentChange("unassign", topic_id)
                for topic_id in data.get("unassign_topics", [])
            ),
            *(
                AssignmentChange("assign", topic_id)
                for topic_id in data.get("assign_topics", [])
            ),
        ]
        raw = data.get("content_document", "")
        if raw:
            try:
                data["document"] = json.loads(raw)
            except (ValueError, RecursionError):
                self.add_error("content_document", "Enter a valid Note JSON document.")
                return data
        else:
            data["document"] = plain_text_content(data.get("content", ""))
        try:
            data["document"] = validated_content(data["document"])[0]
        except NoteError as exc:
            self.add_error("content", str(exc))
            self.document_rejected = str(exc) != "Write something before saving."
        return data

    def clean_page_number(self) -> int | None:
        raw = self.cleaned_data["page_number"]
        value = None if not raw else raw
        if re.fullmatch(r"[0-9]+", raw):
            digits = raw.lstrip("0") or "0"
            # Avoid converting arbitrarily long submitted integers.
            if len(digits) <= 10:
                value = int(digits)
        try:
            return validated_page_number(value)
        except NoteError as exc:
            raise forms.ValidationError(str(exc)) from exc

    def add_note_error(self, error: NoteError) -> None:
        if not error.fields:
            self.add_error(None, str(error))
        for field, messages in error.fields.items():
            for message in messages:
                self.add_error(field if field in self.fields else None, message)

    content_document = forms.CharField(
        label="Formatted content (JSON)",
        required=False,
        strip=False,
        widget=forms.Textarea,
        help_text="Retained document for recovery. Leave empty to use plain text.",
    )

    content = forms.CharField(
        label="Your note",
        strip=False,
        required=False,
        max_length=MAX_CONTENT_LENGTH,
        widget=forms.Textarea(
            attrs={
                "placeholder": "A sentence is enough.",
                "autofocus": True,
                "aria-describedby": "content-help",
            }
        ),
    )
    page_number = forms.CharField(
        label="Page number",
        required=False,
        widget=forms.TextInput(attrs={"inputmode": "numeric"}),
    )
    source_reference = forms.CharField(
        label="Source reference",
        required=False,
        strip=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )


class CaptureForm(NoteForm):
    capture_id = forms.UUIDField(
        required=False, initial=uuid4, widget=forms.HiddenInput
    )


class EditForm(NoteForm):
    revision = forms.IntegerField(
        min_value=1,
        max_value=MAX_EXPECTED_REVISION,
        widget=forms.HiddenInput,
    )


class NoteLinkForm(forms.Form):
    related_note = forms.UUIDField()


class BookForm(forms.Form):
    title = forms.CharField(max_length=300)
    author = forms.CharField(max_length=300, required=False)


class TopicRenameForm(forms.Form):
    label = forms.CharField(max_length=TOPIC_LABEL_LENGTH)

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        if "parent" in self.data:
            self.add_error(None, "Renaming a Topic only accepts a label.")
        return data


class TopicCreateForm(forms.Form):
    label = forms.CharField(max_length=TOPIC_LABEL_LENGTH)
    parent = forms.UUIDField(required=False, widget=forms.Select)

    def __init__(
        self, *args: Any, parent_options: list[tuple[str, str]], **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fields["parent"].widget.choices = [("", "No parent"), *parent_options]


class TopicReorganizationForm(forms.Form):
    confirmation = forms.RegexField(r"\A[0-9a-f]{64}\Z", max_length=64, required=False)


class TopicMoveForm(TopicReorganizationForm):
    parent = forms.UUIDField(label="New parent", required=False, widget=forms.Select)
    resolution = forms.ChoiceField(
        label="Conflicting assignments",
        choices=[("", "Choose which assignments to keep"), *MOVE_RESOLUTIONS.items()],
        required=False,
    )

    def __init__(
        self, *args: Any, parent_options: list[tuple[str, str]], **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fields["parent"].widget.choices = [("", "Root"), *parent_options]

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        if "parent" not in self.data:
            self.add_error("parent", "Choose a new parent or the root.")
        return data


class TopicRemovalForm(TopicReorganizationForm):
    mode = forms.ChoiceField(
        label="Child Topics", choices=[("", "Choose an option"), *REMOVAL_MODES.items()]
    )

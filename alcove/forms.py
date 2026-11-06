import json
import re
from typing import Any
from uuid import UUID, uuid4

from django import forms

from .notes import (
    MAX_CONTENT_LENGTH,
    MAX_EXPECTED_REVISION,
    NoteError,
    plain_text_content,
    validated_content,
    validated_page_number,
)


class NoteForm(forms.Form):
    document_rejected = False

    def __init__(
        self,
        *args: Any,
        book_options: list[tuple[str, str]],
        chapter_options: dict[str, list[dict[str, str | int]]],
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
        if self.initial.get("content_document"):
            self.fields["content"].widget.attrs["readonly"] = True

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
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
                self.add_error(field, message)

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


class BookForm(forms.Form):
    title = forms.CharField(max_length=300)
    author = forms.CharField(max_length=300, required=False)

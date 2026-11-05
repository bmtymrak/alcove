from typing import Any
from uuid import UUID

from django import forms

from .notes import MAX_CONTENT_LENGTH, MAX_EXPECTED_REVISION


class CaptureForm(forms.Form):
    def __init__(
        self, *args: Any, book_options: list[tuple[str, str]], **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fields["book"] = forms.TypedChoiceField(
            label="Source book",
            required=False,
            coerce=UUID,
            empty_value=None,
            choices=[("", "No source book"), *book_options],
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


class EditForm(CaptureForm):
    revision = forms.IntegerField(
        min_value=1,
        max_value=MAX_EXPECTED_REVISION,
        widget=forms.HiddenInput,
    )


class BookForm(forms.Form):
    title = forms.CharField(max_length=300)
    author = forms.CharField(max_length=300, required=False)

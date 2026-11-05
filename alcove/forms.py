from django import forms

from .notes import MAX_CONTENT_LENGTH, MAX_EXPECTED_REVISION


class CaptureForm(forms.Form):
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

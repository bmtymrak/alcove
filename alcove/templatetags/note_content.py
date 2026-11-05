from typing import Any

from django import template
from django.utils.safestring import SafeString, mark_safe

from alcove import note_content

register = template.Library()


@register.filter
def render_note(value: Any) -> SafeString:
    # Only the closed document renderer may produce trusted Note HTML.
    return mark_safe(note_content.render(value))

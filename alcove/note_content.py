"""The supported Note document language and its plain-text projection."""

from typing import Any
from urllib.parse import urlsplit

MAX_CONTENT_LENGTH = 100_000
MAX_NODES = 10_000
MAX_DEPTH = 20
MAX_LINK_LENGTH = 2048
BLOCKS = {"paragraph", "blockquote", "bulletList", "orderedList"}


class InvalidContent(ValueError):
    pass


def invalid() -> None:
    raise InvalidContent("Use only supported Note formatting and http/https links.")


def valid_string(value: Any) -> bool:
    return isinstance(value, str) and not any(
        char == "\x00" or 0xD800 <= ord(char) <= 0xDFFF for char in value
    )


def validate_link(href: Any) -> None:
    if (
        not valid_string(href)
        or len(href) > MAX_LINK_LENGTH
        or any(
            char.isspace() or ord(char) < 32 or ord(char) == 127 or char == "\\"
            for char in href
        )
        or not href.lower().startswith(("http://", "https://"))
    ):
        invalid()
    try:
        url = urlsplit(href)
        if not url.hostname or url.port == 0:
            invalid()
    except ValueError:
        invalid()


def validate(value: Any) -> tuple[dict[str, Any], str]:
    if not isinstance(value, dict) or type(value.get("version")) is not int:
        invalid()
    if value["version"] != 1:
        invalid()
    if value.get("format") == "plain-text":
        if set(value) != {"version", "format", "text"} or not valid_string(
            value["text"]
        ):
            invalid()
        text = value["text"]
    elif value.get("format") == "tiptap":
        if set(value) != {"version", "format", "doc"}:
            invalid()
        remaining = MAX_NODES

        def visit(node: Any, allowed: set[str], depth: int = 0) -> str:
            nonlocal remaining
            remaining -= 1
            if remaining < 0 or depth > MAX_DEPTH or not isinstance(node, dict):
                invalid()
            kind = node.get("type")
            if not isinstance(kind, str) or kind not in allowed:
                invalid()
            if kind == "text":
                if (
                    set(node) - {"type", "text", "marks"}
                    or not valid_string(node.get("text"))
                    or not node["text"]
                ):
                    invalid()
                marks = node.get("marks", [])
                if not isinstance(marks, list) or len(marks) > 3:
                    invalid()
                seen = set()
                for mark in marks:
                    if not isinstance(mark, dict):
                        invalid()
                    name = mark.get("type")
                    if not isinstance(name, str) or name in seen:
                        invalid()
                    seen.add(name)
                    if name in {"bold", "italic"}:
                        if set(mark) != {"type"}:
                            invalid()
                    elif name == "link":
                        if (
                            set(mark) != {"type", "attrs"}
                            or not isinstance(mark["attrs"], dict)
                            or set(mark["attrs"]) != {"href"}
                        ):
                            invalid()
                        validate_link(mark["attrs"]["href"])
                    else:
                        invalid()
                return node["text"]
            if kind == "hardBreak":
                if set(node) != {"type"}:
                    invalid()
                return "\n"
            keys = (
                {"type", "content", "attrs"}
                if kind == "orderedList"
                else {"type", "content"}
            )
            if set(node) - keys:
                invalid()
            if kind == "orderedList" and "attrs" in node:
                attrs = node["attrs"]
                if (
                    not isinstance(attrs, dict)
                    or set(attrs) != {"start"}
                    or type(attrs["start"]) is not int
                    or not 1 <= attrs["start"] <= 2**31 - 1
                ):
                    invalid()
            children = node.get("content", [])
            if not isinstance(children, list) or (kind != "paragraph" and not children):
                invalid()
            if kind == "paragraph":
                child_types = {"text", "hardBreak"}
            elif kind in {"bulletList", "orderedList"}:
                child_types = {"listItem"}
            else:
                child_types = BLOCKS
            if kind == "listItem" and (
                not isinstance(children[0], dict)
                or children[0].get("type") != "paragraph"
            ):
                invalid()
            parts = [visit(child, child_types, depth + 1) for child in children]
            return ("" if kind == "paragraph" else "\n").join(parts)

        text = visit(value["doc"], {"doc"})
    else:
        invalid()
    if len(text) > MAX_CONTENT_LENGTH:
        raise InvalidContent("Use at most 100,000 characters without null characters.")
    if not text.strip():
        raise InvalidContent("Write something before saving.")
    return value, text


def render(value: Any) -> str:
    """Render validated nodes only; every text/attribute value is escaped."""
    from html import escape

    document, _ = validate(value)
    if document["format"] == "plain-text":
        return f"<p>{escape(document['text'])}</p>"

    def node_html(node: dict[str, Any]) -> str:
        kind = node["type"]
        if kind == "text":
            result = escape(node["text"])
            for mark in reversed(node.get("marks", [])):
                if mark["type"] == "link":
                    href = escape(mark["attrs"]["href"], quote=True)
                    result = f'<a href="{href}" rel="noopener noreferrer">{result}</a>'
                else:
                    tag = "strong" if mark["type"] == "bold" else "em"
                    result = f"<{tag}>{result}</{tag}>"
            return result
        if kind == "hardBreak":
            return "<br>"
        children = "".join(node_html(child) for child in node.get("content", []))
        if kind == "doc":
            return children
        tag = {
            "paragraph": "p",
            "blockquote": "blockquote",
            "bulletList": "ul",
            "orderedList": "ol",
            "listItem": "li",
        }[kind]
        attrs = (
            f' start="{node.get("attrs", {}).get("start", 1)}"'
            if kind == "orderedList"
            else ""
        )
        return f"<{tag}{attrs}>{children}</{tag}>"

    return node_html(document["doc"])

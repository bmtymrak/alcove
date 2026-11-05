"""OpenAPI representation of the Note document language (runtime rules add limits)."""

from typing import Any


def ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


def block_schema(kind: str, children: dict[str, Any]) -> dict[str, Any]:
    return object_schema(
        {
            "type": {"type": "string", "const": kind},
            "content": {"type": "array", "minItems": 1, "items": children},
        },
        ["type", "content"],
    )


CONTENT_COMPONENTS = {
    "NoteContent": {
        "description": (
            "Canonical version 1 Note content. Tiptap documents support paragraphs, "
            "bold/italic text, lists, quotations, hard breaks and absolute http/https "
            "links only. Legacy plain-text documents remain supported. "
            "Runtime validation additionally requires non-whitespace text, at most "
            "100,000 projected characters, 10,000 nodes, and depth 20 (root depth 0). "
            "Null characters and unpaired surrogates are forbidden. Text marks "
            "must have distinct types. See docs/api.md for projection and errors."
        ),
        "oneOf": [
            object_schema(
                {
                    "version": {"type": "integer", "const": 1},
                    "format": {"type": "string", "const": "plain-text"},
                    "text": {"type": "string", "minLength": 1, "maxLength": 100_000},
                },
                ["version", "format", "text"],
            ),
            object_schema(
                {
                    "version": {"type": "integer", "const": 1},
                    "format": {"type": "string", "const": "tiptap"},
                    "doc": ref("NoteDocument"),
                },
                ["version", "format", "doc"],
            ),
        ],
    },
    "NoteDocument": block_schema("doc", ref("NoteBlock")),
    "NoteBlock": {
        "oneOf": [
            ref(name)
            for name in [
                "NoteParagraph",
                "NoteBlockquote",
                "NoteBulletList",
                "NoteOrderedList",
            ]
        ]
    },
    "NoteParagraph": object_schema(
        {
            "type": {"type": "string", "const": "paragraph"},
            "content": {
                "type": "array",
                "items": {"oneOf": [ref("NoteText"), ref("NoteHardBreak")]},
            },
        },
        ["type"],
    ),
    "NoteText": object_schema(
        {
            "type": {"type": "string", "const": "text"},
            "text": {"type": "string", "minLength": 1, "maxLength": 100_000},
            "marks": ref("NoteMarks"),
        },
        ["type", "text"],
    ),
    "NoteHardBreak": object_schema(
        {"type": {"type": "string", "const": "hardBreak"}, "marks": ref("NoteMarks")},
        ["type"],
    ),
    "NoteMarks": {
        "type": "array",
        "maxItems": 3,
        "uniqueItems": True,
        "items": ref("NoteMark"),
    },
    "NoteMark": {
        "oneOf": [
            object_schema(
                {
                    "type": {
                        "type": "string",
                        "oneOf": [{"const": "bold"}, {"const": "italic"}],
                    }
                },
                ["type"],
            ),
            object_schema(
                {
                    "type": {"type": "string", "const": "link"},
                    "attrs": object_schema(
                        {
                            "href": {
                                "type": "string",
                                "maxLength": 2048,
                                "pattern": r"^[hH][tT][tT][pP][sS]?://[^\s\\]+$",
                                "description": (
                                    "Absolute http/https URL with a host "
                                    "and valid port; "
                                    "no whitespace, control characters or backslashes."
                                ),
                            }
                        },
                        ["href"],
                    ),
                },
                ["type", "attrs"],
            ),
        ]
    },
    "NoteBlockquote": block_schema("blockquote", ref("NoteBlock")),
    "NoteBulletList": block_schema("bulletList", ref("NoteListItem")),
    "NoteOrderedList": block_schema("orderedList", ref("NoteListItem")),
    "NoteListItem": block_schema("listItem", ref("NoteBlock")),
}
CONTENT_COMPONENTS["NoteOrderedList"]["properties"]["attrs"] = object_schema(
    {"start": {"type": "integer", "minimum": 1, "maximum": 2**31 - 1}}, ["start"]
)
CONTENT_COMPONENTS["NoteListItem"]["properties"]["content"].update(
    prefixItems=[ref("NoteParagraph")],
    description="A paragraph followed by zero or more supported blocks.",
)

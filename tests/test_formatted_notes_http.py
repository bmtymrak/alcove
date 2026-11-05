import json

import pytest
from conftest import document, json_request
from django.utils.html import escape


def rich_document(*blocks):
    return {
        "version": 1,
        "format": "tiptap",
        "doc": {"type": "doc", "content": list(blocks)},
    }


def paragraph(text, marks=None):
    node = {"type": "text", "text": text}
    if marks:
        node["marks"] = marks
    return {"type": "paragraph", "content": [node]}


def test_formatted_note_round_trip_and_derived_readable_text(signed_in):
    content = rich_document(
        {"type": "blockquote", "content": [paragraph("A quotation.")]},
        paragraph("My interpretation.", [{"type": "bold"}, {"type": "italic"}]),
        {
            "type": "bulletList",
            "content": [{"type": "listItem", "content": [paragraph("One idea.")]}],
        },
        {
            "type": "orderedList",
            "attrs": {"start": 3},
            "content": [{"type": "listItem", "content": [paragraph("Next idea.")]}],
        },
        paragraph(
            "Related reading",
            [{"type": "link", "attrs": {"href": "https://example.org/?a=1&b=2"}}],
        ),
    )
    response = json_request(signed_in, "post", "/api/v1/notes/", {"content": content})
    assert response.status_code == 201
    note = response.json()
    assert note["content"] == content
    assert note["plain_text"] == (
        "A quotation.\nMy interpretation.\nOne idea.\nNext idea.\nRelated reading"
    )
    assert signed_in.get(response["Location"]).json() == note
    assert signed_in.get("/api/v1/notes/").json()["results"] == [note]


def test_reading_renders_only_supported_formatting_and_escapes_text(signed_in):
    content = rich_document(
        {"type": "blockquote", "content": [paragraph('<script>alert("x")</script>')]},
        paragraph("Emphasized", [{"type": "bold"}, {"type": "italic"}]),
        {
            "type": "orderedList",
            "attrs": {"start": 3},
            "content": [{"type": "listItem", "content": [paragraph("An item")]}],
        },
        paragraph(
            "A website",
            [{"type": "link", "attrs": {"href": 'https://example.org/?q="&x=1'}}],
        ),
    )
    book = json_request(
        signed_in, "post", "/api/v1/books/", {"title": "Reading"}
    ).json()
    note = json_request(
        signed_in, "post", "/api/v1/notes/", {"content": content, "book": book["id"]}
    ).json()
    for path in ["/notes/", f"/notes/{note['id']}/", f"/books/{book['id']}/"]:
        html = signed_in.get(path).content.decode()
        assert (
            "<blockquote><p>&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;</p>"
            in html
        )
        assert "<strong><em>Emphasized</em></strong>" in html
        assert '<ol start="3"><li><p>An item</p></li></ol>' in html
        assert 'href="https://example.org/?q=&quot;&amp;x=1"' in html
        assert "<script>" not in html


@pytest.mark.parametrize("book_capture", [False, True])
def test_html_formatted_capture_and_edit_use_the_json_content_contract(
    signed_in, book_capture
):
    book = json_request(signed_in, "post", "/api/v1/books/", {"title": "Source"}).json()
    path = f"/books/{book['id']}/notes/new/" if book_capture else "/notes/new/"
    content = rich_document(paragraph("A thought.", [{"type": "italic"}]))
    response = signed_in.post(
        path,
        {
            "content_document": json.dumps(content),
            "book": book["id"] if book_capture else "",
            "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
        },
    )
    assert response.status_code == 302
    note = signed_in.get("/api/v1/notes/").json()["results"][0]
    assert note["content"] == content
    assert note["book"] == (book["id"] if book_capture else None)
    edited = rich_document(paragraph("Reconsidered.", [{"type": "bold"}]))
    response = signed_in.post(
        response["Location"] + "edit/",
        {
            "content_document": json.dumps(edited),
            "revision": 1,
            "book": book["id"] if book_capture else "",
            "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
        },
    )
    assert response.status_code == 302
    assert signed_in.get(f"/api/v1/notes/{note['id']}/").json()["content"] == edited


@pytest.mark.parametrize(
    "invalid_content",
    [
        rich_document(),
        rich_document({"type": "paragraph"}),
        rich_document(paragraph(" \n\u2003\u00a0", [{"type": "bold"}])),
        rich_document({"type": "image", "attrs": {"src": "https://example.org/x.png"}}),
        rich_document({**paragraph("Text"), "attrs": {"style": "color:red"}}),
        rich_document(paragraph("Text", [{"type": "strike"}])),
        rich_document(paragraph("Text", [{"type": "bold", "onclick": "alert(1)"}])),
        rich_document(paragraph("Text", [{"type": "bold"}, {"type": "bold"}])),
        rich_document({"type": "paragraph", "content": [{"type": "text", "text": ""}]}),
        rich_document(
            {"type": "paragraph", "content": [paragraph("Nested paragraph")]}
        ),
        rich_document(
            {"type": "blockquote", "content": [{"type": "text", "text": "x"}]}
        ),
        rich_document({"type": "bulletList", "content": [paragraph("Not an item")]}),
        rich_document(
            {
                "type": "orderedList",
                "attrs": {"start": True},
                "content": [{"type": "listItem", "content": [paragraph("Text")]}],
            }
        ),
        rich_document(
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "blockquote",
                                "content": [paragraph("Missing first paragraph")],
                            }
                        ],
                    }
                ],
            }
        ),
        rich_document({"type": "paragraph", "content": {"text": "Not an array"}}),
        rich_document({"type": ["paragraph"], "content": []}),
        {**rich_document(paragraph("Text")), "version": True},
        {**rich_document(paragraph("Text")), "html": "<script>alert(1)</script>"},
        rich_document(paragraph("Null\x00text")),
        rich_document(paragraph("Unpaired \ud800")),
        rich_document(paragraph("a" * 100_001)),
    ],
)
def test_invalid_formatted_capture_is_rejected_by_both_paths_and_retained(
    signed_in, invalid_content
):
    response = json_request(
        signed_in, "post", "/api/v1/notes/", {"content": invalid_content}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid"
    assert "content" in response.json()["error"]["fields"]
    raw = json.dumps(invalid_content)
    response = signed_in.post(
        "/notes/new/",
        {
            "content_document": raw,
            "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
        },
    )
    assert response.status_code == 400
    assert escape(raw) in response.content.decode()
    assert signed_in.get("/api/v1/notes/").json()["count"] == 0


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "mailto:reader@example.org",
        "ftp://example.org/",
        "//example.org/",
        "/notes/new/",
        "https://",
        "https://example.org:invalid/",
        "https://example.org:70000/",
        "https://example.org:0/",
        "https://[invalid/",
        "https://example.org/\nscript",
        "https://example.org/with space",
        "https://example.org/\\x",
    ],
)
def test_unsafe_links_cannot_replace_saved_content_through_either_path(signed_in, href):
    saved = json_request(
        signed_in, "post", "/api/v1/notes/", {"content": document("Keep this Note.")}
    ).json()
    invalid_content = rich_document(
        paragraph("Pending link", [{"type": "link", "attrs": {"href": href}}])
    )
    path = f"/api/v1/notes/{saved['id']}/"
    response = json_request(
        signed_in,
        "patch",
        path,
        {
            "content": invalid_content,
            "revision": 1,
        },
    )
    assert response.status_code == 400
    raw = json.dumps(invalid_content)
    response = signed_in.post(
        f"/notes/{saved['id']}/edit/",
        {
            "content_document": raw,
            "revision": 1,
            "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
        },
    )
    assert response.status_code == 400
    assert escape(raw) in response.content.decode()
    assert signed_in.get(path).json() == saved


@pytest.mark.parametrize("raw", ['{"version":', "null", "[]", "{}"])
def test_unparseable_or_non_document_html_input_is_retained(signed_in, raw):
    response = signed_in.post(
        "/notes/new/",
        {
            "content_document": raw,
            "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
        },
    )
    assert response.status_code == 400
    assert escape(raw) in response.content.decode()
    assert signed_in.get("/api/v1/notes/").json()["count"] == 0


def test_explicit_null_html_document_cannot_be_treated_as_an_omitted_edit(signed_in):
    saved = json_request(
        signed_in, "post", "/api/v1/notes/", {"content": document("Keep this Note.")}
    ).json()
    response = signed_in.post(
        f"/notes/{saved['id']}/edit/",
        {
            "content_document": "null",
            "revision": 1,
            "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
        },
    )
    assert response.status_code == 400
    assert signed_in.get(f"/api/v1/notes/{saved['id']}/").json() == saved


def test_formatted_edit_conflicts_retain_the_document(signed_in):
    saved = json_request(
        signed_in,
        "post",
        "/api/v1/notes/",
        {"content": rich_document(paragraph("Original"))},
    ).json()
    path = f"/api/v1/notes/{saved['id']}/"
    newer = json_request(
        signed_in,
        "patch",
        path,
        {
            "content": rich_document(paragraph("Newer", [{"type": "italic"}])),
            "revision": 1,
        },
    ).json()
    raw = json.dumps(rich_document(paragraph("Unsaved", [{"type": "bold"}])))
    response = signed_in.post(
        f"/notes/{saved['id']}/edit/",
        {
            "content_document": raw,
            "revision": 1,
            "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
        },
    )
    assert response.status_code == 409
    assert escape(raw) in response.content.decode()
    assert signed_in.get(path).json() == newer


def test_formatted_notes_stay_private_to_their_owner(signed_in):
    from django.contrib.auth.models import User
    from django.test import Client

    from alcove.models import Collection

    content = rich_document(paragraph("Private quotation", [{"type": "bold"}]))
    book = json_request(
        signed_in, "post", "/api/v1/books/", {"title": "Private book"}
    ).json()
    saved = json_request(
        signed_in,
        "post",
        "/api/v1/notes/",
        {
            "content": content,
            "book": book["id"],
        },
    ).json()
    user = User.objects.create_user("another", password="Another-private-reader-472!")
    Collection.objects.create(owner=user)
    other = Client(enforce_csrf_checks=True)
    other.get("/login/")
    assert (
        other.post(
            "/login/",
            {
                "username": user.username,
                "password": "Another-private-reader-472!",
                "csrfmiddlewaretoken": other.cookies["csrftoken"].value,
            },
        ).status_code
        == 302
    )
    assert other.get("/api/v1/notes/").json()["count"] == 0
    assert "Private quotation" not in other.get("/notes/").content.decode()
    for path in [
        f"/notes/{saved['id']}/",
        f"/notes/{saved['id']}/edit/",
        f"/books/{book['id']}/",
    ]:
        assert other.get(path).status_code == 404
    path = f"/api/v1/notes/{saved['id']}/"
    assert other.get(path).status_code == 404
    assert (
        json_request(
            other, "patch", path, {"content": content, "revision": 1}
        ).status_code
        == 404
    )
    assert (
        other.post(
            f"/notes/{saved['id']}/edit/",
            {
                "content_document": json.dumps(content),
                "revision": 1,
                "csrfmiddlewaretoken": other.cookies["csrftoken"].value,
            },
        ).status_code
        == 404
    )
    assert (
        json_request(
            other,
            "post",
            "/api/v1/notes/",
            {
                "content": content,
                "book": book["id"],
            },
        ).status_code
        == 400
    )
    assert signed_in.get(path).json() == saved


def test_formatted_structure_limits_reject_excessive_depth_and_node_counts(signed_in):
    nested = paragraph("Deeply nested")
    for _ in range(21):
        nested = {"type": "blockquote", "content": [nested]}
    for content in [rich_document(nested), rich_document(*([paragraph("x")] * 5_001))]:
        response = json_request(
            signed_in, "post", "/api/v1/notes/", {"content": content}
        )
        assert response.status_code == 400
    assert signed_in.get("/api/v1/notes/").json()["count"] == 0

from pathlib import Path

import yaml
from conftest import document, json_request
from drf_spectacular.generators import SchemaGenerator
from jsonschema import Draft202012Validator, FormatChecker

SCHEMA = yaml.safe_load((Path(__file__).parents[1] / "docs/openapi.yaml").read_text())
COLLECTION = "/api/v1/notes/"
DETAIL = "/api/v1/notes/{note_id}/"


def validate_response(response, path, method, status):
    assert response.status_code == status
    shape = SCHEMA["paths"][path][method]["responses"][str(status)]["content"][
        "application/json"
    ]["schema"]
    Draft202012Validator(
        {**shape, "components": SCHEMA["components"]},
        format_checker=FormatChecker(),
    ).validate(response.json())


def validate_request(payload, path, method):
    shape = SCHEMA["paths"][path][method]["requestBody"]["content"]["application/json"][
        "schema"
    ]
    Draft202012Validator({**shape, "components": SCHEMA["components"]}).validate(
        payload
    )


def test_checked_schema_matches_the_generated_contract():
    assert SchemaGenerator().get_schema(request=None, public=True) == SCHEMA


def test_documented_successes_and_errors_match_real_http_responses(signed_in):
    payload = {"content": document("A documented thought.")}
    validate_request(payload, COLLECTION, "post")
    response = json_request(signed_in, "post", COLLECTION, payload)
    validate_response(response, COLLECTION, "post", 201)
    path = response["Location"]
    validate_response(signed_in.get(COLLECTION), COLLECTION, "get", 200)
    validate_response(signed_in.get(path), DETAIL, "get", 200)
    payload = {
        "content": document("Revised through the documented API."),
        "revision": 1,
    }
    validate_request(payload, DETAIL, "patch")
    validate_response(
        json_request(signed_in, "patch", path, payload), DETAIL, "patch", 200
    )

    conflict = json_request(signed_in, "patch", path, payload)
    validate_response(conflict, DETAIL, "patch", 409)
    assert conflict.json()["error"]["code"] == "conflict"
    invalid = json_request(signed_in, "post", COLLECTION, {"content": document("")})
    validate_response(invalid, COLLECTION, "post", 400)
    validate_response(signed_in.get(COLLECTION + "?page=0"), COLLECTION, "get", 404)
    missing = "/api/v1/notes/00000000-0000-0000-0000-000000000000/"
    validate_response(signed_in.get(missing), DETAIL, "get", 404)
    csrf = signed_in.post(COLLECTION, payload, content_type="application/json")
    validate_response(csrf, COLLECTION, "post", 403)
    assert csrf.json()["error"]["code"] == "permission_denied"
    malformed = signed_in.post(
        COLLECTION,
        "{",
        content_type="application/json",
        HTTP_X_CSRFTOKEN=signed_in.cookies["csrftoken"].value,
    )
    validate_response(malformed, COLLECTION, "post", 400)
    assert malformed.json()["error"]["code"] == "parse_error"
    unsupported = signed_in.post(
        COLLECTION,
        "text",
        content_type="text/plain",
        HTTP_X_CSRFTOKEN=signed_in.cookies["csrftoken"].value,
    )
    validate_response(unsupported, COLLECTION, "post", 415)
    assert unsupported.json()["error"]["code"] == "unsupported_media_type"
    validate_response(
        signed_in.put(
            path,
            {},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=signed_in.cookies["csrftoken"].value,
        ),
        DETAIL,
        "patch",
        405,
    )


def test_schema_is_available_to_the_signed_in_owner(signed_in):
    response = signed_in.get("/api/v1/schema/?format=json")
    assert response.status_code == 200
    assert response.json() == SCHEMA


def test_note_lifecycle_contract_matches_http(signed_in):
    captured = json_request(
        signed_in, "post", COLLECTION, {"content": document("A recoverable thought.")}
    )
    path = captured["Location"]
    trash = COLLECTION + "trash/"
    restore = "restore/"
    purge = "delete-permanently/"
    headers = {"HTTP_X_CSRFTOKEN": signed_in.cookies["csrftoken"].value}

    wrong_state = signed_in.delete(path + purge, **headers)
    validate_response(wrong_state, DETAIL + purge, "delete", 409)
    assert wrong_state.json()["error"]["code"] == "invalid_note_state"
    malformed = signed_in.delete(path, "{", content_type="application/json", **headers)
    validate_response(malformed, DETAIL, "delete", 400)
    assert malformed.json()["error"]["code"] == "parse_error"
    validate_response(signed_in.get(path), DETAIL, "get", 200)
    assert signed_in.delete(path, **headers).status_code == 204
    validate_response(signed_in.get(path), DETAIL, "get", 404)
    validate_response(signed_in.get(trash), trash, "get", 200)
    unexpected = json_request(signed_in, "delete", path + purge, {"confirm": False})
    validate_response(unexpected, DETAIL + purge, "delete", 400)
    assert signed_in.get(trash).json()["count"] == 1
    assert (
        signed_in.post(
            path + restore, content_type="application/json", **headers
        ).status_code
        == 204
    )
    assert signed_in.delete(path, **headers).status_code == 204
    assert signed_in.delete(path + purge, **headers).status_code == 204

    for route, method in (
        (DETAIL, "delete"),
        (DETAIL + restore, "post"),
        (DETAIL + purge, "delete"),
    ):
        operation = SCHEMA["paths"][route][method]
        assert "requestBody" not in operation
        assert "content" not in operation["responses"]["204"]


def test_book_and_source_contracts_match_real_requests_and_responses(signed_in):
    books = "/api/v1/books/"
    detail = "/api/v1/books/{book_id}/"
    book_notes = "/api/v1/books/{book_id}/notes/"
    payload = {"title": "A documented book"}
    validate_request(payload, books, "post")
    response = json_request(signed_in, "post", books, payload)
    validate_response(response, books, "post", 201)
    book = response.json()
    path = response["Location"]
    validate_response(signed_in.get(path), detail, "get", 200)
    validate_response(signed_in.get(books), books, "get", 200)
    payload = {"author": "A documented author"}
    validate_request(payload, detail, "patch")
    validate_response(
        json_request(signed_in, "patch", path, payload), detail, "patch", 200
    )
    payload = {
        "content": document("A sourced thought."),
        "book": book["id"],
        "page_number": 42,
        "source_reference": "pp. 42–44",
    }
    validate_request(payload, COLLECTION, "post")
    response = json_request(signed_in, "post", COLLECTION, payload)
    validate_response(response, COLLECTION, "post", 201)
    note_path = response["Location"]
    assert response.json()["book"] == book["id"]
    assert response.json()["page_number"] == 42
    assert response.json()["source_reference"] == "pp. 42–44"
    validate_response(signed_in.get(path + "notes/?order=page"), book_notes, "get", 200)
    payload = {"book": None, "page_number": None, "source_reference": "", "revision": 1}
    validate_request(payload, DETAIL, "patch")
    response = json_request(signed_in, "patch", note_path, payload)
    validate_response(response, DETAIL, "patch", 200)
    assert response.json()["book"] is None
    validate_response(
        json_request(signed_in, "patch", note_path, payload), DETAIL, "patch", 409
    )
    validate_response(
        json_request(signed_in, "post", books, {"title": ""}), books, "post", 400
    )
    validate_response(
        json_request(signed_in, "patch", path, {"title": ""}), detail, "patch", 400
    )
    validate_response(signed_in.get(books + "?page=0"), books, "get", 404)
    validate_response(
        signed_in.get(path + "notes/?order=invalid"), book_notes, "get", 404
    )
    missing = "/api/v1/books/00000000-0000-0000-0000-000000000000/"
    validate_response(signed_in.get(missing), detail, "get", 404)
    validate_response(signed_in.get(missing + "notes/"), book_notes, "get", 404)
    validate_response(
        json_request(signed_in, "patch", missing, {"title": "Missing"}),
        detail,
        "patch",
        404,
    )
    foreign_source = json_request(
        signed_in,
        "post",
        COLLECTION,
        {
            "content": document("Rejected."),
            "book": "00000000-0000-0000-0000-000000000000",
        },
    )
    validate_response(foreign_source, COLLECTION, "post", 400)
    operation = SCHEMA["paths"][detail]["delete"]
    assert "requestBody" not in operation
    assert "content" not in operation["responses"]["204"]
    validate_response(
        json_request(signed_in, "delete", path, {"title": "Unexpected"}),
        detail,
        "delete",
        400,
    )
    validate_response(signed_in.delete(path), detail, "delete", 403)
    headers = {"HTTP_X_CSRFTOKEN": signed_in.cookies["csrftoken"].value}
    removed = signed_in.delete(path, **headers)
    assert removed.status_code == 204
    assert not removed.content
    validate_response(signed_in.delete(path, **headers), detail, "delete", 404)


def test_formatted_content_contract_matches_both_deliveries(signed_in):
    from test_formatted_notes_http import paragraph, rich_document

    payload = {
        "content": rich_document(
            {
                "type": "blockquote",
                "content": [paragraph("Quoted", [{"type": "italic"}])],
            },
            {
                "type": "orderedList",
                "attrs": {"start": 2},
                "content": [
                    {"type": "listItem", "content": [paragraph("An observation")]},
                ],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "First", "marks": [{"type": "bold"}]},
                    {
                        "type": "hardBreak",
                        "marks": [{"type": "bold"}, {"type": "italic"}],
                    },
                    {"type": "text", "text": "Second", "marks": [{"type": "bold"}]},
                ],
            },
            paragraph(
                "Website", [{"type": "link", "attrs": {"href": "http://example.org/"}}]
            ),
        ),
    }
    validate_request(payload, COLLECTION, "post")
    response = json_request(signed_in, "post", COLLECTION, payload)
    validate_response(response, COLLECTION, "post", 201)
    path = response["Location"]
    validate_response(signed_in.get(path), DETAIL, "get", 200)
    validate_response(signed_in.get(COLLECTION), COLLECTION, "get", 200)
    payload = {
        "content": rich_document(paragraph("Revised", [{"type": "bold"}])),
        "revision": 1,
    }
    validate_request(payload, DETAIL, "patch")
    validate_response(
        json_request(signed_in, "patch", path, payload), DETAIL, "patch", 200
    )
    invalid = json_request(
        signed_in,
        "patch",
        path,
        {
            "content": rich_document(
                paragraph(
                    "Unsafe",
                    [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}],
                )
            ),
            "revision": 2,
        },
    )
    validate_response(invalid, DETAIL, "patch", 400)
    assert set(invalid.json()["error"]["fields"]) == {"content"}


def test_capture_retry_contract_matches_real_responses(signed_in):
    payload = {
        "content": document("A documented retry."),
        "capture_id": "083e06ee-785a-4110-8b5e-02d46aa85fd4",
    }
    validate_request(payload, COLLECTION, "post")
    response = json_request(signed_in, "post", COLLECTION, payload)
    validate_response(response, COLLECTION, "post", 201)
    replay = json_request(signed_in, "post", COLLECTION, payload)
    validate_response(replay, COLLECTION, "post", 200)
    assert replay["Location"] == response["Location"]
    conflict = json_request(
        signed_in, "post", COLLECTION, {**payload, "content": document("Other input.")}
    )
    validate_response(conflict, COLLECTION, "post", 409)
    assert conflict.json()["error"]["code"] == "capture_conflict"


def test_chapter_contract_matches_real_requests_and_responses(signed_in):
    book = json_request(
        signed_in, "post", "/api/v1/books/", {"title": "A documented Book"}
    ).json()
    chapters = "/api/v1/books/{book_id}/chapters/"
    chapter_detail = chapters + "{chapter_id}/"
    path = chapters.format(book_id=book["id"])
    payload = {"label": "Prologue"}
    validate_request(payload, chapters, "post")
    response = json_request(signed_in, "post", path, payload)
    validate_response(response, chapters, "post", 201)
    chapter = response.json()
    validate_response(signed_in.get(path), chapters, "get", 200)
    payload = {"position": 1, "label": "1"}
    validate_request(payload, chapter_detail, "patch")
    validate_response(
        json_request(signed_in, "patch", path + chapter["id"] + "/", payload),
        chapter_detail,
        "patch",
        200,
    )
    payload = {
        "content": document("A sourced thought."),
        "book": book["id"],
        "chapter": chapter["id"],
    }
    validate_request(payload, COLLECTION, "post")
    response = json_request(signed_in, "post", COLLECTION, payload)
    validate_response(response, COLLECTION, "post", 201)
    assert response.json()["chapter_label"] == "1"
    validate_response(
        signed_in.get(path.replace("chapters/", "notes/?order=chapter")),
        "/api/v1/books/{book_id}/notes/",
        "get",
        200,
    )


def test_topic_contract_matches_real_http_requests_and_responses(signed_in):
    topics = "/api/v1/topics/"
    detail = topics + "{topic_id}/"
    payload = {"label": "Humanities", "parent": None}
    validate_request(payload, topics, "post")
    response = json_request(signed_in, "post", topics, payload)
    validate_response(response, topics, "post", 201)
    topic = response.json()
    path = response["Location"]
    validate_response(signed_in.get(path), detail, "get", 200)
    validate_response(signed_in.get(topics + "?q=human"), topics, "get", 200)
    payload = {"label": "Arts"}
    validate_request(payload, detail, "patch")
    validate_response(
        json_request(signed_in, "patch", path, payload), detail, "patch", 200
    )
    payload = {
        "content": document("A thought about art."),
        "topic_changes": [{"action": "assign", "topic": topic["id"]}],
    }
    validate_request(payload, COLLECTION, "post")
    response = json_request(signed_in, "post", COLLECTION, payload)
    validate_response(response, COLLECTION, "post", 201)
    path = response["Location"]
    payload = {
        "revision": 1,
        "topic_changes": [{"action": "unassign", "topic": topic["id"]}],
    }
    validate_request(payload, DETAIL, "patch")
    validate_response(
        json_request(signed_in, "patch", path, payload), DETAIL, "patch", 200
    )


def test_topic_browsing_and_book_group_contracts_match_real_responses(signed_in):
    book = json_request(
        signed_in, "post", "/api/v1/books/", {"title": "A documented Book"}
    ).json()
    topic = json_request(signed_in, "post", "/api/v1/topics/", {"label": "Arts"}).json()
    for changes in ([{"action": "assign", "topic": topic["id"]}], []):
        response = json_request(
            signed_in,
            "post",
            COLLECTION,
            {
                "content": document("An observation"),
                "book": book["id"],
                "topic_changes": changes,
            },
        )
        assert response.status_code == 201

    topic_notes = "/api/v1/topics/{topic_id}/notes/"
    notes_path = topic_notes.format(topic_id=topic["id"])
    validate_response(signed_in.get(notes_path), topic_notes, "get", 200)
    validate_response(
        signed_in.get(notes_path + "?mode=direct"), topic_notes, "get", 200
    )
    validate_response(
        signed_in.get(notes_path + "?mode=invalid"), topic_notes, "get", 404
    )
    groups = "/api/v1/books/{book_id}/note-groups/"
    group_path = groups.format(book_id=book["id"])
    validate_response(signed_in.get(group_path), groups, "get", 200)
    validate_response(signed_in.get(group_path + "?page=0"), groups, "get", 404)


def test_note_link_contract_matches_real_requests_and_responses(signed_in):
    first, second = [
        json_request(signed_in, "post", COLLECTION, {"content": document(text)}).json()[
            "id"
        ]
        for text in ("Original Note.", "Related Note.")
    ]
    candidates = DETAIL + "link-candidates/"
    links = DETAIL + "links/"
    pair = links + "{related_note_id}/"
    link_url = links.format(note_id=first)
    validate_response(
        signed_in.get(candidates.format(note_id=first), {"q": "related"}),
        candidates,
        "get",
        200,
    )
    payload = {"related_note": second}
    validate_request(payload, links, "post")
    validate_response(
        json_request(signed_in, "post", link_url, payload), links, "post", 201
    )
    validate_response(signed_in.get(links.format(note_id=second)), links, "get", 200)
    validate_response(
        json_request(signed_in, "post", link_url, payload), links, "post", 409
    )
    validate_response(
        json_request(signed_in, "post", link_url, {"related_note": first}),
        links,
        "post",
        400,
    )
    url = pair.format(note_id=second, related_note_id=first)
    removed = signed_in.delete(
        url, HTTP_X_CSRFTOKEN=signed_in.cookies["csrftoken"].value
    )
    assert removed.status_code == 204 and removed.content == b""
    assert "content" not in SCHEMA["paths"][pair]["delete"]["responses"]["204"]
    validate_response(json_request(signed_in, "delete", url, {}), pair, "delete", 404)

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
    payload = {"content": document("A sourced thought."), "book": book["id"]}
    validate_request(payload, COLLECTION, "post")
    response = json_request(signed_in, "post", COLLECTION, payload)
    validate_response(response, COLLECTION, "post", 201)
    note_path = response["Location"]
    assert response.json()["book"] == book["id"]
    validate_response(
        signed_in.get(path + "notes/?order=newest"), book_notes, "get", 200
    )
    payload = {"book": None, "revision": 1}
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

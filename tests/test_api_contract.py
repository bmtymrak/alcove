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

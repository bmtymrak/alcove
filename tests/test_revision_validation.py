import pytest
from conftest import document, json_request


@pytest.mark.parametrize("revision", [True, False, "1", 1.0, 1.5, None, {}, [], 0, -1])
def test_json_edit_requires_an_integer_revision_without_changing_the_note(
    signed_in, revision
):
    original = json_request(
        signed_in, "post", "/api/v1/notes/", {"content": document("Original.")}
    ).json()
    path = f"/api/v1/notes/{original['id']}/"
    response = json_request(
        signed_in,
        "patch",
        path,
        {"content": document("Pending."), "revision": revision},
    )
    assert response.status_code == 400
    assert "revision" in response.json()["error"]["fields"]
    assert signed_in.get(path).json() == original


@pytest.mark.parametrize("via_html", [False, True])
def test_missing_revision_cannot_change_content_or_source(signed_in, via_html):
    book = json_request(
        signed_in, "post", "/api/v1/books/", {"title": "Keep this source"}
    ).json()
    original = json_request(
        signed_in,
        "post",
        "/api/v1/notes/",
        {"content": document("Keep this thought."), "book": book["id"]},
    ).json()
    path = f"/api/v1/notes/{original['id']}/"
    if via_html:
        response = signed_in.post(
            f"/notes/{original['id']}/edit/",
            {
                "content": "Pending content.",
                "book": "",
                "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
            },
        )
        assert "Pending content." in response.content.decode()
    else:
        response = json_request(
            signed_in,
            "patch",
            path,
            {"content": document("Pending content."), "book": None},
        )
        assert "revision" in response.json()["error"]["fields"]
    assert response.status_code == 400
    assert signed_in.get(path).json() == original


@pytest.mark.parametrize("revision", [9223372036854775807, 10**100])
@pytest.mark.parametrize("via_html", [False, True])
def test_out_of_range_revision_is_a_field_error_without_changing_the_note(
    signed_in,
    revision,
    via_html,
):
    original = json_request(
        signed_in,
        "post",
        "/api/v1/notes/",
        {
            "content": document("Keep the saved thought."),
        },
    ).json()
    path = f"/api/v1/notes/{original['id']}/"
    if via_html:
        response = signed_in.post(
            f"/notes/{original['id']}/edit/",
            {
                "content": "Keep this pending thought.",
                "revision": revision,
                "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
            },
        )
        assert "Keep this pending thought." in response.content.decode()
    else:
        response = json_request(
            signed_in,
            "patch",
            path,
            {
                "content": document("Keep this pending thought."),
                "revision": revision,
            },
        )
        assert "revision" in response.json()["error"]["fields"]
    assert response.status_code == 400
    assert signed_in.get(path).json() == original

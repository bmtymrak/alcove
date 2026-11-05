import pytest
from conftest import document, json_request


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

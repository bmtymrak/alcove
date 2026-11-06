from datetime import datetime
from html import escape
from uuid import UUID

import pytest
from conftest import document, json_request
from django.contrib.auth.models import User
from django.test import Client

from alcove.models import Collection


def test_capture_a_sentence_in_json_and_read_it_in_a_new_session(signed_in):
    response = json_request(
        signed_in,
        "post",
        "/api/v1/notes/",
        {
            "content": document("Attention is the beginning of devotion."),
        },
    )
    assert response.status_code == 201
    saved = response.json()
    assert str(UUID(saved["id"])) == saved["id"]
    assert saved["content"] == document("Attention is the beginning of devotion.")
    assert saved["plain_text"] == "Attention is the beginning of devotion."
    assert saved["revision"] == 1
    assert datetime.fromisoformat(saved["captured_at"].replace("Z", "+00:00")).tzinfo
    assert response["Location"] == f"/api/v1/notes/{saved['id']}/"
    another = Client()
    assert another.login(username="reader", password="Secluded-reading-472!")
    assert another.get(response["Location"]).json() == saved
    listing = another.get("/api/v1/notes/").json()
    assert listing == {"count": 1, "page": 1, "page_size": 20, "results": [saved]}
    assert saved["plain_text"] in another.get(f"/notes/{saved['id']}/").content.decode()


def test_html_capture_read_and_edit_are_visible_through_json(signed_in):
    text = "A thought with no book, title, topic, or special type."
    response = signed_in.post(
        "/notes/new/",
        {
            "content": text,
            "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
        },
    )
    assert response.status_code == 302
    path = response["Location"]
    before = signed_in.get("/api/v1/notes/").json()["results"][0]
    assert before["plain_text"] == text
    assert text in signed_in.get(path).content.decode()
    response = signed_in.post(
        path + "edit/",
        {
            "content": "Reconsidered after reading.",
            "revision": before["revision"],
            "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
        },
    )
    assert response.status_code == 302
    assert response["Location"] == path
    saved = signed_in.get(f"/api/v1/notes/{before['id']}/").json()
    assert saved["content"] == document("Reconsidered after reading.")
    assert saved["id"] == before["id"]
    assert saved["captured_at"] == before["captured_at"]
    assert saved["updated_at"] >= before["updated_at"]
    assert saved["revision"] == 2


def test_json_edit_is_visible_in_html_and_preserves_original_capture(signed_in):
    note = json_request(
        signed_in,
        "post",
        "/api/v1/notes/",
        {
            "content": document("First thought."),
        },
    ).json()
    response = json_request(
        signed_in,
        "patch",
        f"/api/v1/notes/{note['id']}/",
        {
            "content": document("A better thought.\nWith a second line."),
            "revision": 1,
        },
    )
    assert response.status_code == 200
    saved = response.json()
    assert saved["revision"] == 2
    assert saved["captured_at"] == note["captured_at"]
    assert saved["plain_text"] == "A better thought.\nWith a second line."
    assert (
        saved["plain_text"] in signed_in.get(f"/notes/{note['id']}/").content.decode()
    )


@pytest.mark.parametrize("text", ["", " \n\t", "\u2003\u00a0"])
def test_empty_capture_is_rejected_by_both_paths_without_creating_a_note(
    signed_in, text
):
    response = json_request(
        signed_in,
        "post",
        "/api/v1/notes/",
        {
            "content": document(text),
        },
    )
    assert response.status_code == 400
    assert "content" in response.json()["error"]["fields"]
    response = signed_in.post(
        "/notes/new/",
        {
            "content": text,
            "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
        },
    )
    assert response.status_code == 400
    assert "Write something before saving." in response.content.decode()
    assert signed_in.get("/api/v1/notes/").json()["count"] == 0


@pytest.mark.parametrize("via_html", [False, True])
def test_invalid_edits_leave_saved_content_unchanged(signed_in, via_html):
    note = json_request(
        signed_in,
        "post",
        "/api/v1/notes/",
        {
            "content": document("Keep this thought."),
        },
    ).json()
    path = f"/api/v1/notes/{note['id']}/"
    if via_html:
        response = signed_in.post(
            f"/notes/{note['id']}/edit/",
            {
                "content": "   ",
                "revision": 1,
                "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
            },
        )
    else:
        response = json_request(
            signed_in,
            "patch",
            path,
            {
                "content": document("   "),
                "revision": 1,
            },
        )
    assert response.status_code == 400
    assert signed_in.get(path).json() == note


@pytest.mark.parametrize("via_html", [False, True])
def test_stale_edit_retains_input_and_does_not_overwrite_newer_content(
    signed_in, via_html
):
    note = json_request(
        signed_in,
        "post",
        "/api/v1/notes/",
        {
            "content": document("Original."),
        },
    ).json()
    path = f"/api/v1/notes/{note['id']}/"
    newer = json_request(
        signed_in,
        "patch",
        path,
        {
            "content": document("A newer thought."),
            "revision": 1,
        },
    ).json()
    if via_html:
        response = signed_in.post(
            f"/notes/{note['id']}/edit/",
            {
                "content": "My unsaved thought.",
                "revision": 1,
                "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
            },
        )
        assert "My unsaved thought." in response.content.decode()
        assert "changed elsewhere" in response.content.decode()
    else:
        response = json_request(
            signed_in,
            "patch",
            path,
            {
                "content": document("My unsaved thought."),
                "revision": 1,
            },
        )
        assert response.json()["error"]["code"] == "conflict"
        assert response.json()["error"]["current_revision"] == 2
    assert response.status_code == 409
    assert signed_in.get(path).json() == newer


def test_second_owner_cannot_read_or_change_another_collection(signed_in):
    private = json_request(
        signed_in,
        "post",
        "/api/v1/notes/",
        {
            "content": document("A private thought."),
        },
    ).json()
    second_user = User.objects.create_user("other", password="Different-reading-782!")
    Collection.objects.create(owner=second_user)
    other = Client(enforce_csrf_checks=True)
    other.get("/login/")
    assert (
        other.post(
            "/login/",
            {
                "username": "other",
                "password": "Different-reading-782!",
                "csrfmiddlewaretoken": other.cookies["csrftoken"].value,
            },
        ).status_code
        == 302
    )
    assert "A private thought." not in other.get("/").content.decode()
    assert other.get("/api/v1/notes/").json()["count"] == 0
    for path in [
        f"/notes/{private['id']}/",
        f"/notes/{private['id']}/edit/",
        f"/api/v1/notes/{private['id']}/",
    ]:
        assert other.get(path).status_code == 404
    assert (
        other.post(
            f"/notes/{private['id']}/edit/",
            {
                "content": "Stolen.",
                "revision": 1,
                "csrfmiddlewaretoken": other.cookies["csrftoken"].value,
            },
        ).status_code
        == 404
    )
    assert (
        json_request(
            other,
            "patch",
            f"/api/v1/notes/{private['id']}/",
            {
                "content": document("Stolen."),
                "revision": 1,
            },
        ).status_code
        == 404
    )
    own = json_request(
        other,
        "post",
        "/api/v1/notes/",
        {
            "content": document("Other owner's note."),
        },
    ).json()
    assert other.get("/api/v1/notes/").json()["results"] == [own]
    assert signed_in.get("/api/v1/notes/").json()["results"] == [private]


def test_content_is_displayed_as_text_and_not_executed_as_html(signed_in):
    text = '<script>alert("oops")</script> & <b>thought</b>'
    response = json_request(
        signed_in,
        "post",
        "/api/v1/notes/",
        {
            "content": document(text),
        },
    )
    assert response.status_code == 201
    note = response.json()
    for path in ["/notes/", f"/notes/{note['id']}/", f"/notes/{note['id']}/edit/"]:
        rendered = signed_in.get(path).content.decode()
        assert "<script>" not in rendered
        assert escape(text) in rendered


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"content": None},
        {"content": "A thought."},
        {"content": {"version": 2, "format": "plain-text", "text": "A thought."}},
        {"content": {"version": 1, "format": "html", "text": "<b>A thought.</b>"}},
        {"content": document("A thought."), "collection": "somebody-else"},
        {"content": {**document("A thought."), "script": "unsafe"}},
        {"content": {"version": "1", "format": "plain-text", "text": "A thought."}},
        {"content": {"version": 1, "format": "plain-text", "text": 123}},
        {"content": document("a" * 100_001)},
    ],
)
def test_unsupported_or_invalid_capture_never_creates_a_note(signed_in, payload):
    response = json_request(signed_in, "post", "/api/v1/notes/", payload)
    assert response.status_code == 400
    assert signed_in.get("/api/v1/notes/").json()["count"] == 0


def test_pagination_has_stable_capture_order_and_no_missing_notes(signed_in):
    ids = []
    for number in range(21):
        response = json_request(
            signed_in,
            "post",
            "/api/v1/notes/",
            {
                "content": document(f"Thought {number}."),
            },
        )
        assert response.status_code == 201
        ids.append(response.json()["id"])
    first = signed_in.get("/api/v1/notes/").json()
    second = signed_in.get("/api/v1/notes/?page=2").json()
    assert first["count"] == second["count"] == 21
    assert [n["id"] for n in first["results"]] == ids[:20]
    assert [n["id"] for n in second["results"]] == ids[20:]
    assert "Thought 20." in signed_in.get("/notes/?page=2").content.decode()
    for page in ["0", "3", "oops"]:
        assert signed_in.get(f"/api/v1/notes/?page={page}").status_code == 404

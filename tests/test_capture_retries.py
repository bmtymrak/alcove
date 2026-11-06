from uuid import uuid4

from conftest import PASSWORD, document, json_request
from django.contrib.auth.models import User
from django.test import Client

from alcove.models import Collection

NOTES = "/api/v1/notes/"


def test_capture_retry_replays_the_note_but_distinct_captures_stay_distinct(signed_in):
    payload = {
        "capture_id": str(uuid4()),
        "content": document("A repeated quotation."),
    }
    created = json_request(signed_in, "post", NOTES, payload)
    assert created.status_code == 201

    replay = json_request(signed_in, "post", NOTES, {**payload, "book": None})
    assert replay.status_code == 200
    assert replay["Location"] == created["Location"]
    assert replay.json() == created.json()

    conflict = json_request(
        signed_in, "post", NOTES, {**payload, "content": document("Different input.")}
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "capture_conflict"
    assert signed_in.get(created["Location"]).json() == created.json()

    distinct = json_request(
        signed_in, "post", NOTES, {**payload, "capture_id": str(uuid4())}
    )
    assert distinct.status_code == 201
    assert distinct["Location"] != created["Location"]
    assert signed_in.get(NOTES).json()["count"] == 2


def test_capture_identity_is_shared_by_html_and_json_and_scoped_to_the_owner(signed_in):
    capture_id = str(uuid4())
    text = "My private capture."
    form = {
        "content": text,
        "capture_id": capture_id,
        "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
    }
    created = signed_in.post("/notes/new/", form)
    assert created.status_code == 302
    replay = signed_in.post("/notes/new/", form)
    assert replay["Location"] == created["Location"]
    payload = {"capture_id": capture_id, "content": document(text)}
    json_replay = json_request(signed_in, "post", NOTES, payload)
    assert json_replay.status_code == 200
    assert created["Location"] == f"/notes/{json_replay.json()['id']}/"

    second_user = User.objects.create_user("other-reader", password=PASSWORD)
    Collection.objects.create(owner=second_user)
    other = Client(enforce_csrf_checks=True)
    other.get("/login/")
    assert (
        other.post(
            "/login/",
            {
                "username": second_user.username,
                "password": PASSWORD,
                "csrfmiddlewaretoken": other.cookies["csrftoken"].value,
            },
        ).status_code
        == 302
    )
    other_capture = json_request(
        other, "post", NOTES, {**payload, "content": document("Their private capture.")}
    )
    assert other_capture.status_code == 201
    assert other_capture["Location"] != json_replay["Location"]
    assert other.get(json_replay["Location"]).status_code == 404
    assert signed_in.get(NOTES).json()["count"] == other.get(NOTES).json()["count"] == 1


def test_replaying_after_an_edit_preserves_the_current_note(signed_in):
    payload = {"capture_id": str(uuid4()), "content": document("Original capture.")}
    created = json_request(signed_in, "post", NOTES, payload)
    edited = json_request(
        signed_in,
        "patch",
        created["Location"],
        {"content": document("Revised later."), "revision": 1},
    )
    assert edited.status_code == 200

    replay = json_request(signed_in, "post", NOTES, payload)
    assert replay.status_code == 200
    assert replay.json() == edited.json()
    assert signed_in.get(NOTES).json()["results"] == [edited.json()]

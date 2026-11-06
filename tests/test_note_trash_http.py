from uuid import uuid4

from conftest import PASSWORD, document, json_request
from django.contrib.auth.models import User
from django.test import Client

from alcove.models import Collection


def create(client, path, **fields):
    response = json_request(client, "post", "/api/v1/" + path, fields)
    assert response.status_code == 201
    return response.json()["id"]


def form_post(client, path, **fields):
    return client.post(
        path, {**fields, "csrfmiddlewaretoken": client.cookies["csrftoken"].value}
    )


def test_trash_hides_a_note_from_reading_and_restore_recovers_its_associations(
    signed_in,
):
    book = create(signed_in, "books/", title="Collected essays")
    chapter = create(signed_in, f"books/{book}/chapters/", label="Prologue")
    ideas = create(signed_in, "topics/", label="Ideas")
    writing = create(signed_in, "topics/", label="Writing")
    memory = create(signed_in, "topics/", label="Memory", parent=ideas)
    essays = create(signed_in, "topics/", label="Essays", parent=writing)
    body = "A distinct marginal observation."
    note = create(
        signed_in,
        "notes/",
        content=document(body),
        book=book,
        chapter=chapter,
        page_number=42,
        source_reference="Footnote 2",
        topic_changes=[
            {"action": "assign", "topic": memory},
            {"action": "assign", "topic": essays},
        ],
    )
    related = create(signed_in, "notes/", content=document("A connected thought."))
    picker = create(signed_in, "notes/", content=document("An unlinked thought."))
    detail = f"/api/v1/notes/{note}/"
    links = f"/api/v1/notes/{related}/links/"
    assert (
        json_request(signed_in, "post", links, {"related_note": note}).status_code
        == 201
    )

    lists = [
        ("/api/v1/notes/", "/notes/"),
        (f"/api/v1/books/{book}/notes/?order=chapter", f"/books/{book}/?order=chapter"),
        (f"/api/v1/topics/{ideas}/notes/", f"/topics/{ideas}/"),
        (
            f"/api/v1/topics/{essays}/notes/?mode=direct",
            f"/topics/{essays}/?mode=direct",
        ),
        (links, f"/notes/{related}/"),
        (
            f"/api/v1/notes/{picker}/link-candidates/?q=Prologue",
            f"/notes/{picker}/link/?q=Prologue",
        ),
    ]

    def check_visibility(visible):
        for api, html in lists:
            assert (
                note in {n["id"] for n in signed_in.get(api).json()["results"]}
            ) == visible
            assert (body.encode() in signed_in.get(html).content) == visible
        grouped = signed_in.get(f"/api/v1/books/{book}/note-groups/").json()
        assert grouped["count"] == (2 if visible else 0)
        html = signed_in.get(f"/books/{book}/?order=topic").content
        assert html.count(body.encode()) == (2 if visible else 0)

    check_visibility(True)
    original = signed_in.get(detail).json()
    assert json_request(signed_in, "delete", detail, {}).status_code == 204
    check_visibility(False)
    assert signed_in.get(detail).status_code == 404
    assert signed_in.get(f"/notes/{note}/").status_code == 404
    assert signed_in.get(f"/notes/{note}/edit/").status_code == 404
    assert signed_in.get(detail + "links/").status_code == 404
    (trashed,) = signed_in.get("/api/v1/notes/trash/").json()["results"]
    assert trashed["id"] == note
    assert trashed["trashed_at"]
    assert {t["id"] for t in trashed["topics"]} == {memory, essays}
    assert body.encode() in signed_in.get("/notes/trash/").content

    assert json_request(signed_in, "post", detail + "restore/", {}).status_code == 204
    check_visibility(True)
    restored = signed_in.get(detail).json()
    for key in (
        "id",
        "book",
        "chapter",
        "page_number",
        "source_reference",
        "content",
        "topics",
        "captured_at",
    ):
        assert restored[key] == original[key]
    assert restored["trashed_at"] is None
    assert signed_in.get("/api/v1/notes/trash/").json()["count"] == 0


def test_restore_keeps_survivors_after_topic_removal_and_permanent_note_deletion(
    signed_in,
):
    surviving_topic = create(signed_in, "topics/", label="Surviving topic")
    removed_topic = create(signed_in, "topics/", label="Removed topic")
    note = create(
        signed_in,
        "notes/",
        content=document("A note to restore."),
        topic_changes=[
            {"action": "assign", "topic": topic}
            for topic in (surviving_topic, removed_topic)
        ],
    )
    survivor = create(signed_in, "notes/", content=document("A surviving endpoint."))
    capture = {
        "content": document("An endpoint to erase."),
        "capture_id": str(uuid4()),
    }
    doomed = create(signed_in, "notes/", **capture)
    detail = f"/api/v1/notes/{note}/"
    doomed_detail = f"/api/v1/notes/{doomed}/"
    for target in (survivor, doomed):
        assert (
            json_request(
                signed_in, "post", detail + "links/", {"related_note": target}
            ).status_code
            == 201
        )

    purge = doomed_detail + "delete-permanently/"
    assert json_request(signed_in, "delete", purge, {}).status_code == 409
    assert json_request(signed_in, "delete", detail, {}).status_code == 204
    assert json_request(signed_in, "delete", doomed_detail, {}).status_code == 204

    remove = f"/api/v1/topics/{removed_topic}/remove/"
    payload = {"mode": "remove_subtree"}
    preview = json_request(signed_in, "post", remove + "preview/", payload)
    assert preview.status_code == 200
    (assignment,) = preview.json()["assignments"]
    assert assignment["note"] == note
    assert assignment["note_trashed"] is True
    payload["confirmation"] = preview.json()["confirmation"]
    assert json_request(signed_in, "post", remove, payload).status_code == 204

    retry = json_request(signed_in, "post", "/api/v1/notes/", capture)
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "capture_conflict"
    assert json_request(signed_in, "delete", purge, {}).status_code == 204
    assert (
        json_request(signed_in, "post", doomed_detail + "restore/", {}).status_code
        == 404
    )
    retry = json_request(signed_in, "post", "/api/v1/notes/", capture)
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "capture_conflict"
    assert json_request(signed_in, "post", detail + "restore/", {}).status_code == 204
    restored = signed_in.get(detail).json()
    assert [topic["id"] for topic in restored["topics"]] == [surviving_topic]
    assert restored["plain_text"] == "A note to restore."
    assert [n["id"] for n in signed_in.get(detail + "links/").json()["results"]] == [
        survivor
    ]
    assert signed_in.get("/api/v1/notes/trash/").json()["count"] == 0


def test_lifecycle_actions_enforce_owner_state_and_csrf(signed_in):
    other = User.objects.create_user("other", password=PASSWORD)
    Collection.objects.create(owner=other)
    outsider = Client(enforce_csrf_checks=True)
    outsider.get("/login/")
    assert (
        form_post(outsider, "/login/", username="other", password=PASSWORD).status_code
        == 302
    )
    note = create(signed_in, "notes/", content=document("Private observation."))
    detail = f"/api/v1/notes/{note}/"
    html_detail = f"/notes/{note}/"
    transitions = [
        ("delete", "", "trash/"),
        ("post", "restore/", "restore/"),
        ("delete", "delete-permanently/", "delete-permanently/"),
    ]

    for method, api_action, html_action in transitions:
        assert getattr(Client(), method)(detail + api_action).status_code == 403
        assert (
            getattr(signed_in, method)(
                detail + api_action, content_type="application/json"
            ).status_code
            == 403
        )
        assert signed_in.post(html_detail + html_action).status_code == 403

    original = signed_in.get(detail).json()
    assert json_request(signed_in, "post", detail + "restore/", {}).status_code == 409
    assert form_post(signed_in, html_detail + "restore/").status_code == 409
    assert signed_in.get(html_detail + "delete-permanently/").status_code == 409
    assert signed_in.get(detail).json() == original
    assert form_post(signed_in, html_detail + "trash/").status_code == 302
    assert json_request(signed_in, "delete", detail, {}).status_code == 409

    for method, api_action, html_action in transitions:
        assert (
            json_request(outsider, method, detail + api_action, {}).status_code == 404
        )
        assert form_post(outsider, html_detail + html_action).status_code == 404

    assert outsider.get(html_detail + "delete-permanently/").status_code == 404
    assert outsider.get("/api/v1/notes/trash/").json()["count"] == 0
    assert b"Trash is empty." in outsider.get("/notes/trash/").content

    stale_edit = {"revision": original["revision"], "content": document("Stale edit.")}
    assert json_request(signed_in, "patch", detail, stale_edit).status_code == 404
    assert form_post(signed_in, html_detail + "restore/").status_code == 302
    assert json_request(signed_in, "patch", detail, stale_edit).status_code == 409
    assert signed_in.get(detail).json()["plain_text"] == original["plain_text"]

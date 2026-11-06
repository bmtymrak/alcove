from uuid import uuid4

import pytest
from conftest import PASSWORD, document, json_request
from django.contrib.auth.models import User
from django.db import connection
from django.test import Client

from alcove.models import Collection


def create(client, resource, **payload):
    response = json_request(client, "post", f"/api/v1/{resource}/", payload)
    assert response.status_code == 201
    return response.json()


def form_post(client, path, **fields):
    return client.post(
        path, {**fields, "csrfmiddlewaretoken": client.cookies["csrftoken"].value}
    )


@pytest.mark.parametrize("delivery", ["html", "json"])
def test_book_removal_detaches_active_and_trashed_notes(signed_in, delivery):
    book = create(signed_in, "books", title="Obsolete atlas")
    book_api = f"/api/v1/books/{book['id']}/"
    book_html = f"/books/{book['id']}/"
    chapter = create(signed_in, f"books/{book['id']}/chapters", label="Old preface")
    topic = create(signed_in, "topics", label="Cartography")
    source = {
        "book": book["id"],
        "chapter": chapter["id"],
        "page_number": 42,
        "source_reference": "pp. 42–44, footnote 3",
        "topic_changes": [{"action": "assign", "topic": topic["id"]}],
    }
    capture = {
        **source,
        "content": document("A map is a choice."),
        "capture_id": str(uuid4()),
    }
    active = create(signed_in, "notes", **capture)
    trashed = create(signed_in, "notes", **source, content=document("A folded map."))
    related = create(signed_in, "notes", content=document("A different observation."))
    active_api = f"/api/v1/notes/{active['id']}/"
    trash_api = f"/api/v1/notes/{trashed['id']}/"
    related_api = f"/api/v1/notes/{related['id']}/"
    for path in (active_api, trash_api):
        response = json_request(
            signed_in, "post", path + "links/", {"related_note": related["id"]}
        )
        assert response.status_code == 201
    assert json_request(signed_in, "delete", trash_api, {}).status_code == 204
    (trashed,) = signed_in.get("/api/v1/notes/trash/").json()["results"]

    # An unlinked Note can find the active Note by its current source metadata.
    searcher = create(signed_in, "notes", content=document("Find another Note."))
    candidates = f"/api/v1/notes/{searcher['id']}/link-candidates/"
    for query in ("Obsolete atlas", "Old preface", "A map is a choice"):
        results = signed_in.get(candidates, {"q": query}).json()["results"]
        assert [note["id"] for note in results] == [active["id"]]

    if delivery == "html":
        assert b"Remove book" in signed_in.get(book_html).content
        preview = signed_in.get(book_html + "remove/")
        assert preview.status_code == 200
        assert b"Notes will be kept" in preview.content
        assert signed_in.get(book_api).status_code == 200
        response = form_post(signed_in, book_html + "remove/")
        assert response.status_code == 302
        assert response["Location"] == "/"
    else:
        response = json_request(signed_in, "delete", book_api, {})
        assert response.status_code == 204
        assert not response.content
    for path in (
        book_html,
        book_api,
        book_api + "notes/",
        book_api + "chapters/",
    ):
        assert signed_in.get(path).status_code == 404
    assert (
        json_request(
            signed_in,
            "patch",
            book_api + f"chapters/{chapter['id']}/",
            {"label": "New"},
        ).status_code
        == 404
    )
    assert signed_in.get("/api/v1/books/").json()["results"] == []
    assert b"Obsolete atlas" not in signed_in.get("/").content
    for path in ("/notes/new/", f"/notes/{active['id']}/edit/"):
        html = signed_in.get(path).content
        assert book["id"].encode() not in html
        assert chapter["id"].encode() not in html
    for query in ("Obsolete atlas", "Old preface"):
        assert signed_in.get(candidates, {"q": query}).json()["results"] == []
    results = signed_in.get(candidates, {"q": "A map is a choice"}).json()["results"]
    assert [note["id"] for note in results] == [active["id"]]
    assert b"A map is a choice." in signed_in.get("/notes/").content
    topic_api = f"/api/v1/topics/{topic['id']}/notes/"
    assert [n["id"] for n in signed_in.get(topic_api).json()["results"]] == [
        active["id"]
    ]
    assert signed_in.get(trash_api).status_code == 404

    kept_active = signed_in.get(active_api).json()
    (kept_trash,) = signed_in.get("/api/v1/notes/trash/").json()["results"]
    for before, after in ((active, kept_active), (trashed, kept_trash)):
        assert after["book"] is None and after["chapter"] is None
        assert after["revision"] == before["revision"] + 1
        for field in (
            "id",
            "content",
            "plain_text",
            "page_number",
            "source_reference",
            "topics",
            "captured_at",
            "trashed_at",
        ):
            assert after[field] == before[field]
    stale = json_request(
        signed_in, "patch", active_api, {**source, "revision": active["revision"]}
    )
    assert stale.status_code == 409
    stale_html = form_post(
        signed_in,
        f"/notes/{active['id']}/edit/",
        content="Keep this pending edit.",
        book=book["id"],
        chapter=chapter["id"],
        revision=active["revision"],
    )
    assert stale_html.status_code == 409
    assert b"Keep this pending edit." in stale_html.content
    replay = json_request(signed_in, "post", "/api/v1/notes/", capture)
    assert replay.status_code == 200
    assert replay.json() == kept_active

    assert (
        json_request(signed_in, "post", trash_api + "restore/", {}).status_code == 204
    )
    restored = signed_in.get(trash_api).json()
    assert restored["book"] is None and restored["chapter"] is None
    assert restored["trashed_at"] is None
    assert signed_in.get(book_api).status_code == 404
    assert [n["id"] for n in signed_in.get(topic_api).json()["results"]] == [
        active["id"],
        trashed["id"],
    ]
    assert {
        n["id"] for n in signed_in.get(related_api + "links/").json()["results"]
    } == {active["id"], trashed["id"]}
    for path in (active_api, trash_api):
        assert [n["id"] for n in signed_in.get(path + "links/").json()["results"]] == [
            related["id"]
        ]


def test_native_capture_from_a_removed_book_preserves_input_and_retries(signed_in):
    book = create(signed_in, "books", title="A disappearing source")
    book_api = f"/api/v1/books/{book['id']}/"
    capture_page = signed_in.get(f"/books/{book['id']}/notes/new/")
    assert (
        b'<form method="post" action="/notes/new/" class="panel" data-note-editor'
        in (capture_page.content)
    )
    payload = {
        "book": book["id"],
        "capture_id": str(uuid4()),
        "content": "First thought.",
        "add_another": "1",
    }
    assert form_post(signed_in, "/notes/new/", **payload)["Location"].endswith(
        f"/books/{book['id']}/notes/new/"
    )
    assert json_request(signed_in, "delete", book_api, {}).status_code == 204

    replay = form_post(signed_in, "/notes/new/", **payload)
    assert replay.status_code == 302
    assert replay["Location"] == "/notes/new/"
    payload.update(capture_id=str(uuid4()), content="Second thought.")
    rejected = form_post(signed_in, "/notes/new/", **payload)
    assert rejected.status_code == 400
    assert b"Second thought." in rejected.content
    assert b"Choose a Book from your Collection." in rejected.content
    assert signed_in.get("/api/v1/notes/").json()["count"] == 1


def test_failed_book_removal_does_not_modify_the_collection(signed_in):
    book = create(signed_in, "books", title="Private atlas")
    book_api = f"/api/v1/books/{book['id']}/"
    action = f"/books/{book['id']}/remove/"
    chapter = create(signed_in, f"books/{book['id']}/chapters", label="Private preface")
    note = create(
        signed_in,
        "notes",
        book=book["id"],
        chapter=chapter["id"],
        content=document("Private marginalia."),
    )
    other = User.objects.create_user("other", password=PASSWORD)
    Collection.objects.create(owner=other)
    outsider = Client(enforce_csrf_checks=True)
    outsider.get("/login/")
    assert (
        form_post(outsider, "/login/", username="other", password=PASSWORD).status_code
        == 302
    )

    assert Client().delete(book_api).status_code == 403
    assert Client().post(action).status_code == 302
    assert signed_in.delete(book_api).status_code == 403
    assert signed_in.post(action).status_code == 403
    assert outsider.get(action).status_code == 404
    assert form_post(outsider, action).status_code == 404
    assert json_request(outsider, "delete", book_api, {}).status_code == 404
    assert (
        json_request(signed_in, "delete", book_api, {"confirm": True}).status_code
        == 400
    )

    # Fail at the final SQLite delete, after any association updates have run.
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TEMP TRIGGER reject_book_delete BEFORE DELETE ON alcove_book "
            "BEGIN SELECT RAISE(ABORT, 'Book removal failed'); END"
        )
    try:
        signed_in.raise_request_exception = False
        assert json_request(signed_in, "delete", book_api, {}).status_code == 500
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DROP TRIGGER reject_book_delete")
    assert signed_in.get(book_api).json() == book
    assert signed_in.get(book_api + "chapters/").json() == [chapter]
    assert signed_in.get(f"/api/v1/notes/{note['id']}/").json() == note

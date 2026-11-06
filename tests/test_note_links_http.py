from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from conftest import document, json_request
from django.contrib.auth.models import User
from django.db import connections
from django.test import Client

from alcove.models import Collection


def capture(client, text, **fields):
    response = json_request(
        client, "post", "/api/v1/notes/", {"content": document(text), **fields}
    )
    assert response.status_code == 201
    return response.json()


def links(note):
    return f"/api/v1/notes/{note['id']}/links/"


def picker(note):
    return f"/notes/{note['id']}/link/"


def form_post(client, path, **fields):
    return client.post(
        path, {**fields, "csrfmiddlewaretoken": client.cookies["csrftoken"].value}
    )


def test_json_note_link_is_visible_and_removable_from_either_note(signed_in):
    first = capture(signed_in, "The original thought.")
    second = capture(signed_in, "The related thought.")

    created = json_request(
        signed_in, "post", links(first), {"related_note": second["id"]}
    )
    assert created.status_code == 201
    assert created.json() == {"related_note": second["id"]}
    assert signed_in.get(links(first)).json()["results"][0]["id"] == second["id"]
    assert signed_in.get(links(second)).json()["results"][0]["id"] == first["id"]
    assert signed_in.get(f"/api/v1/notes/{second['id']}/").json() == second

    removed = json_request(signed_in, "delete", links(second) + f"{first['id']}/", {})
    assert removed.status_code == 204
    assert signed_in.get(links(first)).json()["results"] == []
    assert signed_in.get(links(second)).json()["results"] == []
    assert signed_in.get(f"/api/v1/notes/{first['id']}/").json() == first


def test_picker_finds_unlinked_notes_by_readable_text_and_context(signed_in):
    book = json_request(
        signed_in, "post", "/api/v1/books/", {"title": "Collected essays"}
    ).json()
    topic = json_request(
        signed_in, "post", "/api/v1/topics/", {"label": "Marginalia"}
    ).json()
    first = capture(signed_in, "An essay about ambiguity.")
    second = capture(
        signed_in,
        "A different ambiguity.",
        book=book["id"],
        topic_changes=[{"action": "assign", "topic": topic["id"]}],
    )
    capture(signed_in, "Unrelated.")
    path = f"/api/v1/notes/{first['id']}/link-candidates/"

    for query in (" ambiguity ", "Collected essays", "Marginalia"):
        response = signed_in.get(path, {"q": query})
        assert response.status_code == 200
        results = response.json()["results"]
        assert [note["id"] for note in results] == [second["id"]]
        assert results[0]["book_title"] == "Collected essays"
        assert results[0]["topics"][0]["full_path"] == "Marginalia"

    assert signed_in.get(path, {"q": "%"}).json()["results"] == []
    html = signed_in.get(picker(first), {"q": "Collected essays"})
    assert html.status_code == 200
    assert b"A different ambiguity." in html.content
    assert b"Collected essays" in html.content
    assert b"Marginalia" in html.content
    assert b"Unrelated." not in html.content
    assert (
        json_request(
            signed_in, "post", links(first), {"related_note": second["id"]}
        ).status_code
        == 201
    )
    assert signed_in.get(path, {"q": "ambiguity"}).json()["results"] == []
    detail = signed_in.get(f"/notes/{first['id']}/")
    assert b"Collected essays" in detail.content
    assert b"Marginalia" in detail.content


def test_invalid_note_links_leave_existing_relationships_and_revisions_intact(
    signed_in,
):
    first = capture(signed_in, "Original.")
    second = capture(signed_in, "Related.")
    third = capture(signed_in, "Unrelated.")
    assert (
        form_post(signed_in, picker(first), related_note=second["id"]).status_code
        == 302
    )

    for source, target, status, code in (
        (first, first, 400, "self_link"),
        (second, first, 409, "duplicate_link"),
    ):
        payload = {"related_note": target["id"]}
        response = json_request(signed_in, "post", links(source), payload)
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        assert form_post(signed_in, picker(source), **payload).status_code == status

    bad_payload = {"related_note": third["id"], "unexpected": True}
    assert json_request(signed_in, "post", links(first), bad_payload).status_code == 400
    missing_pair = links(first) + f"{third['id']}/"
    assert json_request(signed_in, "delete", missing_pair, {}).status_code == 404

    for source, expected_ids in (
        (first, [second["id"]]),
        (second, [first["id"]]),
        (third, []),
    ):
        result = signed_in.get(links(source)).json()
        assert [note["id"] for note in result["results"]] == expected_ids
        assert signed_in.get(f"/api/v1/notes/{source['id']}/").json() == source


def test_note_link_routes_enforce_collection_boundaries_and_csrf(signed_in):
    other = User.objects.create_user("other")
    Collection.objects.create(owner=other)
    outsider = Client()
    outsider.force_login(other)
    outsider.get("/notes/new/")
    hidden = capture(outsider, "A private keyword.")
    companion = capture(outsider, "Another private Note.")
    payload = {"related_note": companion["id"]}
    assert json_request(outsider, "post", links(hidden), payload).status_code == 201

    owned = capture(signed_in, "The visible Note.")
    candidates = f"/api/v1/notes/{owned['id']}/link-candidates/"
    hidden_candidates = f"/api/v1/notes/{hidden['id']}/link-candidates/"
    assert signed_in.get(candidates, {"q": "private"}).json()["count"] == 0
    assert b"A private keyword." not in signed_in.get(picker(owned)).content
    for path in (hidden_candidates, links(hidden), picker(hidden)):
        assert signed_in.get(path).status_code == 404

    for target in (hidden["id"], str(uuid4())):
        response = json_request(
            signed_in, "post", links(owned), {"related_note": target}
        )
        assert response.status_code == 400
        assert response.json()["error"]["fields"] == {
            "related_note": ["Choose a Note from your Collection."]
        }
        assert (
            form_post(signed_in, picker(owned), related_note=target).status_code == 400
        )
        pair = links(owned) + f"{target}/"
        assert json_request(signed_in, "delete", pair, {}).status_code == 404
        assert (
            form_post(
                signed_in, f"/notes/{owned['id']}/links/{target}/remove/"
            ).status_code
            == 404
        )

    assert json_request(signed_in, "post", links(hidden), payload).status_code == 404
    assert form_post(signed_in, picker(hidden), **payload).status_code == 404
    hidden_pair = links(hidden) + f"{companion['id']}/"
    assert json_request(signed_in, "delete", hidden_pair, {}).status_code == 404
    hidden_remove = f"/notes/{hidden['id']}/links/{companion['id']}/remove/"
    assert form_post(signed_in, hidden_remove).status_code == 404
    assert outsider.get(links(hidden)).json()["count"] == 1
    assert signed_in.get(links(owned)).json()["count"] == 0

    assert Client().get(candidates).status_code == 403
    assert Client().get(picker(owned)).status_code == 302
    assert signed_in.post(picker(owned), payload).status_code == 403
    assert (
        signed_in.post(
            links(owned), payload, content_type="application/json"
        ).status_code
        == 403
    )
    assert signed_in.delete(links(owned) + f"{hidden['id']}/").status_code == 403


@pytest.mark.django_db(transaction=True)
def test_simultaneous_reversed_requests_create_one_note_link(signed_in):
    first = capture(signed_in, "Original.")
    second = capture(signed_in, "Related.")
    ready = Barrier(2)

    def link(pair):
        source, target = pair
        client = Client(enforce_csrf_checks=True)
        client.cookies = signed_in.cookies.copy()
        try:
            ready.wait(timeout=10)
            return json_request(
                client, "post", links(source), {"related_note": target["id"]}
            )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(link, [(first, second), (second, first)]))
    assert sorted(response.status_code for response in responses) == [201, 409]
    for source, target in [(first, second), (second, first)]:
        result = signed_in.get(links(source)).json()
        assert [note["id"] for note in result["results"]] == [target["id"]]

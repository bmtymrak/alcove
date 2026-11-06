import re
from html import unescape

from conftest import document, json_request
from django.contrib.auth.models import User
from django.test import Client
from test_topic_browsing_http import NOTES, capture, create_book
from test_topic_reorganization_http import topic_url
from test_topics_http import create_topic

from alcove.models import Collection


def search(client, **params):
    response = client.get(NOTES, params)
    assert response.status_code == 200
    return response.json()


def test_search_matches_readable_text_book_titles_and_assigned_topic_labels(signed_in):
    book = create_book(signed_in, "Collected Essays")
    topic = create_topic(signed_in, "Perception")
    found = capture(signed_in, "A reflection on distance.", topic, book=book)
    capture(signed_in, "An unrelated thought.")

    for query in ("reflection", "essays", "perception", "distance essays perception"):
        assert search(signed_in, q=query)["results"] == [found]
    assert search(signed_in, q="reflection unrelated")["results"] == []


def test_search_combines_filters_with_direct_or_descendant_membership(signed_in):
    book = create_book(signed_in, "Selected Essays")
    other_book = create_book(signed_in, "Other Essays")
    parent = create_topic(signed_in, "Arts")
    child = create_topic(signed_in, "Painting", parent["id"])
    leaf = create_topic(signed_in, "Landscapes", child["id"])
    sibling = create_topic(signed_in, "Music", parent["id"])
    direct = capture(signed_in, "Looking at the hills.", parent, book=book)
    descendant = capture(signed_in, "Hills and rivers.", leaf, sibling, book=book)
    capture(signed_in, "Trees and rivers.", leaf, book=book)
    capture(signed_in, "Hills in another Book.", leaf, book=other_book)
    capture(signed_in, "Hills without Topics.", book=book)

    filters = {"q": "hills", "book": book["id"], "topic": parent["id"]}
    assert search(signed_in, **filters)["results"] == [direct, descendant]
    assert search(signed_in, **filters, mode="direct")["results"] == [direct]
    html = signed_in.get("/notes/", {**filters, "mode": "direct"}).content
    assert b"Looking at the hills." in html
    assert b"Hills and rivers." not in html
    assert b"Arts \xe2\x80\xba Painting \xe2\x80\xba Landscapes" in html


def test_search_treats_unicode_and_punctuation_as_ordinary_words(signed_in):
    note = capture(signed_in, 'Café — МОСКВА. A "draft" OR a sketch.')
    capture(signed_in, "Another café.")
    capture(signed_in, "Sketchbook and sketch.")

    for query in ("«cafe», (москва)!", "cafe\u0301—Москва", '"draft" OR sketch*'):
        assert search(signed_in, q=query)["results"] == [note]
    assert search(signed_in, q="draft OR sketchbook")["results"] == []
    assert search(signed_in, q='"*():-')["results"] == []


def test_search_updates_after_edits_renames_and_book_removal(signed_in):
    book = create_book(signed_in, "Antique Atlas")
    old_topic = create_topic(signed_in, "Geography")
    new_topic = create_topic(signed_in, "Navigation")
    note = capture(signed_in, "An old harbor.", old_topic, book=book)
    note_url = NOTES + note["id"] + "/"
    book_url = f"/api/v1/books/{book['id']}/"

    assert search(signed_in, q="harbor antique geography")["results"] == [note]
    changed = json_request(
        signed_in,
        "patch",
        note_url,
        {
            "revision": note["revision"],
            "content": document("A new port."),
            "topic_changes": [
                {"action": "unassign", "topic": old_topic["id"]},
                {"action": "assign", "topic": new_topic["id"]},
            ],
        },
    )
    assert changed.status_code == 200
    assert search(signed_in, q="port navigation")["results"] == [changed.json()]
    for query in ("harbor", "geography"):
        assert search(signed_in, q=query)["results"] == []

    for path, payload in (
        (book_url, {"title": "Marine Charts"}),
        (topic_url(new_topic), {"label": "Cartography"}),
    ):
        assert json_request(signed_in, "patch", path, payload).status_code == 200
    for query in ("antique", "navigation"):
        assert search(signed_in, q=query)["results"] == []
    assert search(signed_in, q="marine cartography")["results"] == [
        signed_in.get(note_url).json()
    ]

    assert json_request(signed_in, "delete", book_url, {}).status_code == 204
    assert search(signed_in, q="marine")["results"] == []
    assert search(signed_in, q="port cartography")["results"] == [
        signed_in.get(note_url).json()
    ]


def test_search_follows_topic_moves_promotion_and_subtree_removal(signed_in):
    origin = create_topic(signed_in, "Origin")
    destination = create_topic(signed_in, "Destination")
    branch = create_topic(signed_in, "Travels", origin["id"])
    leaf = create_topic(signed_in, "Journeys", branch["id"])
    note = capture(signed_in, "A thought on ferries.", leaf, destination)
    branch_note = capture(signed_in, "A thought on travel.", branch)
    filters = {"q": "thought", "topic": origin["id"]}
    assert search(signed_in, **filters)["results"] == [note, branch_note]

    def confirm(topic, action, *, resolution=None, **payload):
        preview = json_request(
            signed_in, "post", topic_url(topic, f"{action}/preview/"), payload
        )
        assert preview.status_code == 200
        if resolution is not None:
            payload["resolution"] = resolution
        return json_request(
            signed_in,
            "post",
            topic_url(topic, f"{action}/"),
            {**payload, "confirmation": preview.json()["confirmation"]},
        )

    assert (
        confirm(
            branch, "move", parent=destination["id"], resolution="keep_descendants"
        ).status_code
        == 200
    )
    assert search(signed_in, **filters)["results"] == []
    assert search(signed_in, q="destination")["results"] == []
    assert search(signed_in, q="thought", topic=destination["id"])["count"] == 2

    assert confirm(branch, "remove", mode="promote_children").status_code == 204
    assert search(signed_in, q="travels")["results"] == []
    assert search(signed_in, q="thought", topic=destination["id"])["count"] == 1

    assert confirm(leaf, "remove", mode="remove_subtree").status_code == 204
    assert search(signed_in, q="journeys")["results"] == []
    assert search(signed_in, q="thought", topic=destination["id"])["results"] == []
    assert search(signed_in, q="thought")["count"] == 2


def test_search_excludes_trash_and_indexes_current_labels_on_restore(signed_in):
    book = create_book(signed_in, "An Atlas")
    topic = create_topic(signed_in, "Rivers")
    note = capture(signed_in, "A broad estuary.", topic, book=book)
    note_url = NOTES + note["id"] + "/"
    filters = {"q": "estuary rivers", "book": book["id"], "topic": topic["id"]}
    assert search(signed_in, **filters)["results"] == [note]

    assert json_request(signed_in, "delete", note_url, {}).status_code == 204
    assert search(signed_in, **filters)["results"] == []
    assert b"A broad estuary." not in signed_in.get("/notes/", filters).content
    assert (
        json_request(
            signed_in, "patch", topic_url(topic), {"label": "Tides"}
        ).status_code
        == 200
    )
    assert json_request(signed_in, "post", note_url + "restore/", {}).status_code == 204

    assert search(signed_in, **filters)["results"] == []
    assert search(signed_in, **{**filters, "q": "estuary tides"})["results"] == [
        signed_in.get(note_url).json()
    ]


def test_search_is_private_and_filter_errors_do_not_reveal_other_collections(signed_in):
    other = User.objects.create_user("other")
    Collection.objects.create(owner=other)
    outsider = Client()
    outsider.force_login(other)
    outsider.get("/notes/")
    foreign_book = create_book(outsider, "Private Atlas")
    foreign_topic = create_topic(outsider, "Private Geography")
    capture(outsider, "A thought on islands.", foreign_topic, book=foreign_book)
    own_book = create_book(signed_in, "Own Atlas")
    own = capture(signed_in, "A thought on rivers.", book=own_book)

    assert search(signed_in, q="thought", book=own_book["id"].upper())["results"] == [
        own
    ]
    assert search(signed_in, q="private")["results"] == []
    for path in (NOTES, "/notes/"):
        for params in (
            {"book": foreign_book["id"]},
            {"topic": foreign_topic["id"]},
            {"book": "invalid"},
            {"book": own_book["id"] + "-"},
            {"topic": "invalid"},
            {"mode": "unknown"},
        ):
            assert signed_in.get(path, params).status_code == 404
    assert Client().get(NOTES, {"q": "thought"}).status_code == 403
    assert Client().get("/notes/", {"q": "thought"}).status_code == 302
    html = signed_in.get("/notes/", {"q": "thought"}).content
    assert b"Private Atlas" not in html
    assert b"Private Geography" not in html


def test_search_pages_are_deterministic_and_links_keep_the_filters(signed_in):
    book = create_book(signed_in, "Collected Essays")
    topic = create_topic(signed_in, "Fragments")
    notes = [
        capture(signed_in, f"Journal & fragment {index}", topic, book=book)
        for index in range(21)
    ]
    filters = {
        "q": "journal & fragment",
        "book": book["id"],
        "topic": topic["id"],
        "mode": "direct",
    }
    assert search(signed_in, **filters) == {
        "count": 21,
        "page": 1,
        "page_size": 20,
        "results": notes[:20],
    }
    assert search(signed_in, **filters, page=2)["results"] == notes[20:]
    assert signed_in.get(NOTES, {**filters, "page": 3}).status_code == 404

    first = signed_in.get("/notes/", filters).content.decode()
    next_page = re.search(r'<a href="([^"]+)">Next</a>', first)
    assert next_page
    second = signed_in.get("/notes/" + unescape(next_page[1])).content.decode()
    assert "Page 2 of 2" in second
    assert "Journal &amp; fragment 20" in second
    assert "Journal &amp; fragment 19" not in second
    assert 'value="journal &amp; fragment"' in second
    assert f'value="{book["id"]}" selected' in second
    assert f'value="{topic["id"]}" selected' in second
    assert 'value="direct" selected' in second

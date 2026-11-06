from conftest import document, json_request
from django.contrib.auth.models import User
from django.test import Client
from test_topics_http import change, create_topic

from alcove.models import Collection

BOOKS = "/api/v1/books/"
NOTES = "/api/v1/notes/"


def create_book(client, title):
    response = json_request(client, "post", BOOKS, {"title": title})
    assert response.status_code == 201
    return response.json()


def capture(client, text, *topics, book=None):
    response = json_request(
        client,
        "post",
        NOTES,
        {
            "content": document(text),
            "book": book["id"] if book else None,
            "topic_changes": [change("assign", topic) for topic in topics],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_topic_branch_spans_books_and_standalone_notes_without_assigning_parent(
    signed_in,
):
    arts = create_topic(signed_in, "Arts")
    history = create_topic(signed_in, "History", arts["id"])
    local = create_topic(signed_in, "Local", history["id"])
    music = create_topic(signed_in, "Music", arts["id"])
    sciences = create_topic(signed_in, "Sciences")
    other_history = create_topic(signed_in, "History", sciences["id"])
    first_book = create_book(signed_in, "Ways of Seeing")
    second_book = create_book(signed_in, "Listening")
    shared = capture(signed_in, "Multiple branches", local, music, book=first_book)
    direct = capture(signed_in, "Directly assigned", arts, book=second_book)
    standalone = capture(signed_in, "A standalone thought", history)
    capture(signed_in, "The other History", other_history)
    topic_url = f"/topics/{arts['id']}/"
    api_url = "/api/v1" + topic_url + "notes/"

    branch = signed_in.get(api_url)
    assert branch.status_code == 200
    assert branch.json() == {
        "count": 3,
        "page": 1,
        "page_size": 20,
        "results": [shared, direct, standalone],
    }
    assert signed_in.get(api_url + "?mode=branch").json() == branch.json()
    assert signed_in.get(api_url + "?mode=direct").json()["results"] == [direct]
    assert signed_in.get(NOTES + shared["id"] + "/").json() == shared

    html = signed_in.get(topic_url)
    assert html.status_code == 200
    for text in (
        "Ways of Seeing",
        "Listening",
        "A standalone thought",
        "Arts › History › Local",
        "Sciences › History",
    ):
        assert text in html.content.decode()
    assert "The other History" not in html.content.decode()
    direct_html = signed_in.get(topic_url + "?mode=direct").content.decode()
    assert "Directly assigned" in direct_html
    assert "A standalone thought" not in direct_html
    assert "Sciences › History" in direct_html


def test_book_groups_use_full_paths_and_share_the_same_edited_note(signed_in):
    sciences = create_topic(signed_in, "Sciences")
    science_history = create_topic(signed_in, "History", sciences["id"])
    arts = create_topic(signed_in, "arts")
    art_history = create_topic(signed_in, "History", arts["id"])
    book = create_book(signed_in, "One Book")
    other = create_book(signed_in, "Another Book")
    shared = capture(
        signed_in, "Shared thought", science_history, art_history, book=book
    )
    later = capture(signed_in, "Later thought", art_history, book=book)
    unassigned = capture(signed_in, "No Topic", book=book)
    capture(signed_in, "Another Book's thought", art_history, book=other)
    book_url = f"/books/{book['id']}/"
    api_url = "/api/v1" + book_url + "note-groups/"

    response = signed_in.get(api_url)
    assert response.status_code == 200
    assert response.json() == {
        "count": 4,
        "page": 1,
        "page_size": 20,
        "results": [
            {"topic": art_history, "notes": [shared, later]},
            {"topic": science_history, "notes": [shared]},
            {"topic": None, "notes": [unassigned]},
        ],
    }
    html = signed_in.get(book_url + "?order=topic").content.decode()
    assert (
        html.index('">arts › History</h2>')
        < html.index('">Sciences › History</h2>')
        < html.index('">Unassigned</h2>')
    )
    assert html.count(f'href="/notes/{shared["id"]}/"') == 2
    assert html.count("Shared thought") == 2
    assert "Another Book's thought" not in html
    assert signed_in.get("/api/v1" + book_url + "notes/").json()["count"] == 3

    changed = json_request(
        signed_in,
        "patch",
        NOTES + shared["id"] + "/",
        {"revision": 1, "content": document("Revised thought")},
    )
    assert changed.status_code == 200
    groups = signed_in.get(api_url).json()["results"]
    assert groups[0]["notes"][0] == groups[1]["notes"][0] == changed.json()
    assert (
        signed_in.get(book_url + "?order=topic").content.count(b"Revised thought") == 2
    )


def test_browsing_keeps_order_and_mode_across_page_boundaries(signed_in):
    parent = create_topic(signed_in, "Arts")
    child = create_topic(signed_in, "History", parent["id"])
    book = create_book(signed_in, "Ways of Seeing")
    child_note = capture(signed_in, "A specific thought", child, book=book)
    unassigned = capture(signed_in, "A thought without a Topic", book=book)
    notes = [
        capture(signed_in, f"Thought {index}", parent, book=book) for index in range(21)
    ]
    topic_url = f"/topics/{parent['id']}/"
    book_url = f"/books/{book['id']}/"
    direct_url = "/api/v1" + topic_url + "notes/?mode=direct"
    groups_url = "/api/v1" + book_url + "note-groups/"

    first_page = signed_in.get(direct_url).json()
    assert first_page["count"] == 21
    assert first_page["results"] == notes[:20]
    assert signed_in.get(direct_url + "&page=2").json()["results"] == notes[20:]
    assert (
        b'href="?mode=direct&amp;page=2"'
        in signed_in.get(topic_url + "?mode=direct").content
    )

    first_page = signed_in.get(groups_url).json()
    assert first_page["count"] == 23
    assert first_page["results"] == [{"topic": parent, "notes": notes[:20]}]
    assert signed_in.get(groups_url + "?page=2").json()["results"] == [
        {"topic": parent, "notes": notes[20:]},
        {"topic": child, "notes": [child_note]},
        {"topic": None, "notes": [unassigned]},
    ]
    assert (
        b'href="?order=topic&amp;page=2"'
        in signed_in.get(book_url + "?order=topic").content
    )
    assert signed_in.get(groups_url + "?page=3").status_code == 404


def test_topic_browsing_and_book_grouping_require_collection_access(signed_in):
    other = User.objects.create_user("other")
    Collection.objects.create(owner=other)
    outsider = Client()
    outsider.force_login(other)
    outsider.get("/topics/")
    foreign_topic = create_topic(outsider, "Private Topic")
    foreign_book = create_book(outsider, "Private Book")
    capture(outsider, "Private Note", foreign_topic, book=foreign_book)
    own_topic = create_topic(signed_in, "My Topic")
    own_book = create_book(signed_in, "My Book")

    topic_url = f"/topics/{foreign_topic['id']}/"
    book_url = f"/books/{foreign_book['id']}/"
    for path in (topic_url, book_url + "?order=topic"):
        assert signed_in.get(path).status_code == 404
        assert Client().get(path).status_code == 302
    for path in (topic_url + "notes/", book_url + "note-groups/"):
        assert signed_in.get("/api/v1" + path).status_code == 404
        assert Client().get("/api/v1" + path).status_code == 403

    own_topic_url = f"/topics/{own_topic['id']}/"
    own_groups_url = f"/api/v1/books/{own_book['id']}/note-groups/"
    assert b"Private Topic" not in signed_in.get(own_topic_url).content
    assert signed_in.get("/api/v1" + own_topic_url + "notes/").json()["results"] == []
    assert signed_in.get(own_groups_url).json()["results"] == []

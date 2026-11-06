import pytest
from conftest import document, json_request
from django.contrib.auth.models import User
from django.test import Client
from test_api_contract import validate_request, validate_response
from test_topics_http import TOPICS, change, create_topic, form_post

from alcove.models import Collection


def capture_note(client, *assigned, **fields):
    saved = json_request(
        client,
        "post",
        "/api/v1/notes/",
        {
            "content": document("A thought worth keeping."),
            "page_number": 42,
            "source_reference": "pp. 42–44",
            "topic_changes": [change("assign", topic) for topic in assigned],
            **fields,
        },
    )
    assert saved.status_code == 201
    return saved["Location"], saved.json()


def topic_url(topic, action=""):
    return f"{TOPICS}{topic['id']}/" + action


@pytest.mark.parametrize(
    ("resolution", "remaining"),
    [("keep_descendants", "Detail"), ("keep_ancestors", "Destination")],
)
def test_move_previews_conflicts_and_requires_an_explicit_resolution(
    signed_in, resolution, remaining
):
    branch = create_topic(signed_in, "Branch")
    detail = create_topic(signed_in, "Detail", branch["id"])
    destination = create_topic(signed_in, "Destination")
    unrelated = create_topic(signed_in, "Unrelated")
    note_url, original = capture_note(signed_in, detail, destination, unrelated)
    payload = {"parent": destination["id"]}
    preview_url = topic_url(branch, "move/preview/")
    preview_schema = "/api/v1/topics/{topic_id}/move/preview/"
    validate_request(payload, preview_schema, "post")
    response = json_request(signed_in, "post", preview_url, payload)
    validate_response(response, preview_schema, "post", 200)
    preview = response.json()
    assert [entry["new_path"] for entry in preview["topics"]] == [
        "Destination › Branch",
        "Destination › Branch › Detail",
    ]
    [conflict] = preview["assignments"]
    assert conflict["note"] == original["id"]
    assert conflict["topic"]["id"] == detail["id"]
    assert conflict["ancestor"]["id"] == destination["id"]
    assert signed_in.get(note_url).json() == original

    move_url = topic_url(branch, "move/")
    assert json_request(signed_in, "post", move_url, payload).status_code == 400
    payload["confirmation"] = preview["confirmation"]
    assert json_request(signed_in, "post", move_url, payload).status_code == 400
    assert signed_in.get(note_url).json() == original
    assert signed_in.get(topic_url(detail)).json()["full_path"] == "Branch › Detail"

    payload["resolution"] = resolution
    move_schema = "/api/v1/topics/{topic_id}/move/"
    validate_request(payload, move_schema, "post")
    validate_response(
        json_request(signed_in, "post", move_url, payload), move_schema, "post", 200
    )
    result = signed_in.get(note_url).json()
    assert [entry["label"] for entry in result["topics"]] == [remaining, "Unrelated"]
    assert result["content"] == original["content"]
    assert result["source_reference"] == original["source_reference"]
    assert result["revision"] == original["revision"] + 1
    assert (
        json_request(
            signed_in,
            "patch",
            note_url,
            {"revision": original["revision"], "content": document("Stale edit.")},
        ).status_code
        == 409
    )
    assert signed_in.get(TOPICS + "?q=Destination › Branch › Detail").json() == [
        signed_in.get(topic_url(detail)).json()
    ]


def test_promotion_and_subtree_removal_preserve_notes_and_source(signed_in):
    root = create_topic(signed_in, "Arts")
    parent = create_topic(signed_in, "History", root["id"])
    child = create_topic(signed_in, "History", parent["id"])
    grandchild = create_topic(signed_in, "Archives", child["id"])
    unrelated = create_topic(signed_in, "Reading")
    book = json_request(
        signed_in, "post", "/api/v1/books/", {"title": "The Archive"}
    ).json()
    chapter = json_request(
        signed_in, "post", f"/api/v1/books/{book['id']}/chapters/", {"label": "Notes"}
    ).json()
    parent_note, original = capture_note(
        signed_in, parent, unrelated, book=book["id"], chapter=chapter["id"]
    )
    descendant_note, descendant = capture_note(signed_in, grandchild)

    preview_url = topic_url(parent, "remove/preview/")
    remove_url = topic_url(parent, "remove/")
    assert json_request(signed_in, "post", preview_url, {}).status_code == 400
    assert json_request(signed_in, "post", remove_url, {}).status_code == 400
    promotion = {"mode": "promote_children"}
    preview_schema = "/api/v1/topics/{topic_id}/remove/preview/"
    validate_request(promotion, preview_schema, "post")
    response = json_request(signed_in, "post", preview_url, promotion)
    validate_response(response, preview_schema, "post", 200)
    preview = response.json()
    assert [row["new_path"] for row in preview["topics"]] == [
        None,
        "Arts › History",
        "Arts › History › Archives",
    ]
    assert [row["note"] for row in preview["assignments"]] == [original["id"]]
    assert signed_in.get(parent_note).json() == original
    remove_schema = "/api/v1/topics/{topic_id}/remove/"
    promotion["confirmation"] = preview["confirmation"]
    validate_request(promotion, remove_schema, "post")
    wrong_mode = {**promotion, "mode": "remove_subtree"}
    validate_response(
        json_request(signed_in, "post", remove_url, wrong_mode),
        remove_schema,
        "post",
        409,
    )
    assert signed_in.get(descendant_note).json() == descendant

    response = json_request(signed_in, "post", remove_url, promotion)
    assert response.status_code == 204
    assert signed_in.get(topic_url(parent)).status_code == 404
    assert signed_in.get(topic_url(child)).json()["parent"] == root["id"]
    saved = signed_in.get(parent_note).json()
    assert saved["topics"] == [unrelated]
    for field in ("content", "book", "chapter", "page_number", "source_reference"):
        assert saved[field] == original[field]
    assert signed_in.get(descendant_note).json()["topics"][0]["full_path"] == (
        "Arts › History › Archives"
    )

    subtree = {"mode": "remove_subtree"}
    preview = json_request(
        signed_in, "post", topic_url(child, "remove/preview/"), subtree
    ).json()
    assert [row["topic"]["id"] for row in preview["topics"]] == [
        child["id"],
        grandchild["id"],
    ]
    assert all(row["new_path"] is None for row in preview["topics"])
    assert [row["note"] for row in preview["assignments"]] == [descendant["id"]]
    subtree["confirmation"] = preview["confirmation"]
    assert (
        json_request(
            signed_in, "post", topic_url(child, "remove/"), subtree
        ).status_code
        == 204
    )
    assert signed_in.get(topic_url(grandchild)).status_code == 404
    result = signed_in.get(descendant_note).json()
    assert result["topics"] == []
    assert result["content"] == descendant["content"]


def test_move_to_root_updates_every_delivered_path(signed_in):
    root = create_topic(signed_in, "Arts")
    branch = create_topic(signed_in, "History", root["id"])
    leaf = create_topic(signed_in, "Archives", branch["id"])
    book = json_request(
        signed_in, "post", "/api/v1/books/", {"title": "The Archive"}
    ).json()
    note_url, original = capture_note(signed_in, leaf, book=book["id"])
    destination = {"parent": None}
    preview = json_request(
        signed_in, "post", topic_url(branch, "move/preview/"), destination
    ).json()
    assert preview["assignments"] == []
    assert (
        json_request(
            signed_in,
            "post",
            topic_url(branch, "move/"),
            {**destination, "confirmation": preview["confirmation"]},
        ).status_code
        == 200
    )

    note = signed_in.get(note_url).json()
    assert note["topics"][0]["full_path"] == "History › Archives"
    assert note["revision"] == original["revision"]
    assert (
        b"History \xe2\x80\xba Archives"
        in signed_in.get(note_url.removeprefix("/api/v1")).content
    )
    assert signed_in.get(TOPICS + "?q=Arts › History").json() == []
    assert signed_in.get(topic_url(root, "notes/")).json()["count"] == 0
    assert signed_in.get(topic_url(branch, "notes/")).json()["count"] == 1
    group = signed_in.get(f"/api/v1/books/{book['id']}/note-groups/").json()
    assert group["results"][0]["topic"]["full_path"] == "History › Archives"


def test_invalid_destinations_leave_the_collection_unchanged(signed_in):
    root = create_topic(signed_in, "Arts")
    child = create_topic(signed_in, "History", root["id"])
    create_topic(signed_in, "History")
    note_url, original = capture_note(signed_in, child)
    before = signed_in.get(TOPICS).json()
    for target, destination in [(root, root["id"]), (root, child["id"]), (child, None)]:
        payload = {"parent": destination}
        assert (
            json_request(
                signed_in, "post", topic_url(target, "move/preview/"), payload
            ).status_code
            == 400
        )
        assert (
            json_request(
                signed_in,
                "post",
                topic_url(target, "move/"),
                {**payload, "confirmation": "0" * 64},
            ).status_code
            == 400
        )
    assert (
        json_request(
            signed_in,
            "post",
            topic_url(root, "remove/preview/"),
            {"mode": "promote_children"},
        ).status_code
        == 400
    )
    assert signed_in.get(TOPICS).json() == before
    assert signed_in.get(note_url).json() == original


def test_assignment_added_after_preview_requires_a_fresh_move_preview(signed_in):
    root = create_topic(signed_in, "Arts")
    child = create_topic(signed_in, "History", root["id"])
    destination = create_topic(signed_in, "Culture")
    payload = {"parent": destination["id"]}
    preview_url = topic_url(root, "move/preview/")
    preview = json_request(signed_in, "post", preview_url, payload).json()
    assert preview["assignments"] == []
    note_url, original = capture_note(signed_in, child, destination)
    response = json_request(
        signed_in,
        "post",
        topic_url(root, "move/"),
        {
            **payload,
            "confirmation": preview["confirmation"],
            "resolution": "keep_ancestors",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "stale_preview"
    assert signed_in.get(note_url).json() == original
    assert signed_in.get(topic_url(child)).json()["full_path"] == "Arts › History"
    assert (
        len(json_request(signed_in, "post", preview_url, payload).json()["assignments"])
        == 1
    )


def test_html_uses_the_same_cycle_and_confirmation_rules(signed_in):
    branch = create_topic(signed_in, "Arts")
    child = create_topic(signed_in, "History", branch["id"])
    destination = create_topic(signed_in, "Culture")
    note_url, original = capture_note(signed_in, child, destination)
    move_url = f"/topics/{branch['id']}/move/"
    remove_url = f"/topics/{branch['id']}/remove/"

    cycle = form_post(signed_in, move_url, action="preview", parent=child["id"])
    assert cycle.status_code == 400
    assert b"outside this Topic" in cycle.content
    child_move_url = f"/topics/{child['id']}/move/"
    assert form_post(signed_in, child_move_url, action="preview").status_code == 400
    assert (
        form_post(signed_in, child_move_url, action="preview", parent="").status_code
        == 200
    )
    assert form_post(signed_in, remove_url, action="preview").status_code == 400
    preview = json_request(
        signed_in,
        "post",
        topic_url(branch, "move/preview/"),
        {"parent": destination["id"]},
    ).json()
    rejected = form_post(
        signed_in,
        move_url,
        action="apply",
        parent=destination["id"],
        confirmation=preview["confirmation"],
    )
    assert rejected.status_code == 400
    assert b"Choose which conflicting Topic Assignments to keep" in rejected.content
    assert signed_in.get(note_url).json() == original

    before = signed_in.get(TOPICS).json()
    removal = {"mode": "remove_subtree"}
    preview = json_request(
        signed_in, "post", topic_url(branch, "remove/preview/"), removal
    ).json()
    added_note, added = capture_note(signed_in, branch)
    rejected = form_post(
        signed_in,
        remove_url,
        action="apply",
        confirmation=preview["confirmation"],
        **removal,
    )
    assert rejected.status_code == 409
    assert b"Preview it again" in rejected.content
    assert signed_in.get(TOPICS).json() == before
    assert signed_in.get(added_note).json() == added


def test_reorganization_requires_the_owning_collection_and_csrf(signed_in):
    owner = User.objects.create_user("other")
    Collection.objects.create(owner=owner)
    other = Client()
    other.force_login(owner)
    hidden = other.post(
        TOPICS, {"label": "Private"}, content_type="application/json"
    ).json()
    owned = create_topic(signed_in, "Owned")

    for action, payload in [
        ("move/preview/", {"parent": owned["id"]}),
        ("move/", {"parent": owned["id"], "confirmation": "0" * 64}),
        ("remove/preview/", {"mode": "remove_subtree"}),
        ("remove/", {"mode": "remove_subtree", "confirmation": "0" * 64}),
    ]:
        assert (
            json_request(
                signed_in, "post", topic_url(hidden, action), payload
            ).status_code
            == 404
        )
        url = topic_url(owned, action)
        assert (
            Client().post(url, payload, content_type="application/json").status_code
            == 403
        )
        assert (
            signed_in.post(url, payload, content_type="application/json").status_code
            == 403
        )

    for action in ["move/", "remove/"]:
        hidden_url = f"/topics/{hidden['id']}/{action}"
        assert signed_in.get(hidden_url).status_code == 404
        assert form_post(signed_in, hidden_url, action="preview").status_code == 404
        assert signed_in.post(f"/topics/{owned['id']}/{action}").status_code == 403
    payload = {"parent": hidden["id"]}
    assert (
        json_request(
            signed_in, "post", topic_url(owned, "move/preview/"), payload
        ).status_code
        == 400
    )
    assert (
        form_post(
            signed_in, f"/topics/{owned['id']}/move/", action="preview", **payload
        ).status_code
        == 400
    )
    assert other.get(TOPICS).json() == [hidden]
    assert signed_in.get(TOPICS).json() == [owned]

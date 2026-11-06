from conftest import document, json_request

TOPICS = "/api/v1/topics/"


def create_topic(client, label, parent=None):
    response = json_request(client, "post", TOPICS, {"label": label, "parent": parent})
    assert response.status_code == 201
    return response.json()


def test_topics_can_share_a_label_under_different_parents_and_show_full_paths(
    signed_in,
):
    arts = create_topic(signed_in, "Arts")
    sciences = create_topic(signed_in, "Sciences")
    arts_history = create_topic(signed_in, "History", arts["id"])
    create_topic(signed_in, "History", sciences["id"])

    assert arts_history["full_path"] == "Arts › History"
    response = json_request(
        signed_in, "patch", f"{TOPICS}{arts['id']}/", {"label": "Humanities"}
    )
    assert response.status_code == 200
    assert [
        topic["full_path"] for topic in signed_in.get(TOPICS + "?q=history").json()
    ] == [
        "Humanities › History",
        "Sciences › History",
    ]
    tree = signed_in.get("/topics/")
    assert tree.status_code == 200
    assert "Humanities › History" in tree.content.decode()
    renamed = form_post(
        signed_in, f"/topics/{arts_history['id']}/rename/", label="Cultural History"
    )
    assert renamed.status_code == 302
    assert "Humanities › Cultural History" in signed_in.get("/topics/").content.decode()


def change(action, topic):
    return {"action": action, "topic": topic["id"]}


def test_ordered_assignment_changes_keep_independent_branches(signed_in):
    arts = create_topic(signed_in, "Arts")
    history = create_topic(signed_in, "History", arts["id"])
    music = create_topic(signed_in, "Music", arts["id"])
    sciences = create_topic(signed_in, "Sciences")
    captured = json_request(
        signed_in,
        "post",
        "/api/v1/notes/",
        {
            "content": document("A note across branches."),
            "topic_changes": [
                change("assign", arts),
                change("assign", history),
                change("assign", music),
                change("assign", sciences),
            ],
        },
    )
    assert captured.status_code == 201
    path = captured["Location"]
    assert [entry["full_path"] for entry in captured.json()["topics"]] == [
        "Arts › History",
        "Arts › Music",
        "Sciences",
    ]
    response = json_request(
        signed_in,
        "patch",
        path,
        {
            "revision": captured.json()["revision"],
            "topic_changes": [change("assign", arts), change("unassign", sciences)],
        },
    )
    assert response.status_code == 200
    assert [entry["full_path"] for entry in signed_in.get(path).json()["topics"]] == [
        "Arts"
    ]
    assert "Arts" in signed_in.get(path.removeprefix("/api/v1")).content.decode()


def form_post(client, path, **fields):
    return client.post(
        path, {"csrfmiddlewaretoken": client.cookies["csrftoken"].value, **fields}
    )


def test_duplicate_labels_and_reparenting_are_rejected(signed_in):
    root = create_topic(signed_in, "Arts")
    child = create_topic(signed_in, "History", root["id"])
    other_child = create_topic(signed_in, "Music", root["id"])

    create_topic(signed_in, "Reading Notes")
    for label, parent in [
        (" arts ", None),
        ("HISTORY", root["id"]),
        ("Reading  Notes", None),
    ]:
        assert (
            json_request(
                signed_in, "post", TOPICS, {"label": label, "parent": parent}
            ).status_code
            == 400
        )
    assert (
        json_request(
            signed_in, "patch", f"{TOPICS}{other_child['id']}/", {"label": "history"}
        ).status_code
        == 400
    )
    root_path = f"{TOPICS}{root['id']}/"
    assert (
        json_request(
            signed_in, "patch", root_path, {"label": "Moved", "parent": child["id"]}
        ).status_code
        == 400
    )
    assert (
        form_post(
            signed_in,
            f"/topics/{root['id']}/rename/",
            label="Moved",
            parent=child["id"],
        ).status_code
        == 400
    )
    assert signed_in.get(root_path).json()["full_path"] == "Arts"


def test_topic_routes_and_suggestions_are_collection_scoped(signed_in):
    from django.contrib.auth.models import User
    from django.test import Client

    from alcove.models import Collection

    other = User.objects.create_user("other")
    Collection.objects.create(owner=other)
    outsider = Client()
    outsider.force_login(other)
    hidden = outsider.post(
        TOPICS, {"label": "Private Subject"}, content_type="application/json"
    ).json()
    path = f"{TOPICS}{hidden['id']}/"

    assert signed_in.get(TOPICS + "?q=private").json() == []
    assert b"Private Subject" not in signed_in.get("/topics/").content
    assert signed_in.get(path).status_code == 404
    assert (
        json_request(signed_in, "patch", path, {"label": "Changed"}).status_code == 404
    )
    assert signed_in.get(f"/topics/{hidden['id']}/rename/").status_code == 404
    assert (
        form_post(
            signed_in, "/topics/", label="Foreign child", parent=hidden["id"]
        ).status_code
        == 400
    )
    assert (
        json_request(
            signed_in,
            "post",
            TOPICS,
            {"label": "Foreign child", "parent": hidden["id"]},
        ).status_code
        == 400
    )
    assert (
        signed_in.post(
            TOPICS, {"label": "No CSRF"}, content_type="application/json"
        ).status_code
        == 403
    )
    assert Client().get(TOPICS).status_code == 403
    assert (
        json_request(
            signed_in,
            "post",
            "/api/v1/notes/",
            {
                "content": document("Private assignment."),
                "topic_changes": [change("assign", hidden)],
            },
        ).status_code
        == 400
    )
    assert (
        form_post(
            signed_in,
            "/notes/new/",
            content="Private assignment.",
            assign_topics=[hidden["id"]],
        ).status_code
        == 400
    )
    assert signed_in.get("/api/v1/notes/").json()["count"] == 0


def test_invalid_topic_change_rolls_back_the_entire_save(signed_in):
    from uuid import uuid4

    arts = create_topic(signed_in, "Arts")
    history = create_topic(signed_in, "History", arts["id"])
    absent = {"id": str(uuid4())}
    payload = {"content": document("Original"), "capture_id": str(uuid4())}
    note_url = "/api/v1/notes/"
    rejected = [change("assign", history), change("assign", absent)]
    response = json_request(
        signed_in, "post", note_url, {**payload, "topic_changes": rejected}
    )
    assert response.status_code == 400
    assert signed_in.get(note_url).json()["count"] == 0
    payload["topic_changes"] = [change("assign", arts)]
    saved = json_request(signed_in, "post", note_url, payload)
    assert saved.status_code == 201
    path = saved["Location"]
    assert (
        json_request(
            signed_in,
            "patch",
            path,
            {"revision": 1, "content": document("Rejected"), "topic_changes": rejected},
        ).status_code
        == 400
    )
    assert signed_in.get(path).json() == saved.json()

    updated = json_request(
        signed_in,
        "patch",
        path,
        {"revision": 1, "topic_changes": [change("assign", history)]},
    )
    assert updated.status_code == 200
    stale = json_request(
        signed_in,
        "patch",
        path,
        {"revision": 1, "topic_changes": [change("assign", arts)]},
    )
    assert stale.status_code == 409
    replay = json_request(signed_in, "post", note_url, payload)
    assert replay.status_code == 200
    assert replay.json() == updated.json()
    assert [topic["id"] for topic in replay.json()["topics"]] == [history["id"]]
    assert (
        json_request(
            signed_in,
            "post",
            note_url,
            {**payload, "topic_changes": [change("assign", history)]},
        ).status_code
        == 409
    )


def test_html_capture_and_edit_share_assignment_rules(signed_in):
    arts = create_topic(signed_in, "Arts")
    history = create_topic(signed_in, "History", arts["id"])
    created = form_post(
        signed_in,
        "/notes/new/",
        content="An HTML capture.",
        assign_topics=[arts["id"], history["id"]],
    )
    assert created.status_code == 302
    detail = created["Location"]
    assert "Arts › History" in signed_in.get(detail).content.decode()
    edited = form_post(
        signed_in,
        detail + "edit/",
        revision=1,
        content="An HTML capture.",
        assign_topics=[arts["id"]],
    )
    assert edited.status_code == 302
    path = "/api/v1" + detail
    assert [topic["id"] for topic in signed_in.get(path).json()["topics"]] == [
        arts["id"]
    ]
    removed = form_post(
        signed_in,
        detail + "edit/",
        revision=2,
        content="An HTML capture.",
        unassign_topics=[arts["id"]],
    )
    assert removed.status_code == 302
    assert signed_in.get(path).json()["topics"] == []


def test_stale_html_unassignment_returns_a_revision_conflict(signed_in):
    topic = create_topic(signed_in, "Arts")
    captured = form_post(
        signed_in, "/notes/new/", content="A thought.", assign_topics=[topic["id"]]
    )
    detail = captured["Location"]
    path = "/api/v1" + detail
    edited = json_request(
        signed_in,
        "patch",
        path,
        {"revision": 1, "topic_changes": [change("unassign", topic)]},
    )
    assert edited.status_code == 200
    stale = form_post(
        signed_in,
        detail + "edit/",
        revision=1,
        content="A stale draft.",
        unassign_topics=[topic["id"]],
    )
    assert stale.status_code == 409
    assert b"A stale draft." in stale.content
    assert b"Unassign Topics" in stale.content
    assert signed_in.get(path).json() == edited.json()

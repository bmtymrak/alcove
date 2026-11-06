from conftest import document, json_request


def create_book(client, title):
    response = json_request(client, "post", "/api/v1/books/", {"title": title})
    assert response.status_code == 201
    return response["Location"] + "chapters/"


def add_chapter(client, path, label):
    response = json_request(client, "post", path, {"label": label})
    assert response.status_code == 201
    return response.json()


def test_book_chapters_append_rename_and_move(signed_in):
    path = create_book(signed_in, "Field guide")
    assert signed_in.get(path).json() == []
    appendix = add_chapter(signed_in, path, "Appendix")
    numbered = add_chapter(signed_in, path, "2")
    prologue = add_chapter(signed_in, path, "Prologue")
    assert signed_in.get(path).json() == [appendix, numbered, prologue]

    moved = json_request(
        signed_in, "patch", path + prologue["id"] + "/", {"position": 1}
    )
    assert moved.status_code == 200
    renamed = json_request(
        signed_in, "patch", path + numbered["id"] + "/", {"label": "2. The shore"}
    )
    assert renamed.status_code == 200
    expected = [
        {**prologue, "position": 1},
        {**appendix, "position": 2},
        {**numbered, "position": 3, "label": "2. The shore"},
    ]
    for invalid in [0, 4, "1", True]:
        response = json_request(
            signed_in, "patch", path + appendix["id"] + "/", {"position": invalid}
        )
        assert response.status_code == 400
        assert "position" in response.json()["error"]["fields"]
    assert signed_in.get(path).json() == expected


def test_chapter_assignment_requires_matching_source_and_follows_book_changes(
    signed_in,
):
    path = create_book(signed_in, "Field guide")
    other_path = create_book(signed_in, "Other book")
    book = path.split("/")[-3]
    other_book = other_path.split("/")[-3]
    chapter = add_chapter(signed_in, path, "Prologue")["id"]
    other_chapter = add_chapter(signed_in, other_path, "Appendix")["id"]
    payload = {"book": book, "chapter": chapter, "content": document("At the start.")}
    for invalid in [{"book": None}, {"chapter": other_chapter}]:
        rejected = json_request(
            signed_in, "post", "/api/v1/notes/", {**payload, **invalid}
        )
        assert rejected.status_code == 400
        assert "chapter" in rejected.json()["error"]["fields"]

    created = json_request(signed_in, "post", "/api/v1/notes/", payload)
    assert created.status_code == 201
    note_path = created["Location"]
    assert created.json()["chapter"] == chapter
    assert created.json()["chapter_label"] == "Prologue"
    for fields in [
        {"chapter": other_chapter},
        {"book": other_book, "chapter": chapter},
    ]:
        rejected = json_request(
            signed_in, "patch", note_path, {**fields, "revision": 1}
        )
        assert rejected.status_code == 400
        assert "chapter" in rejected.json()["error"]["fields"]
    assert signed_in.get(note_path).json() == created.json()

    for revision, fields, expected in [
        (1, {"book": book}, chapter),
        (2, {"book": other_book}, None),
        (3, {"chapter": other_chapter}, other_chapter),
        (4, {"book": None}, None),
        (5, {"book": book, "chapter": chapter}, chapter),
        (6, {"chapter": None}, None),
    ]:
        updated = json_request(
            signed_in, "patch", note_path, {**fields, "revision": revision}
        )
        assert updated.status_code == 200
        assert updated.json()["chapter"] == expected
        assert signed_in.get(note_path).json() == updated.json()


def test_chapter_order_matches_html_and_json_with_missing_locations(
    signed_in, monkeypatch
):
    from datetime import datetime, timezone

    path = create_book(signed_in, "A reading sequence")
    book = path.split("/")[-3]
    numbered = add_chapter(signed_in, path, "1")["id"]
    prologue = add_chapter(signed_in, path, "Prologue")["id"]
    assert (
        json_request(
            signed_in, "patch", path + prologue + "/", {"position": 1}
        ).status_code
        == 200
    )
    for label, chapter, page, minute in [
        ("No known location", None, None, 0),
        ("Page without Chapter", None, 1, 1),
        ("Early page in later Chapter", numbered, 1, 2),
        ("Unpaged in Prologue", prologue, None, 3),
        ("Page ten in Prologue", prologue, 10, 4),
        ("First capture on page two", prologue, 2, 5),
        ("Tied page capture A", prologue, 2, 6),
        ("Tied page capture B", prologue, 2, 6),
    ]:
        now = datetime(2026, 1, 1, 12, minute, tzinfo=timezone.utc)
        monkeypatch.setattr("django.utils.timezone.now", lambda: now)
        response = signed_in.post(
            f"/books/{book}/notes/new/",
            {
                "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
                "book": book,
                "chapter": chapter or "",
                "content": label,
                "page_number": page or "",
            },
        )
        assert response.status_code == 302
    api = f"/api/v1/books/{book}/notes/"
    oldest = signed_in.get(api).json()["results"]
    ties = [
        note["plain_text"] for note in sorted(oldest[-2:], key=lambda note: note["id"])
    ]
    expected = [
        "First capture on page two",
        *ties,
        "Page ten in Prologue",
        "Unpaged in Prologue",
        "Early page in later Chapter",
        "Page without Chapter",
        "No known location",
    ]
    result = signed_in.get(api + "?order=chapter")
    assert result.status_code == 200
    assert [note["plain_text"] for note in result.json()["results"]] == expected
    html = signed_in.get(f"/books/{book}/?order=chapter").content.decode()
    positions = [html.index(label) for label in expected]
    assert positions == sorted(positions)
    assert "Chapter: Prologue" in html
    assert oldest[0]["plain_text"] == "No known location"


def test_chapter_routes_and_assignments_are_private(signed_in):
    from django.contrib.auth.models import User
    from django.test import Client

    from alcove.models import Collection

    private_path = create_book(signed_in, "Private book")
    private_chapter = add_chapter(signed_in, private_path, "Private chapter")
    private_detail = private_path + private_chapter["id"] + "/"
    user = User.objects.create_user("other-reader")
    Collection.objects.create(owner=user)
    other = Client(enforce_csrf_checks=True)
    other.force_login(user)
    other.get("/notes/new/")
    assert Client().get(private_path).status_code == 403
    assert other.get(private_path).status_code == 404
    for method, path, payload in [
        ("post", private_path, {"label": "Intrusion"}),
        ("patch", private_detail, {"label": "Intrusion"}),
    ]:
        assert json_request(other, method, path, payload).status_code == 404
        assert (
            getattr(signed_in, method)(
                path, payload, content_type="application/json"
            ).status_code
            == 403
        )
    assert "Private chapter" not in other.get("/notes/new/").content.decode()

    own_path = create_book(other, "Own book")
    book = own_path.split("/")[-3]
    assert (
        json_request(
            other, "patch", own_path + private_chapter["id"] + "/", {"position": 1}
        ).status_code
        == 404
    )
    chapter = private_chapter["id"]
    payload = {"book": book, "chapter": chapter, "content": document("A private Note.")}
    rejected = json_request(other, "post", "/api/v1/notes/", payload)
    assert rejected.status_code == 400
    assert "chapter" in rejected.json()["error"]["fields"]

    created = json_request(
        other, "post", "/api/v1/notes/", {**payload, "chapter": None}
    )
    assert created.status_code == 201
    note_path = created["Location"]
    for path in ["/notes/new/", note_path.removeprefix("/api/v1") + "edit/"]:
        rejected = other.post(
            path,
            {
                "book": book,
                "chapter": chapter,
                "content": "Retain the pending note.",
                "revision": 1,
                "csrfmiddlewaretoken": other.cookies["csrftoken"].value,
            },
        )
        assert rejected.status_code == 400
        html = rejected.content.decode()
        assert "Choose a Chapter from the selected Book." in html
        assert "Retain the pending note." in html
        assert "Private chapter" not in html
    assert other.get(note_path).json() == created.json()
    assert other.get("/api/v1/notes/").json()["count"] == 1
    assert signed_in.get(private_path).json() == [private_chapter]


def test_capture_retry_compares_original_chapter_even_after_html_edit(signed_in):
    from uuid import uuid4

    path = create_book(signed_in, "Field guide")
    book = path.split("/")[-3]
    prologue = add_chapter(signed_in, path, "Prologue")["id"]
    other_path = create_book(signed_in, "A second Book")
    appendix = add_chapter(signed_in, other_path, "Appendix")["id"]
    notes_path = "/api/v1/notes/"
    payload = {
        "book": book,
        "chapter": prologue,
        "content": document("Revisiting the material."),
        "capture_id": str(uuid4()),
    }
    created = json_request(signed_in, "post", notes_path, payload)
    assert created.status_code == 201
    note_path = created["Location"]
    edit_path = note_path.removeprefix("/api/v1") + "edit/"
    for form_path in ["/notes/new/", edit_path]:
        html = signed_in.get(form_path).content.decode()
        assert '<optgroup label="A second Book">' in html
        assert f'<option value="{appendix}">Appendix</option>' in html
    edited = signed_in.post(
        edit_path,
        {
            "book": other_path.split("/")[-3],
            "chapter": appendix,
            "revision": 1,
            "content": "A thought for the appendix.",
            "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
        },
    )
    assert edited.status_code == 302
    saved = signed_in.get(note_path).json()
    assert saved["chapter"] == appendix
    replay = json_request(signed_in, "post", notes_path, payload)
    assert replay.status_code == 200
    assert replay.json() == saved
    conflict = json_request(
        signed_in, "post", notes_path, {**payload, "chapter": appendix}
    )
    assert conflict.status_code == 409
    assert signed_in.get(notes_path).json()["results"] == [saved]

from conftest import json_request


def test_book_library_create_duplicate_titles_and_edit_metadata(signed_in):
    response = signed_in.post(
        "/books/new/",
        {
            "title": "Ways of Seeing",
            "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
        },
    )
    assert response.status_code == 302
    book = signed_in.get("/api/v1/books/").json()["results"][0]
    assert book["title"] == "Ways of Seeing"
    assert book["author"] == ""
    assert response["Location"] == f"/books/{book['id']}/"
    duplicate = json_request(
        signed_in,
        "post",
        "/api/v1/books/",
        {"title": "Ways of Seeing", "author": "John Berger"},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] != book["id"]
    assert signed_in.get(duplicate["Location"]).json() == duplicate.json()
    library = signed_in.get("/").content.decode()
    assert "Book library" in library
    assert library.count("Ways of Seeing") == 2
    path = f"/api/v1/books/{book['id']}/"
    updated = json_request(signed_in, "patch", path, {"author": "A different author"})
    assert updated.status_code == 200
    assert updated.json()["title"] == "Ways of Seeing"
    response = signed_in.post(
        f"/books/{book['id']}/edit/",
        {
            "title": "A revised title",
            "author": "",
            "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
        },
    )
    assert response.status_code == 302
    assert signed_in.get(path).json() == {
        "id": book["id"],
        "title": "A revised title",
        "author": "",
    }
    assert "A revised title" in signed_in.get(response["Location"]).content.decode()


def test_repeated_book_capture_and_source_changes_preserve_one_note(signed_in):
    from conftest import document

    first = json_request(signed_in, "post", "/api/v1/books/", {"title": "First"}).json()
    second = json_request(
        signed_in, "post", "/api/v1/books/", {"title": "Second"}
    ).json()
    capture_path = f"/books/{first['id']}/notes/new/"
    form = signed_in.get(capture_path)
    assert form.status_code == 200
    assert f'value="{first["id"]}" selected' in form.content.decode()
    for text in ["First marginalium.", "Second marginalium."]:
        response = signed_in.post(
            capture_path,
            {
                "content": text,
                "book": first["id"],
                "add_another": "1",
                "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
            },
        )
        assert response.status_code == 302
        assert response["Location"] == capture_path
        assert (
            f'value="{first["id"]}" selected'
            in signed_in.get(response["Location"]).content.decode()
        )
    listing = signed_in.get(f"/api/v1/books/{first['id']}/notes/").json()
    assert [n["plain_text"] for n in listing["results"]] == [
        "First marginalium.",
        "Second marginalium.",
    ]
    html = signed_in.get(f"/books/{first['id']}/").content.decode()
    for note in listing["results"]:
        assert note["plain_text"] in html
        assert f"/notes/{note['id']}/" in html
        assert note["book"] == first["id"]
    note = listing["results"][0]
    path = f"/api/v1/notes/{note['id']}/"
    changed = json_request(
        signed_in, "patch", path, {"book": second["id"], "revision": 1}
    )
    assert changed.status_code == 200
    assert changed.json()["book"] == second["id"]
    assert changed.json()["content"] == document("First marginalium.")
    assert changed.json()["revision"] == 2
    # Older clients that send only content must preserve the association.
    preserved = json_request(
        signed_in, "patch", path, {"content": document("Revisited."), "revision": 2}
    )
    assert preserved.status_code == 200
    assert preserved.json()["book"] == second["id"]
    stale = json_request(signed_in, "patch", path, {"book": None, "revision": 2})
    assert stale.status_code == 409
    assert signed_in.get(path).json() == preserved.json()
    cleared = signed_in.post(
        f"/notes/{note['id']}/edit/",
        {
            "content": "Revisited.",
            "book": "",
            "revision": 3,
            "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
        },
    )
    assert cleared.status_code == 302
    assert signed_in.get(path).json()["book"] is None
    assert signed_in.get(f"/api/v1/books/{second['id']}/notes/").json()["count"] == 0
    # General capture, including Save and add another, remains available.
    general = signed_in.post(
        "/notes/new/",
        {
            "content": "Standalone.",
            "add_another": "1",
            "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
        },
    )
    assert general.status_code == 302
    assert general["Location"] == "/notes/new/"


def test_book_note_ordering_paginates_equally_through_html_and_json(
    signed_in, monkeypatch
):
    from datetime import datetime, timezone

    from conftest import document

    book = json_request(
        signed_in, "post", "/api/v1/books/", {"title": "Ordering"}
    ).json()
    # Time is a system boundary: equal capture times exercise UUID tiebreaking.
    monkeypatch.setattr(
        "django.utils.timezone.now", lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    captured = []
    for number in range(21):
        response = json_request(
            signed_in,
            "post",
            "/api/v1/notes/",
            {"content": document(f"Marginalium {number:02d}."), "book": book["id"]},
        )
        assert response.status_code == 201
        captured.append(response.json())
    expected = sorted(captured, key=lambda n: n["id"])
    for order, ordered in [
        ("oldest", expected),
        ("newest", expected[::-1]),
        ("page", expected),
    ]:
        for page, subset in [(1, ordered[:20]), (2, ordered[20:])]:
            query = f"?order={order}&page={page}"
            response = signed_in.get(f"/api/v1/books/{book['id']}/notes/" + query)
            assert response.status_code == 200
            assert response.json() == {
                "count": 21,
                "page": page,
                "page_size": 20,
                "results": subset,
            }
            html = signed_in.get(f"/books/{book['id']}/" + query).content.decode()
            positions = [html.index(n["plain_text"]) for n in subset]
            assert positions == sorted(positions)
            assert f"?order={order}&amp;page=" in html
    assert (
        signed_in.get(f"/api/v1/books/{book['id']}/notes/").json()["results"]
        == expected[:20]
    )
    for query in ["?page=0", "?page=3", "?page=invalid", "?order=invalid"]:
        assert (
            signed_in.get(f"/api/v1/books/{book['id']}/notes/" + query).status_code
            == 404
        )
        assert signed_in.get(f"/books/{book['id']}/" + query).status_code == 404


def test_foreign_books_are_private_and_cannot_be_note_sources(signed_in):
    from conftest import document
    from django.contrib.auth.models import User
    from django.test import Client

    from alcove.models import Collection

    book = json_request(
        signed_in,
        "post",
        "/api/v1/books/",
        {"title": "Private book", "author": "Private author"},
    ).json()
    note = json_request(
        signed_in,
        "post",
        "/api/v1/notes/",
        {"content": document("Private note."), "book": book["id"]},
    ).json()
    user = User.objects.create_user("other", password="Different-reading-782!")
    Collection.objects.create(owner=user)
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
    assert other.get("/api/v1/books/").json()["count"] == 0
    assert "Private book" not in other.get("/").content.decode()
    assert "Private book" not in other.get("/notes/new/").content.decode()
    for path in [
        f"/books/{book['id']}/",
        f"/books/{book['id']}/?order=page",
        f"/books/{book['id']}/edit/",
        f"/books/{book['id']}/notes/new/",
        f"/api/v1/books/{book['id']}/",
        f"/api/v1/books/{book['id']}/notes/",
        f"/api/v1/books/{book['id']}/notes/?order=page",
    ]:
        assert other.get(path).status_code == 404
    assert (
        other.post(
            f"/books/{book['id']}/edit/",
            {
                "title": "Stolen",
                "csrfmiddlewaretoken": other.cookies["csrftoken"].value,
            },
        ).status_code
        == 404
    )
    assert (
        json_request(
            other, "patch", f"/api/v1/books/{book['id']}/", {"title": "Stolen"}
        ).status_code
        == 404
    )
    assert (
        other.post(
            f"/books/{book['id']}/notes/new/",
            {
                "content": "Intrusion",
                "csrfmiddlewaretoken": other.cookies["csrftoken"].value,
            },
        ).status_code
        == 404
    )
    own_book = json_request(
        other, "post", "/api/v1/books/", {"title": "Own book"}
    ).json()
    own_note = json_request(
        other,
        "post",
        "/api/v1/notes/",
        {"content": document("Keep this."), "book": own_book["id"]},
    ).json()
    for source in [book["id"], "00000000-0000-0000-0000-000000000000", "invalid"]:
        payload = {
            "content": document("Rejected capture."),
            "book": source,
            "page_number": 42,
            "source_reference": "Footnote 3",
        }
        response = json_request(other, "post", "/api/v1/notes/", payload)
        assert response.status_code == 400
        assert "book" in response.json()["error"]["fields"]
        response = json_request(
            other,
            "patch",
            f"/api/v1/notes/{own_note['id']}/",
            {**payload, "revision": 1},
        )
        assert response.status_code == 400
        assert "book" in response.json()["error"]["fields"]
        for path in ["/notes/new/", f"/notes/{own_note['id']}/edit/"]:
            response = other.post(
                path,
                {
                    "content": "Retain my unsaved text.",
                    "book": source,
                    "page_number": "42",
                    "source_reference": "Footnote 3",
                    "revision": 1,
                    "csrfmiddlewaretoken": other.cookies["csrftoken"].value,
                },
            )
            assert response.status_code == 400
            assert "Retain my unsaved text." in response.content.decode()
        assert other.get(f"/api/v1/notes/{own_note['id']}/").json() == own_note
        assert other.get("/api/v1/notes/").json()["count"] == 1
    assert signed_in.get(f"/api/v1/books/{book['id']}/").json() == book
    assert signed_in.get(f"/api/v1/books/{book['id']}/notes/").json()["results"] == [
        note
    ]


def test_html_can_assign_and_change_a_note_source(signed_in):
    from conftest import document

    books = [
        json_request(signed_in, "post", "/api/v1/books/", {"title": title}).json()
        for title in ["First", "Second"]
    ]
    note = json_request(
        signed_in,
        "post",
        "/api/v1/notes/",
        {"content": document("Standalone originally.")},
    ).json()
    assert note["book"] is None
    for revision, book in enumerate(books, start=1):
        response = signed_in.post(
            f"/notes/{note['id']}/edit/",
            {
                "content": "Same note, new source.",
                "book": book["id"],
                "revision": revision,
                "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
            },
        )
        assert response.status_code == 302
        saved = signed_in.get(f"/api/v1/notes/{note['id']}/").json()
        assert saved["book"] == book["id"]
        assert saved["revision"] == revision + 1
        assert saved["captured_at"] == note["captured_at"]
        assert book["title"] in signed_in.get(response["Location"]).content.decode()
    assert signed_in.get(f"/api/v1/books/{books[0]['id']}/notes/").json()["count"] == 0
    assert signed_in.get(f"/api/v1/books/{books[1]['id']}/notes/").json()[
        "results"
    ] == [saved]


def test_book_validation_preserves_metadata_and_unsaved_html_input(signed_in):
    book = json_request(
        signed_in, "post", "/api/v1/books/", {"title": "Keep me"}
    ).json()
    for invalid in [
        {},
        {"title": "  "},
        {"title": "a" * 301},
        {"title": None},
        {"title": "Bad\x00title"},
        {"title": "Valid", "author": "a" * 301},
        {"title": "Valid", "collection": "other"},
    ]:
        response = json_request(signed_in, "post", "/api/v1/books/", invalid)
        assert response.status_code == 400
        if invalid:
            assert (
                json_request(
                    signed_in, "patch", f"/api/v1/books/{book['id']}/", invalid
                ).status_code
                == 400
            )
        assert signed_in.get("/api/v1/books/").json()["results"] == [book]
    for path in ["/books/new/", f"/books/{book['id']}/edit/"]:
        response = signed_in.post(
            path,
            {
                "title": "  ",
                "author": "Retain this author",
                "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
            },
        )
        assert response.status_code == 400
        assert "Retain this author" in response.content.decode()
    assert signed_in.get(f"/api/v1/books/{book['id']}/").json() == book


def test_book_routes_require_authentication_and_writes_require_csrf(signed_in):
    from django.test import Client

    book = json_request(
        signed_in, "post", "/api/v1/books/", {"title": "Protected"}
    ).json()
    anonymous = Client(enforce_csrf_checks=True)
    for path in [
        "/",
        "/notes/",
        "/books/new/",
        f"/books/{book['id']}/",
        f"/books/{book['id']}/edit/",
        f"/books/{book['id']}/notes/new/",
    ]:
        assert anonymous.get(path).status_code == 302
    for path in [
        "/api/v1/books/",
        f"/api/v1/books/{book['id']}/",
        f"/api/v1/books/{book['id']}/notes/",
    ]:
        assert anonymous.get(path).status_code == 403
    for client in [anonymous, signed_in]:
        assert (
            client.post(
                "/api/v1/books/",
                {"title": "Intrusion"},
                content_type="application/json",
            ).status_code
            == 403
        )
        assert (
            client.patch(
                f"/api/v1/books/{book['id']}/",
                {"title": "Intrusion"},
                content_type="application/json",
            ).status_code
            == 403
        )
        assert client.post("/books/new/", {"title": "Intrusion"}).status_code == 403
        assert (
            client.post(
                f"/books/{book['id']}/edit/", {"title": "Intrusion"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/books/{book['id']}/notes/new/", {"content": "Intrusion"}
            ).status_code
            == 403
        )
    assert signed_in.get(f"/api/v1/books/{book['id']}/").json() == book


def test_library_pagination_and_escaped_metadata(signed_in):
    from html import escape

    captured = []
    for number in range(21):
        response = json_request(
            signed_in, "post", "/api/v1/books/", {"title": f"Book {number:02d}"}
        )
        assert response.status_code == 201
        captured.append(response.json())
    assert signed_in.get("/api/v1/books/").json() == {
        "count": 21,
        "page": 1,
        "page_size": 20,
        "results": captured[:20],
    }
    assert signed_in.get("/api/v1/books/?page=2").json()["results"] == captured[20:]
    assert "Book 20" in signed_in.get("/?page=2").content.decode()
    for query in ["?page=0", "?page=3", "?page=invalid"]:
        assert signed_in.get("/api/v1/books/" + query).status_code == 404
        assert signed_in.get("/" + query).status_code == 404
    title = '<script>alert("book")</script>'
    author = "<b>Author & reader</b>"
    response = json_request(
        signed_in, "post", "/api/v1/books/", {"title": title, "author": author}
    )
    assert response.status_code == 201
    book = response.json()
    for path in [
        "/",
        f"/books/{book['id']}/",
        f"/books/{book['id']}/edit/",
        "/notes/new/",
    ]:
        html = signed_in.get(path).content.decode()
        assert "<script>" not in html
        assert escape(title) in html
        assert escape(author) in html

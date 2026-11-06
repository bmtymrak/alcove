from html import escape
from uuid import uuid4

from conftest import document, json_request


def test_html_capture_and_json_edit_round_trip_page_and_reference(signed_in):
    book = json_request(
        signed_in, "post", "/api/v1/books/", {"title": "Field guide"}
    ).json()
    csrf = signed_in.cookies["csrftoken"].value
    reference = "pp. 42–44, footnote <2>"
    captured = signed_in.post(
        f"/books/{book['id']}/notes/new/",
        {
            "csrfmiddlewaretoken": csrf,
            "content": "A marginalium.",
            "book": book["id"],
            "page_number": "42",
            "source_reference": reference,
        },
    )
    assert captured.status_code == 302
    detail = captured["Location"]
    api = "/api/v1" + detail
    saved = signed_in.get(api).json()
    assert (saved["book"], saved["page_number"], saved["source_reference"]) == (
        book["id"],
        42,
        reference,
    )
    for path in [detail, f"/books/{book['id']}/", detail + "edit/"]:
        assert escape(reference) in signed_in.get(path).content.decode()

    edited = json_request(
        signed_in,
        "patch",
        api,
        {"page_number": 43, "source_reference": "Footnote 3", "revision": 1},
    )
    assert edited.status_code == 200
    assert edited.json()["content"] == saved["content"]
    assert "Footnote 3" in signed_in.get(detail).content.decode()
    assert signed_in.get(api).json() == edited.json()

    cleared = signed_in.post(
        detail + "edit/",
        {
            "csrfmiddlewaretoken": csrf,
            "content": "Edited through HTML.",
            "book": "",
            "page_number": "",
            "source_reference": "A reference without a Book",
            "revision": 2,
        },
    )
    assert cleared.status_code == 302
    saved = signed_in.get(api).json()
    assert saved["plain_text"] == "Edited through HTML."
    assert saved["book"] is saved["page_number"] is None
    assert saved["source_reference"] == "A reference without a Book"
    assert saved["source_reference"] in signed_in.get(detail).content.decode()


def test_page_number_errors_leave_capture_and_edit_inputs_intact(signed_in):
    notes = "/api/v1/notes/"
    payload = {"content": document("My own reference."), "source_reference": "pp. 9–12"}
    for invalid in [False, "9", 9.0, 9.5, 0, -9, 2147483648]:
        response = json_request(
            signed_in, "post", notes, {**payload, "page_number": invalid}
        )
        assert response.status_code == 400
        assert "page_number" in response.json()["error"]["fields"]
    assert signed_in.get(notes).json()["count"] == 0
    created = json_request(
        signed_in, "post", notes, {**payload, "page_number": 2147483647}
    )
    assert created.status_code == 201
    api = created["Location"]
    detail = api.removeprefix("/api/v1")
    for invalid in ["9.0", "9–12", "0", "2147483648"]:
        response = signed_in.post(
            detail + "edit/",
            {
                "csrfmiddlewaretoken": signed_in.cookies["csrftoken"].value,
                "content": "Retain my unsaved text.",
                "page_number": invalid,
                "source_reference": "Retain my unsaved reference.",
                "revision": 1,
            },
        )
        assert response.status_code == 400
        html = response.content.decode()
        assert "Enter a whole Page Number" in html
        assert "Retain my unsaved reference." in html
    for fields, invalid_field in [
        ({"page_number": 9.5}, "page_number"),
        ({"source_reference": 9}, "source_reference"),
        ({"source_reference": "footnote\x00"}, "source_reference"),
    ]:
        response = json_request(signed_in, "patch", api, {**fields, "revision": 1})
        assert response.status_code == 400
        assert invalid_field in response.json()["error"]["fields"]
    assert signed_in.get(api).json() == created.json()


def test_capture_retry_compares_original_page_and_reference_after_edit(signed_in):
    notes = "/api/v1/notes/"
    payload = {
        "capture_id": str(uuid4()),
        "content": document("A page range."),
        "page_number": 42,
        "source_reference": "pp. 42–44",
    }
    created = json_request(signed_in, "post", notes, payload)
    assert created.status_code == 201
    api = created["Location"]
    edited = json_request(
        signed_in, "patch", api, {"content": document("Revised."), "revision": 1}
    )
    assert edited.status_code == 200
    assert edited.json()["page_number"] == 42
    assert edited.json()["source_reference"] == "pp. 42–44"
    cleared = json_request(
        signed_in,
        "patch",
        api,
        {"page_number": None, "source_reference": "", "revision": 2},
    )
    assert cleared.status_code == 200
    assert cleared.json()["page_number"] is None
    assert cleared.json()["source_reference"] == ""
    replay = json_request(signed_in, "post", notes, payload)
    assert replay.status_code == 200
    assert replay.json() == cleared.json()
    for changed in [{"page_number": 43}, {"source_reference": "Footnote 2"}]:
        response = json_request(signed_in, "post", notes, {**payload, **changed})
        assert response.status_code == 409
    assert signed_in.get(notes).json()["results"] == [cleared.json()]


def test_book_page_order_uses_numeric_anchors_then_capture_time_then_uuid(
    signed_in, monkeypatch
):
    from datetime import datetime, timezone

    book = json_request(
        signed_in, "post", "/api/v1/books/", {"title": "Reading sequence"}
    ).json()
    book_path = f"/books/{book['id']}/"
    api = "/api/v1" + book_path + "notes/"
    captures = {}
    for label, anchor, minute in [
        ("Unlocated", None, 0),
        ("Page ten", 10, 1),
        ("Page nine first", 9, 2),
        ("Page nine tied A", 9, 3),
        ("Page nine tied B", 9, 3),
    ]:
        now = datetime(2026, 1, 1, 12, minute, tzinfo=timezone.utc)
        monkeypatch.setattr("django.utils.timezone.now", lambda: now)
        response = json_request(
            signed_in,
            "post",
            "/api/v1/notes/",
            {
                "book": book["id"],
                "content": document(label),
                "page_number": anchor,
                "source_reference": "pp. 1–3" if anchor is None else "",
            },
        )
        assert response.status_code == 201
        captures[label] = response.json()
    tied = sorted(
        [captures["Page nine tied A"], captures["Page nine tied B"]],
        key=lambda note: note["id"],
    )
    expected = [
        captures["Page nine first"],
        *tied,
        captures["Page ten"],
        captures["Unlocated"],
    ]
    response = signed_in.get(api + "?order=page")
    assert response.status_code == 200
    assert response.json()["results"] == expected
    html = signed_in.get(book_path + "?order=page").content.decode()
    positions = [html.index(note["plain_text"]) for note in expected]
    assert positions == sorted(positions)
    assert signed_in.get(api).json()["results"][0] == captures["Unlocated"]

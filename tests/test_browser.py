import pytest
from conftest import PASSWORD
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def page(live_server, owner):
    # Start Playwright's event loop after Django fixture setup, and stop it
    # before Django's synchronous database teardown.
    with sync_playwright() as playwright:
        with playwright.chromium.launch() as browser:
            with browser.new_context() as context:
                yield context.new_page()


def open_existing_editor(page, live_server):
    page.goto(live_server.url + "/login/")
    page.get_by_label("Username").fill("reader")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("link", name="Capture a note", exact=True).click()
    page.get_by_label("Your note").fill("Original thought.")
    page.get_by_role("button", name="Save note", exact=True).click()
    page.get_by_role("link", name="Edit note", exact=True).click()


def test_existing_note_autosaves_without_leaving_the_editor(page, live_server, owner):
    open_existing_editor(page, live_server)
    edit_url = page.url
    page.get_by_label("Your note").fill("A thought reconsidered.")
    expect(page.get_by_role("status")).to_have_text("Saved.")
    expect(page).to_have_url(edit_url)
    assert page.get_by_role("button", name="Save changes", exact=True).count() == 0
    page.reload()
    expect(page.get_by_label("Your note")).to_have_text("A thought reconsidered.")


def test_autosave_keeps_newer_edits_pending_until_their_request_finishes(
    page, live_server, owner
):
    open_existing_editor(page, live_server)
    requests = []
    page.route("**/api/v1/notes/*/", lambda route: requests.append(route))
    editor = page.get_by_label("Your note")
    editor.fill("First pending version.")
    expect(page.get_by_role("status")).to_have_text("Saving…")
    page.wait_for_timeout(700)
    assert len(requests) == 1
    editor.fill("Latest pending version.")
    page.wait_for_timeout(700)
    assert len(requests) == 1
    requests[0].continue_()
    page.wait_for_timeout(700)
    assert len(requests) == 2
    assert requests[1].request.post_data_json["revision"] == 2
    expect(page.get_by_role("status")).to_have_text("Saving…")
    expect(editor).to_have_text("Latest pending version.")
    requests[1].continue_()
    expect(page.get_by_role("status")).to_have_text("Saved.")
    page.reload()
    expect(editor).to_have_text("Latest pending version.")


@pytest.mark.parametrize(
    "failure", ["validation", "server", "lost-response", "lost-response-revert"]
)
def test_failed_autosave_retains_pending_edits_and_can_retry_or_review(
    page, live_server, owner, failure
):
    open_existing_editor(page, live_server)
    endpoint = "**/api/v1/notes/*/"

    def fail(route):
        if failure.startswith("lost-response"):
            assert route.fetch().status == 200
            route.abort("failed")
        elif failure == "server":
            route.fulfill(status=500, content_type="text/html", body="Unavailable")
        else:
            route.fulfill(
                status=400,
                json={"error": {"message": "Could not save.", "fields": {}}},
            )

    page.route(endpoint, fail)
    editor = page.get_by_label("Your note")
    editor.fill("Keep this pending thought.")
    expect(page.get_by_role("status")).to_have_text(
        "Not saved. Your draft is still here."
    )
    expect(editor).to_have_text("Keep this pending thought.")
    pending = (
        "Original thought."
        if failure == "lost-response-revert"
        else "A revised pending thought."
    )
    editor.fill(pending)
    expect(page.get_by_role("status")).to_have_text(
        "Not saved. Your draft is still here."
    )
    page.unroute(endpoint)
    page.get_by_role("button", name="Retry saving").click()
    if failure.startswith("lost-response"):
        expect(page.get_by_role("status")).to_have_text(
            "Conflict. Your draft is still here."
        )
        page.get_by_role("button", name="Review current note").click()
        expect(page.locator("[data-current-content]")).to_have_text(
            "Keep this pending thought."
        )
        page.get_by_role("button", name="Save my version").click()
    expect(page.get_by_role("status")).to_have_text("Saved.")
    page.reload()
    expect(editor).to_have_text(pending)


@pytest.mark.parametrize(
    "viewport", [{"width": 1280, "height": 900}, {"width": 390, "height": 844}]
)
def test_capture_read_edit_and_sign_out_in_browser(page, live_server, owner, viewport):
    page.set_viewport_size(viewport)
    page.goto(live_server.url)
    expect(
        page.get_by_role("heading", name="A quiet place for your thoughts.")
    ).to_be_visible()
    page.get_by_label("Username").fill("reader")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("link", name="Capture a note", exact=True).click()
    page.get_by_label("Your note").fill("A sentence from my reading.")
    page.get_by_role("button", name="Save note", exact=True).click()
    expect(page.get_by_role("link", name="Edit note", exact=True)).to_be_visible()
    note_url = page.url
    expect(page.get_by_text("A sentence from my reading.", exact=True)).to_be_visible()
    page.reload()
    expect(page.get_by_text("A sentence from my reading.", exact=True)).to_be_visible()
    page.get_by_role("link", name="Edit note", exact=True).click()
    page.get_by_label("Your note").fill("A thought reconsidered.")
    expect(page.get_by_role("status")).to_have_text("Saved.")
    page.goto(note_url)
    expect(page.get_by_text("A thought reconsidered.", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.get_by_role("button", name="Sign out", exact=True).click()
    page.goto(note_url)
    expect(page.get_by_role("button", name="Sign in", exact=True)).to_be_visible()


def test_browser_retains_invalid_and_conflicted_input(page, live_server, owner):
    page.goto(live_server.url + "/login/")
    page.get_by_label("Username").fill("reader")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("link", name="Capture a note", exact=True).click()
    page.get_by_label("Your note").fill("   ")
    page.get_by_role("button", name="Save note", exact=True).click()
    expect(
        page.get_by_text("Write something before saving.", exact=True)
    ).to_be_visible()
    expect(page.get_by_label("Your note")).to_have_text("   ")
    page.get_by_label("Your note").fill("Original thought.")
    page.get_by_role("button", name="Save note", exact=True).click()
    page.get_by_role("link", name="Edit note", exact=True).click()
    second_tab = page.context.new_page()
    second_tab.goto(page.url)
    second_tab.get_by_label("Your note").fill("Saved in another tab.")
    expect(second_tab.get_by_role("status")).to_have_text("Saved.")
    page.get_by_label("Your note").fill("Keep my pending thought.")
    expect(page.get_by_role("status")).to_have_text(
        "Conflict. Your draft is still here."
    )
    expect(page.get_by_label("Your note")).to_have_text("Keep my pending thought.")
    expect(
        page.get_by_text("This Note changed elsewhere.", exact=False)
    ).to_be_visible()
    page.get_by_role("button", name="Review current note").click()
    expect(page.get_by_text("Saved in another tab.", exact=True)).to_be_visible()
    expect(page.get_by_label("Your note")).to_have_text("Keep my pending thought.")
    page.get_by_role("button", name="Save my version").click()
    expect(page.get_by_role("status")).to_have_text("Saved.")
    second_tab.reload()
    expect(second_tab.get_by_label("Your note")).to_have_text(
        "Keep my pending thought."
    )
    second_tab.close()


@pytest.mark.parametrize(
    "viewport", [{"width": 1280, "height": 900}, {"width": 390, "height": 844}]
)
def test_book_marginalia_capture_and_inline_reading(page, live_server, owner, viewport):
    page.set_viewport_size(viewport)
    page.goto(live_server.url)
    page.get_by_label("Username").fill("reader")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.get_by_role("heading", name="Book library")).to_be_visible()
    page.get_by_role("link", name="Add a book", exact=True).click()
    page.get_by_label("Title").fill("Ways of Seeing")
    page.get_by_label("Author").fill("John Berger")
    page.get_by_role("button", name="Save book", exact=True).click()
    book_url = page.url
    page.get_by_role("link", name="Capture a note from this book").click()
    selected_book = page.get_by_label("Source book").input_value()
    assert selected_book
    page.get_by_label("Your note").fill("First marginalium.")
    page.get_by_label("Page number").fill("10")
    page.get_by_label("Source reference").fill("pp. 10–12, footnote 3")
    page.get_by_role("button", name="Save and add another", exact=True).click()
    expect(page.get_by_label("Your note")).to_have_text("")
    expect(page.get_by_label("Source book")).to_have_value(selected_book)
    expect(page.get_by_label("Page number")).to_have_value("")
    expect(page.get_by_label("Source reference")).to_have_value("")
    page.get_by_role("button", name="Save and add another", exact=True).click()
    expect(
        page.get_by_text("Write something before saving.", exact=True)
    ).to_be_visible()
    expect(page.get_by_label("Source book")).to_have_value(selected_book)
    page.get_by_label("Your note").fill("Second marginalium.")
    page.get_by_label("Page number").fill("9")
    page.get_by_role("button", name="Save note", exact=True).click()
    expect(page.get_by_role("link", name="Edit note", exact=True)).to_be_visible()
    page.goto(book_url)
    expect(page.locator(".note-content")).to_have_text(
        ["First marginalium.", "Second marginalium."]
    )
    expect(page.get_by_text("Source reference: pp. 10–12, footnote 3")).to_be_visible()
    page.get_by_label("Note order").select_option("page")
    page.get_by_role("button", name="Apply order", exact=True).click()
    expect(page.locator(".note-content")).to_have_text(
        ["Second marginalium.", "First marginalium."]
    )
    page.reload()
    expect(page.get_by_label("Note order")).to_have_value("page")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.get_by_role("link", name="Open note", exact=False).first.click()
    expect(page.get_by_role("link", name="Ways of Seeing", exact=True)).to_be_visible()
    page.get_by_role("link", name="Edit note", exact=True).click()
    expect(page.get_by_role("status")).to_have_text("Saved.")
    page.get_by_label("Source book").select_option("")
    expect(page.get_by_role("status")).to_have_text("Saved.")
    page.goto(page.url.removesuffix("edit/"))
    expect(page.get_by_role("link", name="Edit note", exact=True)).to_be_visible()
    expect(page.get_by_text("Page 9", exact=True)).to_be_visible()
    page.goto(book_url)
    expect(page.locator(".note-content")).to_have_text(["First marginalium."])


@pytest.mark.parametrize(
    "viewport", [{"width": 1280, "height": 900}, {"width": 390, "height": 844}]
)
def test_formatted_editor_round_trip_and_website_links(
    page, live_server, owner, viewport
):
    page.set_viewport_size(viewport)
    page.goto(live_server.url + "/login/")
    page.get_by_label("Username").fill("reader")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("link", name="Capture a note", exact=True).click()
    editor = page.get_by_role("textbox", name="Your note", exact=True)
    editor.fill("A quotation and a thought.")
    editor.press("ControlOrMeta+a")
    page.get_by_role("button", name="Bold", exact=True).click()
    page.get_by_role("button", name="Italic", exact=True).click()
    page.get_by_role("button", name="Quotation", exact=True).click()
    page.get_by_role("button", name="Website link", exact=True).click()
    page.get_by_label("Website address").fill("javascript:alert(1)")
    page.get_by_role("button", name="Apply link", exact=True).click()
    expect(
        page.get_by_text("Use a complete http:// or https:// website address.")
    ).to_be_visible()
    page.get_by_label("Website address").fill("https://example.org/reading?q=1&x=2")
    page.get_by_role("button", name="Apply link", exact=True).click()
    with page.expect_response(
        lambda response: response.url.endswith("/api/v1/notes/")
        and response.request.method == "POST"
    ) as saved:
        page.get_by_role("button", name="Save note", exact=True).click()
    assert saved.value.status == 201
    assert saved.value.request.post_data_json["content"]["format"] == "tiptap"
    expect(page.get_by_role("link", name="Edit note", exact=True)).to_be_visible()
    note_url = page.url
    expect(page.locator(".note-content blockquote a")).to_have_text(
        "A quotation and a thought."
    )
    expect(
        page.get_by_role("link", name="A quotation and a thought.")
    ).to_have_attribute("href", "https://example.org/reading?q=1&x=2")
    expect(page.locator(".note-content strong")).to_have_text(
        "A quotation and a thought."
    )
    expect(page.locator(".note-content em")).to_have_text("A quotation and a thought.")
    page.reload()
    page.get_by_role("link", name="Edit note", exact=True).click()
    expect(editor.locator("blockquote a")).to_have_text("A quotation and a thought.")
    editor.press("ControlOrMeta+End")
    editor.press("Enter")
    editor.press("Enter")
    page.get_by_role("button", name="Bulleted list", exact=True).click()
    editor.press_sequentially("An idea")
    editor.press("Enter")
    editor.press_sequentially("Another idea")
    expect(page.get_by_role("status")).to_have_text("Saved.")
    page.goto(note_url)
    expect(page.locator(".note-content ul li")).to_have_text(
        ["An idea", "Another idea"]
    )
    page.get_by_role("link", name="Edit note", exact=True).click()
    editor.press("ControlOrMeta+End")
    page.get_by_role("button", name="Numbered list", exact=True).click()
    expect(page.get_by_role("status")).to_have_text("Saved.")
    page.goto(note_url)
    expect(page.locator(".note-content ol li")).to_have_text(
        ["An idea", "Another idea"]
    )
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_existing_plain_note_gains_formatting_and_keeps_draft_after_network_error(
    page, live_server, owner
):
    page.goto(live_server.url + "/login/")
    page.get_by_label("Username").fill("reader")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    csrf = next(
        cookie["value"]
        for cookie in page.context.cookies()
        if cookie["name"] == "csrftoken"
    )
    saved = page.request.post(
        live_server.url + "/api/v1/notes/",
        data={
            "content": {
                "version": 1,
                "format": "plain-text",
                "text": "An existing plain Note.",
            },
        },
        headers={"X-CSRFToken": csrf},
    )
    assert saved.status == 201
    note = saved.json()
    page.goto(live_server.url + f"/notes/{note['id']}/")
    expect(page.locator(".note-content")).to_have_text("An existing plain Note.")
    page.get_by_role("link", name="Edit note", exact=True).click()
    editor = page.get_by_role("textbox", name="Your note", exact=True)
    expect(editor).to_have_text("An existing plain Note.")
    editor.press("ControlOrMeta+a")
    page.get_by_role("button", name="Bold", exact=True).click()
    endpoint = f"**/api/v1/notes/{note['id']}/"
    page.route(endpoint, lambda route: route.abort("failed"))
    expect(page.get_by_role("status")).to_have_text(
        "Not saved. Your draft is still here."
    )
    expect(editor.locator("strong")).to_have_text("An existing plain Note.")
    assert (
        page.request.get(live_server.url + f"/api/v1/notes/{note['id']}/").json()
        == note
    )
    page.unroute(endpoint)
    page.get_by_role("button", name="Retry saving").click()
    expect(page.get_by_role("status")).to_have_text("Saved.")
    page.goto(page.url.removesuffix("edit/"))
    expect(page.locator(".note-content strong")).to_have_text("An existing plain Note.")
    updated = page.request.get(live_server.url + f"/api/v1/notes/{note['id']}/").json()
    assert updated["content"]["format"] == "tiptap"
    assert updated["plain_text"] == note["plain_text"]
    assert updated["revision"] == 2


def test_emphasis_across_a_line_break_round_trips(page, live_server, owner):
    page.goto(live_server.url + "/login/")
    page.get_by_label("Username").fill("reader")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("link", name="Capture a note", exact=True).click()
    editor = page.get_by_role("textbox", name="Your note", exact=True)
    editor.fill("First")
    editor.press("End")
    editor.press("Shift+Enter")
    editor.press_sequentially("Second")
    editor.press("ControlOrMeta+a")
    page.get_by_role("button", name="Bold", exact=True).click()
    page.get_by_role("button", name="Italic", exact=True).click()
    page.get_by_role("button", name="Save note", exact=True).click()
    expect(page.locator(".note-content")).to_have_text("FirstSecond")
    expect(page.locator(".note-content br")).to_have_count(1)
    page.get_by_role("link", name="Edit note", exact=True).click()
    expect(editor.locator("strong")).to_have_text("FirstSecond")
    expect(editor.locator("em")).to_have_text("FirstSecond")
    expect(editor.locator("br")).to_have_count(1)
    expect(page.get_by_role("status")).to_have_text("Saved.")
    page.goto(page.url.removesuffix("edit/"))
    expect(page.locator(".note-content br")).to_have_count(1)


def sign_in(page, live_server):
    page.goto(live_server.url + "/login/")
    page.get_by_label("Username").fill("reader")
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in", exact=True).click()


def test_capture_recovers_formatting_and_source_after_navigation_and_reload(
    page, live_server
):
    sign_in(page, live_server)
    page.get_by_role("link", name="Add a book", exact=True).click()
    page.get_by_label("Title").fill("A source for later")
    page.get_by_role("button", name="Save book", exact=True).click()
    page.goto(live_server.url + "/notes/new/")
    source = page.get_by_label("Source book")
    editor = page.get_by_label("Your note")
    expect(editor).to_be_visible()
    page.get_by_label("Page number").fill("34")
    page.get_by_label("Source reference").fill("Footnote saved before the text")
    page.reload()
    expect(page.get_by_label("Page number")).to_have_value("34")
    expect(page.get_by_label("Source reference")).to_have_value(
        "Footnote saved before the text"
    )
    source.select_option(label="A source for later")
    editor.fill("An unfinished quotation.")
    editor.press("ControlOrMeta+a")
    page.get_by_role("button", name="Quotation", exact=True).click()

    page.get_by_role("link", name="Books", exact=True).click()
    page.get_by_role("link", name="Capture a note", exact=True).click()
    page.reload()
    expect(editor.locator("blockquote")).to_have_text("An unfinished quotation.")
    expect(source.locator("option:checked")).to_have_text("A source for later")
    assert page.request.get(live_server.url + "/api/v1/notes/").json()["count"] == 0


def test_lost_book_capture_response_can_be_retried_after_reload(page, live_server):
    sign_in(page, live_server)
    page.get_by_role("link", name="Add a book", exact=True).click()
    page.get_by_label("Title").fill("A Book of marginalia")
    page.get_by_role("button", name="Save book", exact=True).click()
    book_url = page.url
    page.get_by_role("link", name="Capture a note from this book").click()
    capture_url = page.url
    source = page.get_by_label("Source book")
    selected_book = source.input_value()
    editor = page.get_by_label("Your note")
    another = page.get_by_role("button", name="Save and add another", exact=True)

    def lose_acknowledgement(route):
        assert route.fetch().status == 201
        route.abort("failed")

    endpoint = "**/api/v1/notes/"
    page.route(endpoint, lose_acknowledgement)
    editor.fill("A quotation worth repeating.")
    page.get_by_label("Page number").fill("42")
    page.get_by_label("Source reference").fill("Footnote 8")
    another.click()
    expect(page.get_by_role("status")).to_have_text("Save not confirmed.")
    expect(page).to_have_url(capture_url)
    expect(editor).to_have_text("A quotation worth repeating.")
    expect(source).to_have_value(selected_book)

    page.reload()
    expect(editor).to_have_text("A quotation worth repeating.")
    expect(source).to_have_value(selected_book)
    expect(page.get_by_label("Page number")).to_have_value("42")
    expect(page.get_by_label("Source reference")).to_have_value("Footnote 8")
    expect(page.get_by_label("Source reference")).to_be_disabled()
    page.unroute(endpoint)
    another.click()
    expect(editor).to_have_text("")
    expect(source).to_have_value(selected_book)
    editor.fill("A quotation worth repeating.")
    another.click()
    expect(editor).to_have_text("")
    expect(source).to_have_value(selected_book)

    page.goto(book_url)
    expect(page.locator(".note-content")).to_have_text(
        ["A quotation worth repeating.", "A quotation worth repeating."]
    )
    expect(page.get_by_text("Source reference: Footnote 8", exact=True)).to_be_visible()


@pytest.mark.parametrize("failure", ["validation", "conflict"])
def test_pending_edits_recover_after_reload_without_replacing_saved_note(
    page, live_server, failure
):
    open_existing_editor(page, live_server)
    endpoint = "**/api/v1/notes/*/"
    if failure == "conflict":
        second_tab = page.context.new_page()
        second_tab.goto(page.url)
        second_tab.get_by_label("Your note").fill("The latest saved thought.")
        second_tab.get_by_label("Source reference").fill("Other tab's reference")
        expect(second_tab.get_by_role("status")).to_have_text("Saved.")
        second_tab.close()
        status = "Conflict. Your draft is still here."
    else:
        page.route(
            endpoint,
            lambda route: route.fulfill(
                status=400, json={"error": {"message": "Could not save."}}
            ),
        )
        status = "Not saved. Your draft is still here."

    editor = page.get_by_label("Your note")
    editor.fill("My pending thought.")
    page.get_by_label("Page number").fill("19")
    page.get_by_label("Source reference").fill("My pending reference")
    expect(page.get_by_role("status")).to_have_text(status)
    page.unroute(endpoint)
    page.reload()
    expect(editor).to_have_text("My pending thought.")
    expect(page.get_by_label("Page number")).to_have_value("19")
    expect(page.get_by_label("Source reference")).to_have_value("My pending reference")
    expect(page.get_by_role("status")).to_have_text(status)

    if failure == "conflict":
        page.get_by_role("button", name="Review current note").click()
        expect(page.locator("[data-current-content]")).to_have_text(
            "The latest saved thought."
        )
        expect(page.locator("[data-current-reference]")).to_have_text(
            "Other tab's reference"
        )
        page.get_by_role("button", name="Save my version").click()
    else:
        page.get_by_role("button", name="Retry saving").click()
    expect(page.get_by_role("status")).to_have_text("Saved.")
    page.reload()
    expect(editor).to_have_text("My pending thought.")
    expect(page.get_by_label("Page number")).to_have_value("19")
    expect(page.get_by_label("Source reference")).to_have_value("My pending reference")


def test_signing_out_from_another_page_clears_local_drafts(page, live_server):
    sign_in(page, live_server)
    page.get_by_role("link", name="Capture a note", exact=True).click()
    page.get_by_label("Your note").fill("A private capture draft.")
    page.get_by_role("link", name="Books", exact=True).click()
    page.get_by_role("button", name="Sign out", exact=True).click()
    sign_in(page, live_server)
    page.get_by_role("link", name="Capture a note", exact=True).click()
    expect(page.get_by_label("Your note")).to_have_text("")


def test_switching_books_keeps_each_draft_and_starts_the_next_capture_fresh(
    page, live_server
):
    sign_in(page, live_server)
    capture_urls = []
    for title in ("First source", "Second source"):
        page.get_by_role("link", name="Books", exact=True).click()
        page.get_by_role("link", name="Add a book", exact=True).click()
        page.get_by_label("Title").fill(title)
        page.get_by_role("button", name="Save book", exact=True).click()
        page.get_by_role("link", name="Capture a note from this book").click()
        capture_urls.append(page.url)
        expect(page.get_by_label("Source book").locator("option:checked")).to_have_text(
            title
        )
        expect(page.get_by_label("Your note")).to_have_text("")
        page.get_by_label("Your note").fill(f"Draft for {title}.")

    page.goto(capture_urls[0])
    expect(page.get_by_label("Your note")).to_have_text("Draft for First source.")
    page.get_by_label("Source book").select_option(label="Second source")
    page.get_by_role("button", name="Save and add another", exact=True).click()
    expect(page.get_by_label("Your note")).to_have_text("")
    expect(page.get_by_label("Source book").locator("option:checked")).to_have_text(
        "Second source"
    )
    page.get_by_label("Your note").fill("A fresh draft for the second source.")
    page.reload()
    expect(page.get_by_label("Your note")).to_have_text(
        "A fresh draft for the second source."
    )
    page.get_by_role("link", name="Resume previous capture").click()
    expect(page.get_by_label("Your note")).to_have_text("Draft for Second source.")

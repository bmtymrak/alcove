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
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page).to_have_url(note_url)
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
    second_tab.get_by_role("button", name="Save changes", exact=True).click()
    page.get_by_label("Your note").fill("Keep my pending thought.")
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_label("Your note")).to_have_text("Keep my pending thought.")
    expect(
        page.get_by_text("This Note changed elsewhere.", exact=False)
    ).to_be_visible()
    page.get_by_role("link", name="Open current note").click()
    expect(page.get_by_text("Saved in another tab.", exact=True)).to_be_visible()
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
    page.get_by_role("button", name="Save and add another", exact=True).click()
    expect(page.get_by_label("Your note")).to_have_text("")
    expect(page.get_by_label("Source book")).to_have_value(selected_book)
    page.get_by_role("button", name="Save and add another", exact=True).click()
    expect(
        page.get_by_text("Write something before saving.", exact=True)
    ).to_be_visible()
    expect(page.get_by_label("Source book")).to_have_value(selected_book)
    page.get_by_label("Your note").fill("Second marginalium.")
    page.get_by_role("button", name="Save note", exact=True).click()
    expect(page.get_by_role("link", name="Edit note", exact=True)).to_be_visible()
    page.goto(book_url)
    expect(page.locator(".note-content")).to_have_text(
        ["First marginalium.", "Second marginalium."]
    )
    page.get_by_label("Capture order").select_option("newest")
    page.get_by_role("button", name="Apply order", exact=True).click()
    expect(page.locator(".note-content")).to_have_text(
        ["Second marginalium.", "First marginalium."]
    )
    page.reload()
    expect(page.get_by_label("Capture order")).to_have_value("newest")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.get_by_role("link", name="Open note", exact=False).first.click()
    expect(page.get_by_role("link", name="Ways of Seeing", exact=True)).to_be_visible()
    page.get_by_role("link", name="Edit note", exact=True).click()
    page.get_by_label("Source book").select_option("")
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("link", name="Edit note", exact=True)).to_be_visible()
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
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page).to_have_url(note_url)
    expect(page.locator(".note-content ul li")).to_have_text(
        ["An idea", "Another idea"]
    )
    page.get_by_role("link", name="Edit note", exact=True).click()
    editor.press("ControlOrMeta+End")
    page.get_by_role("button", name="Numbered list", exact=True).click()
    page.get_by_role("button", name="Save changes", exact=True).click()
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
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("status")).to_have_text("Save not confirmed.")
    expect(editor.locator("strong")).to_have_text("An existing plain Note.")
    assert (
        page.request.get(live_server.url + f"/api/v1/notes/{note['id']}/").json()
        == note
    )
    page.unroute(endpoint)
    page.get_by_role("button", name="Save changes", exact=True).click()
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
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.locator(".note-content br")).to_have_count(1)

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
    expect(page.get_by_label("Your note")).to_have_value("   ")
    page.get_by_label("Your note").fill("Original thought.")
    page.get_by_role("button", name="Save note", exact=True).click()
    page.get_by_role("link", name="Edit note", exact=True).click()
    second_tab = page.context.new_page()
    second_tab.goto(page.url)
    second_tab.get_by_label("Your note").fill("Saved in another tab.")
    second_tab.get_by_role("button", name="Save changes", exact=True).click()
    page.get_by_label("Your note").fill("Keep my pending thought.")
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_label("Your note")).to_have_value("Keep my pending thought.")
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
    expect(page.get_by_label("Your note")).to_have_value("")
    expect(page.get_by_label("Source book")).to_have_value(selected_book)
    page.get_by_role("button", name="Save and add another", exact=True).click()
    expect(
        page.get_by_text("Write something before saving.", exact=True)
    ).to_be_visible()
    expect(page.get_by_label("Source book")).to_have_value(selected_book)
    page.get_by_label("Your note").fill("Second marginalium.")
    page.get_by_role("button", name="Save note", exact=True).click()
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
    page.goto(book_url)
    expect(page.locator(".note-content")).to_have_text(["First marginalium."])

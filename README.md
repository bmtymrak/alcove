# Alcove

A private Collection of reading notes, served by Django templates and a same-origin
versioned JSON API. Sign in to a Book library, add Books with optional authors,
and repeatedly capture their Notes with Save and add another. General Note capture,
inline Book reading, source editing, and capture or numeric page ordering are available
through HTML and JSON. Notes support paragraphs, bold/italic emphasis, lists,
quotations, and clickable website links in a limited open-source Tiptap editor
([Ticket #5](https://github.com/bmtymrak/alcove/issues/5)).

## Run locally

Install Python 3.11–3.13 and [uv](https://docs.astral.sh/uv/), then:

```sh
uv sync --frozen
uv run python manage.py migrate
uv run python manage.py provision_owner reader
uv run python manage.py runserver 127.0.0.1:8000
```

Open <http://127.0.0.1:8000/>. Owner provisioning prompts for a password and checks
Django's password rules. Repeating the command with the same username leaves the
password and Collection unchanged; it refuses a different owner. For unattended
setup, provide `ALCOVE_OWNER_PASSWORD` via the environment and use `--no-input`.
Unset that variable afterward. No public registration or account-management UI is
provided. Use Django's `changepassword reader` command to change the password.

Saved data lives in `data/alcove.sqlite3`, outside source control. Stop and restart
the server with the same database path to retain the Collection. To use another
persistent file, set `ALCOVE_DATABASE` to its absolute path; create its parent
directory first. Runtime dependencies and development tools are pinned in `uv.lock`.

## Deploy on a server

The [deployment runbook](docs/deployment.md) covers Compose setup, private HTTPS
access, owner provisioning, persistent SQLite, backups, isolated recovery, and
upgrades. The package runs Gunicorn with debug disabled and collects the
checked-in editor assets during the image build.

## Check the application

```sh
uv run playwright install chromium
# Linux hosts may also need: uv run playwright install-deps chromium
uv run mypy
uv run ruff check .
uv run ruff format --check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py spectacular --file /tmp/alcove-openapi.yaml --validate --fail-on-warn
diff -u docs/openapi.yaml /tmp/alcove-openapi.yaml
uv run pytest
```

Tests create a real SQLite file in a fresh temporary directory for each test run,
apply migrations, and never use the saved Collection. HTTP integration tests read
persisted results back through public routes and exercise sessions, CSRF, validation,
pagination, revision conflicts, and a second owner's private Collection. Browser
tests run a local Django server and Chromium at desktop and phone sizes; they cover
capture, repeated Book marginalia capture, inline reading, ordering, reload,
autosave, formatted round trips, website links, draft recovery, delayed and lost
responses, two-tab conflicts and resolution, and sign-out.
For a focused run use `uv run pytest tests/test_notes_http.py` or
`uv run pytest tests/test_browser.py`. The production restart and recovery test also needs OpenSSL.
If browser downloads are stored in a custom
location, set `PLAYWRIGHT_BROWSERS_PATH` for both installation and test runs.

## Application boundaries

`alcove.collections.for_owner` resolves the authenticated Collection.
`alcove.books` owns Book metadata changes and removal.
`alcove.notes.capture/edit` own content validation, projection, source validation,
Topic Assignment changes, and revision-checked mutation; `alcove.reading` owns scoped Book/Note retrieval,
ordering, and deterministic pagination.
`alcove.topics` owns the hierarchy, paths, and assignment replacement.
Both HTML views and JSON handlers call those interfaces with Collection context.
The modules persist directly through Django's ORM. Domain rules stay out of the
transport adapters. No internal module tests or persistence mocks are required.

Notes have UUID identifiers, UTC capture/update timestamps, a revision, canonical
versioned content, and a derived plain-text projection. The editor saves validated
`{version: 1, format: "tiptap", doc: ...}` documents. Shared content rules in
`alcove.note_content` validate the closed schema, derive readable plain text, and
render only supported tags with escaped text and absolute HTTP/HTTPS links.
Legacy `plain-text` documents remain readable and editable; opening one in the
editor converts it to paragraphs when saved. No data migration is needed. A title, Book, Topic, and specialized Note type are not
required. Each Note can have one source Book or none. Book titles need not be
unique; title alone is enough to create a Book. The library is the signed-in start
page at `/`, with all Notes still available at `/notes/`. A Book page shows its
Notes inline, oldest capture first by default, with newest-first, numeric
Page Number, and Chapter and page options. Use **Manage chapters** on a Book
page or while capturing or editing a Note to add, rename, and reorder named
or numbered Chapters. A Note can use one Chapter from its selected Book.
A Note can also have a free-text Source Reference for a
range, footnote, or other location. Save and add another retains the selected
Book and starts with empty location fields. Existing standalone Notes remain
unassigned after upgrading. Apply the new migrations before starting the server.

Existing Notes autosave content, source, and Topic changes after a short pause, with one
request at a time and visible saving, saved, failed, and conflict states
([Ticket #6](https://github.com/bmtymrak/alcove/issues/6)). Editing stays available
while saving. Failed requests retain pending content and offer Retry saving.
Conflicts pause saves: Review current note shows the saved text, source, and Topics without
replacing the editor, and Save my version applies the owner's reconciled content
against that reviewed revision. Open current note opens a separate tab for the
formatted saved version.
Without JavaScript, Save changes uses the same revision checks through HTML.
Creation still requires Save note or Save and add another.

The editor recovers unfinished captures and pending edits after navigation or
reload in the same tab. Drafts belong to the signed-in Collection and session.
After an uncertain capture response, retry confirms the same Note using its
capture UUID. Acknowledged captures clear the draft. Open **Topics** from the navigation to
create or rename roots and children. Capture and edit forms suggest existing
Topics by full path. Selecting a Topic replaces any selected ancestors or
descendants and keeps selections on other branches. Saved assignments appear
alongside Notes. Open a Note and select **Link a related Note** to find another
Note by text, Book, or Topic. Related Notes show their source and Topics, and
you can follow or remove the link from either Note. Select **Move to trash**
on a Note to hide it from reading and the link picker. Open **Trash** to restore
the Note with its surviving source, Topics, and Note Links, or confirm permanent
deletion. On a Book page, **Remove book** removes the Book and its Chapters
and keeps its active and trashed Notes with their remaining associations.
General capture offers drafts from removed Books in the same tab and session.
Trash has no expiry. Collection-wide search and portability are
planned separately.

## Editor assets

The browser editor uses pinned open-source Tiptap 3 packages without cloud services,
accounts, paid extensions, or runtime CDN requests. Its source is `frontend/editor.js`;
the locally served bundle and third-party license notices are checked in under
`alcove/static/alcove/`. Node.js is needed only to rebuild the assets:

```sh
npm ci
npm run build
```

Commit the rebuilt `editor.js` and `editor.NOTICES.txt` together with source changes.
The enhanced capture/edit forms save through the same-origin JSON API with CSRF;
HTML form posts use the same content validation. Without JavaScript, new plain-text
capture remains available; formatted documents can be recovered/edited in the
form's JSON recovery field without flattening them.

See [the API guide](docs/api.md) and [checked OpenAPI schema](docs/openapi.yaml).

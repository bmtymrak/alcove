# Alcove

A private Collection of reading notes, served by Django templates and a same-origin
versioned JSON API. This first slice implements owner sign-in and standalone Note
capture, reading, and explicit editing ([Ticket #3](https://github.com/bmtymrak/alcove/issues/3)).

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

Local development defaults to debug mode and a development-only secret. For a
deployment set `ALCOVE_DEBUG=0`, a private random `ALCOVE_SECRET_KEY`, and
`ALCOVE_ALLOWED_HOSTS` (comma-separated hostnames). This enables secure session and
CSRF cookies, so HTTPS is required. Keep the secret stable across restarts. A
production server, TLS routing, backups, and deployment packaging are later work;
`runserver` is only for local development.

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
capture, reload, explicit editing, retained invalid input, conflicts, and sign-out.
For a focused run use `uv run pytest tests/test_notes_http.py` or
`uv run pytest tests/test_browser.py`. If browser downloads are stored in a custom
location, set `PLAYWRIGHT_BROWSERS_PATH` for both installation and test runs.

## Application boundaries

`alcove.collections.for_owner` resolves the authenticated Collection.
`alcove.notes.capture/edit` own content validation, projection, and mutation;
`alcove.reading.notes/note` own scoped retrieval and deterministic pagination.
Both HTML views and JSON handlers call those interfaces with Collection context.
The modules persist directly through Django's ORM. Domain rules stay out of the
transport adapters. No internal module tests or persistence mocks are required.

Notes have UUID identifiers, UTC capture/update timestamps, a revision, canonical
versioned content, and a derived plain-text projection. This slice accepts a
`plain-text` document and safely renders it as escaped text. Future formatting can
extend supported document formats while keeping capture/read/edit operations and
the plain-text projection. A title, Book, Topic, and specialized Note type are not
required. Books, rich text, drafts, autosave, retry idempotency, search, Topics,
links, trash, and portability remain later tickets from Spec #2.

See [the API guide](docs/api.md) and [checked OpenAPI schema](docs/openapi.yaml).

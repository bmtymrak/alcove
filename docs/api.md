# JSON API v1

The API and rendered pages use the same session and shared Collection, Note, and
Reading interfaces. All endpoints below, including `/api/v1/schema/`, require
sign-in. Get `/login/`, then POST the username, password, and CSRF token from that
page. There is no registration endpoint. Django rotates the CSRF token at login;
use the new `csrftoken` cookie afterward. POST `/logout/` with CSRF to revoke the
session. Unsafe API requests require `Content-Type: application/json`, the session
cookie, and `X-CSRFToken` matching the CSRF cookie. Same-origin Django CSRF checks
also validate Origin/Referer. Non-browser and cross-origin authentication are deferred.

The machine-readable contract is [openapi.yaml](openapi.yaml), generated with
drf-spectacular and served to authenticated users at `/api/v1/schema/`. The suite
checks schema drift and validates real request/response examples against it.

| Operation | Route | Success |
| --- | --- | --- |
| List Notes | `GET /api/v1/notes/?page=1` | `200` |
| Capture a Note | `POST /api/v1/notes/` | `201`, with a relative `Location` header |
| Read a Note | `GET /api/v1/notes/{uuid}/` | `200` |
| Explicitly edit a Note | `PATCH /api/v1/notes/{uuid}/` | `200` |

Capture body:

```json
{"content": {"version": 1, "format": "plain-text", "text": "A sentence is enough."}}
```

An edit sends the complete replacement content and the last-read `revision`:

```json
{"content": {"version": 1, "format": "plain-text", "text": "A reconsidered thought."}, "revision": 1}
```

A Note response has `id` (stable UUID), `content` (canonical document), `plain_text`
(derived text), `captured_at` and `updated_at` (UTC ISO 8601), and `revision`
(positive integer starting at 1). Editing preserves identity and capture time and
increments the revision atomically. There is no caller-supplied ownership field;
every lookup and change uses the session owner's Collection. Another owner's UUID
and a nonexistent UUID both return `404`.

Edit revisions must be integers between 1 and 9223372036854775806, leaving room
for the increment in SQLite storage. Out-of-range preconditions are field errors
(`400`) and do not change the Note.

Content preserves whitespace, Unicode, and line breaks. Blank or whitespace-only
content, null characters, unsupported formats/versions, and content over 100,000
characters are rejected. HTML-looking input remains literal escaped text. Unknown
request fields are rejected. Version 1 currently supports `plain-text` only;
formatting will extend the content schema in a later slice.

List results have `count`, `page`, `page_size` (20), and `results`. Pages start at 1;
an empty Collection has an empty page 1. Invalid/out-of-range pages return `404`.
Ordering is oldest capture first, then UUID as the deterministic tiebreaker. No
filter or ordering parameters are supported yet.

## Errors and safe retries

Errors use the following envelope (field values may be nested for document errors):

```json
{"error": {"code": "invalid", "message": "Check the submitted fields.", "fields": {"content": ["Write something before saving."]}}}
```

| Status | Meaning |
| --- | --- |
| `400` | Invalid/missing/unknown fields (`invalid`) or malformed JSON (`parse_error`). |
| `403` | Sign-in required (`not_authenticated`) or failed CSRF (`permission_denied`). |
| `404` | Note or page not found in the current Collection (`not_found`). |
| `405` | Unsupported method (`method_not_allowed`). |
| `409` | Stale revision (`conflict`); content was not changed. |
| `415` | Unsupported request media type (`unsupported_media_type`). |

Retain pending content after errors. For `409`, fetch the latest Note and let the
owner reconcile the changes before submitting with its revision. Retrying an edit
with an already-consumed revision produces a conflict. Capture idempotency is not
delivered yet: repeating a successful POST creates another Note, so after an
ambiguous network result inspect the Collection before resubmitting. Never infer
successful saving from a timeout. Restore preview/confirmation and other operations
will be documented with their delivery tickets.

The HTML capture/edit forms retain submitted input on validation and revision
errors. This slice uses explicit saves; it makes no draft-recovery or autosave
promise. Authentication redirects and HTML form errors are specific to the HTML
delivery path; JSON errors use the envelope above for matched API operations.

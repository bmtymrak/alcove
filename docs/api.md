# JSON API v1

The API and rendered pages use the same session and shared Collection, Book,
Chapter, Note, Topic, and Reading interfaces. All endpoints below, including `/api/v1/schema/`, require
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
| List Books | `GET /api/v1/books/?page=1` | `200` |
| Add a Book | `POST /api/v1/books/` | `201`, with a relative `Location` header |
| Read a Book | `GET /api/v1/books/{uuid}/` | `200` |
| Edit Book metadata | `PATCH /api/v1/books/{uuid}/` | `200` |
| List a Book's Chapters | `GET /api/v1/books/{book_id}/chapters/` | `200`, an ordered array |
| Append a Chapter | `POST /api/v1/books/{book_id}/chapters/` | `201` |
| Rename or move a Chapter | `PATCH /api/v1/books/{book_id}/chapters/{chapter_id}/` | `200` |
| Read a Book's Notes | `GET /api/v1/books/{uuid}/notes/?order=oldest&page=1` | `200` |
| Read a Book's Notes grouped by Topic | `GET /api/v1/books/{uuid}/note-groups/?page=1` | `200` |
| List Topics or autocomplete | `GET /api/v1/topics/?q=history` | `200`, an ordered array |
| Create a root or child Topic | `POST /api/v1/topics/` | `201`, with a relative `Location` header |
| Read a Topic | `GET /api/v1/topics/{uuid}/` | `200` |
| Read a Topic's Notes | `GET /api/v1/topics/{uuid}/notes/?mode=branch&page=1` | `200` |
| Rename a Topic | `PATCH /api/v1/topics/{uuid}/` | `200` |
| List Notes | `GET /api/v1/notes/?page=1` | `200` |
| Capture a Note | `POST /api/v1/notes/` | `201` on creation or `200` on replay, both with a relative `Location` header |
| Read a Note | `GET /api/v1/notes/{uuid}/` | `200` |
| Edit a Note (including autosave) | `PATCH /api/v1/notes/{uuid}/` | `200` |

A Book needs only `{"title": "Ways of Seeing"}`. An optional `author` defaults to
an empty string. Metadata is trimmed and limited to 300 characters per field;
blank titles and null characters are rejected. Distinct Books can share a title.
A Book response has `id` (stable UUID), `title`, and `author`. PATCH updates only
submitted metadata fields; `{"author": ""}` clears the author. Null values and
unknown fields are rejected. Book metadata edits currently use last-write-wins.

The Chapter list contains the full sequence in reading order and can be empty.
Each Chapter has a stable UUID `id`, a string `label`, and a one-based integer
`position`. Send `{"label": "Prologue"}` to append to the end. Labels are trimmed
and must contain 1–300 characters. Use strings such as `"1"` for numbered Chapters.
PATCH accepts either or both of `label` and `position`. Moving to a position
between 1 and the current Chapter count shifts the intervening Chapters.
Moves and appends apply atomically to the current sequence. Fetch the list
again to read all positions after a move. An invalid label or position returns
`400`. A Book outside the signed-in Collection or a Chapter outside the URL's
Book returns `404`.

Capture body:

```json
{"content": {"version": 1, "format": "plain-text", "text": "A sentence is enough."}}
```

Capture may also include `"book": "<book-uuid>"`; omission or null creates a
standalone Note. Each Note has at most one source Book.
Send `"chapter": "<chapter-uuid>"` to associate a Chapter of that Book.
Omission or null leaves the Chapter unset. A Chapter that does not belong to
the selected Book returns a `400` field error on `chapter`. This also applies
to unknown Chapters and to any non-null Chapter when the Book is unset.

Send an optional `"page_number": 42` for the starting page and
`"source_reference": "pp. 42–44, footnote 3"` for the written location. Either
field can be used independently, including on a standalone Note. Page Numbers
must be JSON integers from 1 to 2147483647. Source References are plain text,
with line endings normalized to LF. Omitted values default to null for the page
and the empty string for the reference.

Send an optional `"capture_id": "<uuid>"` to make a capture safe to retry.
Generate a fresh UUID for each new capture, even when two Notes have identical
content and source. After a timeout or lost response, resend the same UUID,
document, Book, Chapter, Page Number, Source Reference, and ordered Topic operations. The first successful request
creates the Note and returns `201`. A replay returns `200` and the current
representation of the same Note,
including any later edits. Both responses include its `Location`. The identity
is scoped to the signed-in Collection. Reusing it there with different content, source, or
Topic operations returns `409` with `error.code = "capture_conflict"` and leaves the Note
intact. Invalid requests do not reserve identities. Omitting the UUID requests a
new Note on every successful POST. Capture identities are accepted only on create.

An edit sends the last-read `revision` and the fields to change. Content, when
sent, replaces the complete document:

```json
{"content": {"version": 1, "format": "plain-text", "text": "A reconsidered thought."}, "revision": 1}
```

Send `{"book": "<book-uuid>", "revision": 1}` to assign or change the source,
or `{"book": null, "revision": 1}` to clear it. Send `"chapter": null`,
`"page_number": null`, or `"source_reference": ""` to clear those fields. PATCH
preserves omitted fields, except that changing or clearing the Book clears
its Chapter unless a Chapter of the new Book is explicitly supplied.
Source changes use the same revision precondition as content. A stale change
returns `409` without saving. Another Collection's
Book and an unknown Book both produce a `400` field error on `book` without saving.

A Note response has `id` (stable UUID), `book` and `chapter` (UUIDs or null),
`chapter_label` (the current label or null), `page_number`
(integer or null), `source_reference` (string), `content` (canonical document), `plain_text`
(derived text), `captured_at` and `updated_at` (UTC ISO 8601), and `revision`
(positive integer starting at 1). Editing preserves identity and capture time and
increments the revision atomically. There is no caller-supplied ownership field;
every lookup and change uses the session owner's Collection. Another owner's UUID
and a nonexistent UUID both return `404`.

Edit revisions must be JSON integers between 1 and 9223372036854775806 (strings,
booleans, floating-point values, and omitted revisions are rejected), leaving room
for the increment in SQLite storage. Out-of-range preconditions are field errors
(`400`) and do not change the Note.

## Topics and Topic Assignments

Create a Topic with a string `label` and optional `parent` UUID. Omission or
null creates a root Topic. Labels are trimmed, internal whitespace is collapsed, and labels are limited
to 300 characters. They are
compared within each sibling group using Unicode case folding and normalization.
Roots form their own sibling group. A parent must belong to the signed-in
Collection. Rename accepts a `label` field. A Topic retains its original parent
when renamed, and descendant paths reflect the new label on the next read.

Topic responses include the stable `id`, the direct `parent` UUID or null,
the `label`, and `path` as an array of labels from root to leaf. The
`ancestors` array contains the corresponding UUIDs from root to parent.
`full_path` is the display string joined with ` › `. A backslash escapes a
literal separator or backslash within a label. The list follows tree order
with siblings sorted by normalized label. Supply `q` to match part of a label
or full path, case insensitively. The query returns only the owner's Topics.

Send `topic_changes` on capture or revision-checked edit. Each operation names a
Topic UUID and an `assign` or `unassign` action:

```json
{
  "revision": 1,
  "topic_changes": [
    {"action": "assign", "topic": "11111111-1111-4111-8111-111111111111"},
    {"action": "unassign", "topic": "22222222-2222-4222-8222-222222222222"}
  ]
}
```

The server applies operations in order. Assigning a Topic removes any explicitly
assigned ancestors or descendants while preserving independent branches.
Unassigning removes the named assignment if present. Omission and an empty array
both preserve existing assignments. Every referenced Topic must belong to the
Collection. An invalid operation rejects the entire save, including content,
source, and revision changes. The response field `topics` is an array of
explicitly assigned Topics in tree order, including their full paths.

The signed-in Topic tree at `/topics/` provides create and rename forms. The
Note editor offers full-path suggestions and retains selections in capture and
edit drafts. The native HTML forms accept explicit assignment and unassignment
selections and apply unassignments first.

## Canonical Note content

`content` is a complete versioned JSON document, never raw HTML. The limited
open-source editor uses this representation for general and Book capture and
for editing existing Notes:

```json
{
  "version": 1,
  "format": "tiptap",
  "doc": {
    "type": "doc",
    "content": [
      {"type": "blockquote", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "A quotation."}]}
      ]},
      {"type": "paragraph", "content": [
        {"type": "text", "text": "My thought. ", "marks": [{"type": "italic"}]},
        {"type": "text", "text": "Related reading", "marks": [
          {"type": "link", "attrs": {"href": "https://example.org/reading"}}
        ]}
      ]}
    ]
  }
}
```

The closed schema is recorded under `NoteContent` and its recursive components in
OpenAPI. Allowed blocks are `paragraph`, `blockquote`, `bulletList`, and
`orderedList`. The root `doc` and blockquotes contain one or more blocks. Lists
contain one or more `listItem` nodes, each beginning with a paragraph and optionally
followed by more blocks (including nested lists). Paragraphs may be empty and
contain only `text` and `hardBreak` nodes. Text nodes need a nonempty string.
Both text and hard breaks may optionally carry `marks`: `bold`, `italic`, or `link`, each at most once per node.
Only link marks accept `attrs`, containing just `href`. Ordered lists optionally
accept `attrs` containing just `start` (integer 1–2147483647; omitted means 1).
All other node/mark attributes and unsupported properties, nodes, or formats are
rejected, including images, headings, styles, event handlers, and raw HTML.

Links must be absolute `http://` or `https://` addresses with a host and a valid
nonzero port if present, at most 2,048 characters long, without whitespace, control
characters, or backslashes. Relative URLs and other protocols, including
`javascript:`, `data:`, `file:`, and `mailto:`, are rejected. Supported tags are
rendered from validated content with all text and link attributes escaped; Notes
never render submitted HTML. Text such as `<script>` remains literal text.

`plain_text` is derived by concatenating inline text, translating `hardBreak` to
a newline, and joining sibling blocks/list items with a newline, recursively.
There are no bullets, numbering, or markup in this projection; link labels appear
as text, without appending the URL. Whitespace and Unicode are preserved. The
projection must contain non-whitespace text and be at most 100,000 characters.
Documents with only empty paragraphs, list items, line breaks, or whitespace do
not create Notes. Null characters and unpaired Unicode surrogates are rejected.
Tiptap documents allow at most 10,000 nodes and depth 20 (root is depth 0).
OpenAPI describes these additional semantic limits; they are enforced by the
shared Note content module for both transports.

Existing `{ "version": 1, "format": "plain-text", "text": "..." }` documents remain
accepted without migration and are returned unchanged until edited. They use the
same text/length/nonempty rules. The browser converts them to paragraphs on save,
retaining their text. No Note requires a title or type, and quotations and
commentary can coexist in one document. Unknown request fields are rejected.

Book and Note list results have `count`, `page`, `page_size` (20), and `results`. Pages start at 1;
an empty Collection has an empty page 1. Invalid/out-of-range pages return `404`.
The all-Notes list is oldest capture first, then UUID as the deterministic
tiebreaker. The library is ordered by title then UUID. A Book's Notes use the same
pagination envelope, scoped to that Book, with `order=oldest` by default or
`order=newest` to reverse both capture timestamp and UUID. `order=page` sorts by
ascending numeric Page Number with missing pages last. `order=chapter` sorts
by the Book's explicit Chapter positions with unassigned Notes last. Within
each Chapter and among unassigned Notes, it uses the same numeric page ordering.
Both modes break ties by oldest capture first, then ascending UUID.
Invalid ordering returns `404`. HTML Book pages use
the same ordering and pagination and retain the selected order across pages.

Topic Notes use the same pagination envelope. The default `mode=branch`
includes Notes explicitly assigned to the selected Topic or any descendant.
`mode=direct` includes only Notes explicitly assigned to the selected Topic.
Results span Books and standalone Notes and contain each matching Note once
in capture order (oldest first, then UUID). The `topics` field lists actual
assignments, and browsing never writes an assignment. An unknown mode returns
`404`. The HTML Topic view at `/topics/{uuid}/` keeps the mode across pages.

Book Note groups use the same envelope with `results` containing objects
with a `topic` (the Topic representation or null for Unassigned) and `notes`
(an array of Note representations). Groups sort alphabetically by full
Topic path, case-insensitively, then by Topic UUID, with Unassigned last.
Within each group Notes sort by capture time, oldest first, then UUID.
Pagination takes 20 Note appearances from this order before assembling the
page's groups. A group can continue on the next page, and `count` counts
appearances. A Note with multiple assignments has the same Note UUID and
revision in every group. Edit it using the regular Note endpoint. The HTML
Book view offers the same grouping with `?order=topic`.

No search or general Note filters are supported yet.

## Errors and safe retries

Errors use the following envelope (field values may be nested for document errors):

```json
{"error": {"code": "invalid", "message": "Check the submitted fields.", "fields": {"content": ["Write something before saving."]}}}
```

| Status | Meaning |
| --- | --- |
| `400` | Invalid/missing/unknown fields (`invalid`) or malformed JSON (`parse_error`). |
| `403` | Sign-in required (`not_authenticated`) or failed CSRF (`permission_denied`). |
| `404` | Book, Chapter, Note, Topic, order, mode, or page not found at the requested route (`not_found`). |
| `405` | Unsupported method (`method_not_allowed`). |
| `409` | Stale edit revision (`conflict`) or capture UUID reused for different input (`capture_conflict`). |
| `415` | Unsupported request media type (`unsupported_media_type`). |

Revision conflicts have this additional required field:

```json
{"error":{"code":"conflict","message":"This Note changed elsewhere. Your text has not been saved. Review the current Note before trying again.","fields":{},"current_revision":2}}
```

`current_revision` is the revision at conflict detection, not permission to
overwrite it. Retain pending content after errors. For `409`, GET the latest Note
and let the owner review its content, source, and Topics and reconcile the changes before
submitting with its revision. A concurrent change after review still returns
`409`. Every rejected edit preserves content, source, Topics, revision, and timestamps.
Retrying an edit with an already-consumed revision produces a conflict.
Restore preview/confirmation and other operations will be documented with their
delivery tickets.

The signed-in HTML start page is the Book library at `/`. `/notes/` still lists
all Notes, including standalone Notes. `/books/new/` adds a Book and
`/books/{uuid}/edit/` edits its metadata. `/books/{uuid}/` reads its Notes inline
with links to individual Notes. `/books/{uuid}/notes/new/` preselects the Book;
Save and add another opens a fresh capture with the saved source selected.
General capture at `/notes/new/` offers the same source selector and repeat action.
Clearing the selection makes the next capture standalone.

Content validation returns `400` with `error.code = "invalid"` and
`error.fields.content` as an array of messages, for example:

```json
{"error":{"code":"invalid","message":"Use only supported Note formatting and http/https links.","fields":{"content":["Use only supported Note formatting and http/https links."]}}}
```

An empty document returns `"Write something before saving."`. Invalid content
never creates a Note or changes existing content, revision, or timestamps.

Enhanced forms send the canonical document through the JSON API with CSRF. Capture
is explicit and navigates only after a confirmed successful response. The browser
keeps the submitted document, source, and capture UUID together until it can
confirm an uncertain result. Retry uses that same input. Save and add another
starts a fresh capture with the submitted Book selected. Existing-note
content and source edits autosave after 500 ms of inactivity, serialize requests,
and remain in the editor. A successful response confirms only the snapshot sent;
newer edits remain pending until their own save succeeds. Saving, saved, failed,
and conflict status is visible. Validation, network, and server errors retain
formatted pending input, pause automatic retries, and offer Retry saving. A lost
response never implies success, even after undoing the pending edits; retrying
uses the last confirmed revision and may return a conflict if the write committed.

Conflicts pause autosave. Review current note fetches the current text, source,
and revision without replacing pending content. The owner can reconcile in the
editor and explicitly Save my version against the reviewed revision; another
concurrent edit still conflicts. Open current note opens the formatted saved
version in another tab.

Each browser tab stores unfinished captures by entry point and pending edits by
Note in session storage. Opening a different Book's capture keeps its own source
preselection. If Save and add another starts a fresh capture at an entry point
with an unfinished draft, the capture page links to the other draft. Drafts
survive navigation and reload in the tab. Pending
edits keep their last confirmed revision so that reopening the editor can detect
intervening changes. When storage is unavailable the editor warns before leaving
with pending input. Drafts are scoped to the Collection and sign-in session.
Sign-out requests that the browser clear site storage, and a subsequent sign-in
cannot recover the previous session's drafts. Drafts are local to the tab and do
not sync across devices.

Native HTML form posts accept the same document serialized in the
`content_document` field, with the same validation rules; an empty/omitted field
uses legacy plain text from `content`. Invalid JSON and rejected documents remain
in the recovery field, escaped, instead of being stripped or replaced. The plain
text field for an existing formatted Note is read-only without the editor, so a
source-only edit preserves the canonical document. Native capture forms also carry
a hidden `capture_id` and support resubmitting the same input. Authentication redirects and
HTML form errors are specific to the HTML path; JSON errors use the envelope
above for matched API operations. Explicit HTML edits also require the last-read
`revision` hidden field and return `409` with pending input retained on conflicts;
they never replace it with the newly read revision automatically.

# JSON API v1

The API and rendered pages use the same session and shared Collection, Book,
Chapter, Note, Topic, and Reading interfaces. All endpoints below, including `/api/v1/schema/`, require
sign-in. Get `/login/`, then POST the username, password, and CSRF token from that
page. There is no registration endpoint. Django rotates the CSRF token at login;
use the new `csrftoken` cookie afterward. POST `/logout/` with CSRF to revoke the
session. Unsafe API requests require the session cookie and `X-CSRFToken` matching
the CSRF cookie. Send `Content-Type: application/json` with JSON bodies. Same-origin Django CSRF checks
also validate Origin/Referer. Non-browser and cross-origin authentication are deferred.

The deployment probe at `GET /healthz` is separate from the versioned API.
See the [deployment runbook](deployment.md#start-from-a-clean-checkout) for its
response and access contract.

The machine-readable contract is [openapi.yaml](openapi.yaml), generated with
drf-spectacular and served to authenticated users at `/api/v1/schema/`. The suite
checks schema drift and validates real request/response examples against it.

| Operation | Route | Success |
| --- | --- | --- |
| List Books | `GET /api/v1/books/?page=1` | `200` |
| Add a Book | `POST /api/v1/books/` | `201`, with a relative `Location` header |
| Read a Book | `GET /api/v1/books/{uuid}/` | `200` |
| Edit Book metadata | `PATCH /api/v1/books/{uuid}/` | `200` |
| Remove a Book and keep its Notes | `DELETE /api/v1/books/{uuid}/` | `204` |
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
| Preview a Topic move | `POST /api/v1/topics/{uuid}/move/preview/` | `200`, with a confirmation token |
| Move a Topic | `POST /api/v1/topics/{uuid}/move/` | `200`, with the updated Topic |
| Preview a Topic removal | `POST /api/v1/topics/{uuid}/remove/preview/` | `200`, with a confirmation token |
| Remove a Topic | `POST /api/v1/topics/{uuid}/remove/` | `204` |
| List or search active Notes | `GET /api/v1/notes/?q=essay&page=1` | `200` |
| Capture a Note | `POST /api/v1/notes/` | `201` on creation or `200` on replay, both with a relative `Location` header |
| Read a Note | `GET /api/v1/notes/{uuid}/` | `200` |
| Edit a Note (including autosave) | `PATCH /api/v1/notes/{uuid}/` | `200` |
| Move a Note to trash | `DELETE /api/v1/notes/{uuid}/` | `204` |
| List trashed Notes | `GET /api/v1/notes/trash/?page=1` | `200` |
| Restore a Note | `POST /api/v1/notes/{uuid}/restore/` | `204` |
| Permanently delete a trashed Note | `DELETE /api/v1/notes/{uuid}/delete-permanently/` | `204` |
| Find a Note to link | `GET /api/v1/notes/{note_id}/link-candidates/?q=essay&page=1` | `200` |
| List a Note's related Notes | `GET /api/v1/notes/{note_id}/links/?page=1` | `200` |
| Link two Notes | `POST /api/v1/notes/{note_id}/links/` | `201` |
| Remove a Note Link | `DELETE /api/v1/notes/{note_id}/links/{related_note_id}/` | `204` |

## Search active Notes

The Notes list accepts the same parameters as the browser's `/notes/` page.
All parameters are optional and can be combined.

| Parameter | Behavior |
| --- | --- |
| `q` | Match all supplied words across readable Note text, the source Book title, and directly assigned Topic labels. Matching is case-insensitive and ignores Latin accents. Punctuation separates words. Quotes, wildcards, and Boolean operators have no special meaning. An empty query lists active Notes, and a punctuation-only query finds no Notes. |
| `book` | Restrict results to the source Book UUID. |
| `topic` | Restrict results to a Topic UUID. |
| `mode` | With a Topic, `branch` (default) includes descendant assignments and `direct` requires an explicit assignment to the selected Topic. |
| `page` | 1-based page, with 20 unique Notes per page. Results are oldest first by capture timestamp, with the Note UUID breaking ties. |

Results use the existing `count`, `page`, `page_size`, and `results` envelope.
Unknown or malformed filter UUIDs, Books or Topics outside the signed-in
Collection, invalid modes, and unavailable pages return `404`. Trashed Notes
stay out of search until restored.

## Books, Chapters, and capture

A Book needs only `{"title": "Ways of Seeing"}`. An optional `author` defaults to
an empty string. Metadata is trimmed and limited to 300 characters per field;
blank titles and null characters are rejected. Distinct Books can share a title.
A Book response has `id` (stable UUID), `title`, and `author`. PATCH updates only
submitted metadata fields; `{"author": ""}` clears the author. Null values and
unknown fields are rejected. Book metadata edits currently use last-write-wins.

Book removal accepts no request body or an empty JSON object. It atomically
deletes the Book and its Chapters and clears both associations from active and
trashed Notes. Affected Notes keep their content, Page Numbers, Source
References, Topics, and Note Links. Their revision and update timestamp advance,
so an edit using the old revision receives a `409` conflict. Restoring a
trashed Note keeps it detached. A capture retry with the original UUID and
payload still returns the saved active Note with its current associations.
An unknown or out-of-Collection Book returns `404`, including a repeat
removal. A nonempty JSON body returns `400`.

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
A replay while the Note is in trash or after permanent deletion also returns
`409 capture_conflict`. The server retains only the Collection-scoped capture
UUID after permanent deletion so a delayed retry cannot recreate the Note.
A restored Note can confirm a replay with the original input again.

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
(derived text), `captured_at` and `updated_at` (UTC ISO 8601), `trashed_at`
(UTC ISO 8601 or null), and `revision`
(positive integer starting at 1). Editing preserves identity and capture time and
increments the revision atomically. There is no caller-supplied ownership field;
every lookup and change uses the session owner's Collection. Another owner's UUID
and a nonexistent UUID both return `404`.

Edit revisions must be JSON integers between 1 and 9223372036854775806 (strings,
booleans, floating-point values, and omitted revisions are rejected), leaving room
for the increment in SQLite storage. Out-of-range preconditions are field errors
(`400`) and do not change the Note.

## Note lifecycle

Active Notes have a null `trashed_at`. Ordinary Note reads and edits, Book lists
and groups, Topic lists, related Notes, and the link picker use active Notes.
An unavailable source Note returns `404`. Creating a Note Link to a trashed
target returns the same `400` field error as an unknown target.

Moving an active Note to trash sets `trashed_at` and keeps its content, source,
Topic Assignments, and Note Links. Trash is owner-scoped and uses the standard
20-Note pagination envelope, most recently trashed first with descending UUID
as the tiebreaker. Notes stay in trash until the owner acts.

Restoring clears `trashed_at` and returns the same Note to ordinary reading with
its surviving associations. Trashing and restoring each advance the revision
and update `updated_at` so an editor opened before the change cannot silently
save a stale draft. Permanent deletion removes the Note, its Topic Assignments,
and every Note Link involving it. Other Notes and their remaining links survive.

Lifecycle mutations take no request fields. Omit the body or send an empty
JSON object. Malformed JSON and unexpected fields return `400`.
For an owned Note in the wrong state, including a repeated trash or restore,
the API returns `409 invalid_note_state`. Unknown, permanently deleted, and
foreign Note UUIDs return `404 not_found`. Rejected actions leave the
Collection unchanged. In HTML, open **Trash** to restore or review and confirm
permanent deletion. Mutations use CSRF-protected forms. If the Note changes
after you open the permanent deletion page, reopen it to confirm again.

## Note Links

Send `{"related_note": "<note-uuid>"}` to link the two Notes. The response
echoes the related Note UUID. The same unordered pair appears under either
Note, and either endpoint can be used to remove it. Link changes leave
both Notes' revisions, timestamps, and content intact.

The candidate picker matches a trimmed literal substring against readable
Note text, Book title or author, Chapter label, Source Reference, or assigned
Topic path. An empty query browses all eligible Notes. The picker excludes the
current Note and Notes already linked to it. Candidate and related Note lists
use the standard 20-item pagination envelope, in capture order with UUID as
the final tiebreaker. Each result has the regular Note fields, including Topic
paths, plus `book_title` (string or null). Use its `id` to open the same Note
at `GET /api/v1/notes/{note_id}/`.

| Condition | Response |
| --- | --- |
| Create with the same Note at both endpoints | `400`, `self_link` with a `related_note` field error |
| Create with an unknown or foreign related Note | `400`, `invalid` with the same `related_note` field error for both cases |
| Create a pair that already exists in either order | `409`, `duplicate_link` with a `related_note` field error |
| Address an unknown or foreign source Note | `404` |
| Remove an absent link, including a repeated removal or a foreign endpoint | `404` |

Rejected operations leave existing links intact. After an uncertain create
response, read the list or retry the same pair and check for `duplicate_link`.
Removal needs no request body.

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

The signed-in Topic tree at `/topics/` provides create, rename, move, and removal forms. The
Note editor offers full-path suggestions and retains selections in capture and
edit drafts. The native HTML forms accept explicit assignment and unassignment
selections and apply unassignments first.

### Move and remove Topics

For a move, send `{"parent": "<uuid>"}` or `{"parent": null}` to move to the
root. The destination must be in the same Collection and outside the moved
branch. Sibling labels must remain distinct.

For removal, send `{"mode": "promote_children"}` to move direct children to the
removed Topic's parent or to the root if it has no parent. Their descendants
move with them. Sibling label collisions block promotion. Use
`{"mode": "remove_subtree"}` to remove the Topic and all its descendants.

Preview responses list affected `topics` with their current representation and
`new_path`. A null `new_path` marks a Topic for removal. Each affected
assignment includes a `note` UUID, a short `note_excerpt`, a `note_trashed`
flag, and its assigned
`topic`. Move previews pair each conflicting descendant assignment with its
`ancestor` assignment. Removal previews list the assignments to clear.

Apply by repeating the destination or removal mode with the preview's
`confirmation` token. If the move preview lists conflicts, also send
`"resolution": "keep_ancestors"` or `"resolution": "keep_descendants"`.
That choice applies to all listed conflicts. Apply revalidates the operation and
returns `409 stale_preview` if the valid operation now has a different preview.
Fetch a fresh preview before retrying. Invalid changes return `400`. Changes
to the hierarchy and assignments commit together.

Removing a Topic clears its assignments and preserves the Notes and their
source details. A Note whose assignments are cleared advances its revision so
an open editor can review the change before saving a stale draft. Topic paths
in browsing and suggestions reflect the new hierarchy on the next read.

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

The Note Link picker provides the delivered Note search. Collection-wide
search and general Note filters are planned separately.

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
| `409` | Stale edit revision (`conflict`), capture UUID conflict (`capture_conflict`), or wrong lifecycle state (`invalid_note_state`). |
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
Collection export and restore preview/confirmation are planned separately.

The signed-in HTML start page is the Book library at `/`. `/notes/` still lists
all active Notes, including standalone Notes. `/books/new/` adds a Book and
`/books/{uuid}/edit/` edits its metadata. `/books/{uuid}/` reads its Notes inline
with links to individual Notes. `/books/{uuid}/notes/new/` preselects the Book;
Save and add another opens a fresh capture with the saved source selected.
General capture at `/notes/new/` offers the same source selector and repeat action.
Clearing the selection makes the next capture standalone.
The Book page links to `/books/{uuid}/remove/`, which explains what is kept
and confirms removal with a CSRF-protected POST. In the same tab and session,
general capture can reopen drafts from removed Books with the source cleared.

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
starts a fresh capture with the saved Note's current Book selected. Existing-note
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

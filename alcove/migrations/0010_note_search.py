from django.db import migrations

# If a later SQLite migration rebuilds a source table, drop this view and its
# triggers before the rebuild, then recreate them against the new table.
CREATE_SEARCH = """
CREATE VIRTUAL TABLE alcove_note_search USING fts5(
    note_id, document,
    tokenize = "unicode61 remove_diacritics 2 categories 'L* N* Co M*'"
);

CREATE VIEW alcove_note_search_documents AS
SELECT note.id AS note_id,
       note.plain_text || ' ' || COALESCE(book.title, '') || ' ' ||
       COALESCE((
           SELECT group_concat(topic.label, ' ')
           FROM alcove_topicassignment AS assignment
           JOIN alcove_topic AS topic ON topic.id = assignment.topic_id
           WHERE assignment.note_id = note.id
             AND topic.collection_id = note.collection_id
       ), '') AS document
FROM alcove_note AS note
LEFT JOIN alcove_book AS book
    ON book.id = note.book_id AND book.collection_id = note.collection_id
WHERE note.trashed_at IS NULL;

INSERT INTO alcove_note_search (note_id, document)
SELECT note_id, document FROM alcove_note_search_documents;
"""

# Use an indexed UUID for refreshes. Implicit SQLite rowids can change on VACUUM.
REFRESH_NOTE = """
CREATE TRIGGER alcove_note_search_refresh
INSTEAD OF INSERT ON alcove_note_search_documents BEGIN
    DELETE FROM alcove_note_search WHERE note_id MATCH NEW.note_id;
    INSERT INTO alcove_note_search (note_id, document)
    SELECT note_id, document FROM alcove_note_search_documents
    WHERE note_id = NEW.note_id;
END;
"""


def refresh_on(name, event, note_ids):
    return f"""
    CREATE TRIGGER alcove_note_search_{name} AFTER {event} BEGIN
        INSERT INTO alcove_note_search_documents (note_id) {note_ids};
    END;
    """


TRIGGERS = {
    "note_insert": ("INSERT ON alcove_note", "SELECT NEW.id"),
    "note_update": (
        "UPDATE OF plain_text, book_id, trashed_at ON alcove_note",
        "SELECT NEW.id",
    ),
    "note_delete": ("DELETE ON alcove_note", "SELECT OLD.id"),
    "book_rename": (
        "UPDATE OF title ON alcove_book WHEN OLD.title <> NEW.title",
        "SELECT id FROM alcove_note WHERE book_id = NEW.id AND trashed_at IS NULL",
    ),
    "topic_rename": (
        "UPDATE OF label ON alcove_topic WHEN OLD.label <> NEW.label",
        "SELECT note_id FROM alcove_topicassignment WHERE topic_id = NEW.id",
    ),
    "assignment_insert": ("INSERT ON alcove_topicassignment", "SELECT NEW.note_id"),
    "assignment_delete": ("DELETE ON alcove_topicassignment", "SELECT OLD.note_id"),
}


class Migration(migrations.Migration):
    dependencies = [("alcove", "0009_note_trash")]

    operations = [
        migrations.RunSQL(
            sql=CREATE_SEARCH
            + REFRESH_NOTE
            + "".join(refresh_on(name, *args) for name, args in TRIGGERS.items()),
            reverse_sql="".join(
                f"DROP TRIGGER alcove_note_search_{name};\n" for name in TRIGGERS
            )
            + """
            DROP TRIGGER alcove_note_search_refresh;
            DROP VIEW alcove_note_search_documents;
            DROP TABLE alcove_note_search;
            """,
        ),
    ]

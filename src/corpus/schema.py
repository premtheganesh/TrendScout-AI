"""MongoDB indexes for the corpus. Idempotent; call it after any load.

Default index names are used deliberately: MongoDB refuses to create an
index that already exists under a different name, and some of these were
created by earlier scripts with the default names.
"""

from src.corpus.types import COLLECTION


def ensure_indexes(db) -> None:
    docs = db[COLLECTION]
    docs.create_index('doc_key', unique=True)
    docs.create_index('type')
    docs.create_index([('type', 1), ('event_at', -1)])
    docs.create_index('event_at')
    docs.create_index('first_seen_at')
    docs.create_index('content_hash')

    entities = db.canonical_entities
    entities.create_index('entity_text')
    entities.create_index('mentioned_in.doc_id')

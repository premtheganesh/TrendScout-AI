"""
Upsert documents by `doc_key`.

    new        - never seen: insert with first_seen_at = last_seen_at = now
    changed    - content_hash differs: overwrite fields, bump last_seen_at
    unchanged  - same hash: bump last_seen_at and the volatile metrics only

A document's `_id`, `first_seen_at`, `entities` and `embedding` survive a
`changed` upsert; the pipeline (Phase 4) compares `content_hash` against
what those were computed from and redoes only what is stale.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.corpus.dates import event_at_for
from src.corpus.identity import content_hash, doc_key
from src.corpus.types import COLLECTION

# Updated on every run even when the text has not changed: they are the
# time series the trends feature reads.
VOLATILE_FIELDS = ('stars', 'forks', 'watchers', 'open_issues', 'updated_at',
                   'pushed_at', 'team_size', 'status', 'is_hiring')

# Never overwritten by a re-ingest.
PROTECTED_FIELDS = ('_id', 'first_seen_at', 'entities', 'entities_extracted_at',
                    'embedding', 'embedding_generated_at')


def prepare(fields: Dict[str, Any], doc_type: str, source_tag: str) -> Dict[str, Any]:
    """Attach everything the runner owns to a normalised document."""
    doc = dict(fields)
    doc['type'] = doc_type
    doc['source'] = source_tag
    doc['doc_key'] = doc_key(doc, doc_type)
    doc['event_at'] = event_at_for(doc, doc_type)
    doc['content_hash'] = content_hash(doc, doc_type)
    return doc


class DocumentStore:
    def __init__(self, db):
        self.collection = db[COLLECTION]

    def upsert(self, doc: Dict[str, Any], now: Optional[datetime] = None) -> str:
        now = now or datetime.now(timezone.utc)
        existing = self.collection.find_one(
            {'doc_key': doc['doc_key']}, {'content_hash': 1})

        if existing is None:
            record = dict(doc)
            record['first_seen_at'] = now
            record['last_seen_at'] = now
            self.collection.insert_one(record)
            return 'new'

        if existing.get('content_hash') != doc['content_hash']:
            update = {k: v for k, v in doc.items() if k not in PROTECTED_FIELDS}
            update['last_seen_at'] = now
            self.collection.update_one({'_id': existing['_id']}, {'$set': update})
            return 'changed'

        update = {k: doc[k] for k in VOLATILE_FIELDS if k in doc}
        update['last_seen_at'] = now
        self.collection.update_one({'_id': existing['_id']}, {'$set': update})
        return 'unchanged'

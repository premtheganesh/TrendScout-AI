"""
Keep `content_hash` honest.

`content_hash` is sha1 of document_text(). Two things can make the stored
value stale: a source re-ingested different text (the store handles that),
or document_text() itself changed (this stage handles that). Each derived
artefact records the hash it was computed from — `entities_hash`,
`embedding_hash` — and the other stages redo only rows whose hash moved.

Rows that predate those markers but already carry entities/embeddings are
adopted: their marker is set to the hash the artefacts were built from,
and list-stored vectors are converted to float32 binary.
"""

from typing import Dict

from src.corpus.embeddings import to_binary
from src.corpus.identity import content_hash
from src.corpus.types import COLLECTION


def refresh_hashes(db) -> Dict[str, int]:
    stats = {'scanned': 0, 'adopted': 0, 'rehashed': 0, 'converted': 0}
    for doc in db[COLLECTION].find():
        stats['scanned'] += 1
        updates = {}
        old = doc.get('content_hash')

        # Pre-Phase-4 rows stored vectors as lists of doubles; same vector,
        # a third of the size.
        if isinstance(doc.get('embedding'), list):
            updates['embedding'] = to_binary(doc['embedding'])
            stats['converted'] += 1

        if old:
            if 'embedding' in doc and 'embedding_hash' not in doc:
                updates['embedding_hash'] = old
            if 'entities' in doc and 'entities_hash' not in doc:
                updates['entities_hash'] = old
            if updates:
                stats['adopted'] += 1

        new = content_hash(doc, doc.get('type'))
        if new != old:
            updates['content_hash'] = new
            stats['rehashed'] += 1

        if updates:
            db[COLLECTION].update_one({'_id': doc['_id']}, {'$set': updates})
    return stats

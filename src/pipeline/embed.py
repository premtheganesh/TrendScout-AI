"""E5 passage embeddings for documents whose text changed."""

import logging
from datetime import datetime, timezone

from src.corpus.embeddings import to_binary
from src.corpus.types import COLLECTION
from src.search.document_text import document_text

logger = logging.getLogger(__name__)

STALE = {'$or': [
    {'embedding_hash': {'$exists': False}},
    {'$expr': {'$ne': ['$embedding_hash', '$content_hash']}},
]}

CHUNK = 256


def embed_stale(db, generator, force: bool = False) -> int:
    query = {} if force else STALE
    docs, texts = [], []
    for doc in db[COLLECTION].find(query):
        text = document_text(doc, doc.get('type'))
        if not text.strip():
            continue
        docs.append(doc)
        texts.append(text)

    if not docs:
        return 0

    logger.info(f"Embedding {len(docs)} documents")
    now = datetime.now(timezone.utc).isoformat()
    for start in range(0, len(docs), CHUNK):
        chunk_docs = docs[start:start + CHUNK]
        vectors = generator.embed_passages_batch(texts[start:start + CHUNK],
                                                show_progress=False)
        for doc, vector in zip(chunk_docs, vectors):
            db[COLLECTION].update_one({'_id': doc['_id']}, {'$set': {
                'embedding': to_binary(vector),
                'embedding_hash': doc.get('content_hash'),
                'embedding_generated_at': now,
            }})
    return len(docs)

"""
Build the dense and lexical indexes from MongoDB.

Run after scraping new data or changing src/search/document_text.py:
    python scripts/build_indexes.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pickle
import logging
from datetime import datetime, timezone

import faiss
import numpy as np

from src.config import get_settings
from src.database.mongo_client import MongoDBClient
from src.embeddings.embedding_generator import EmbeddingGenerator
from src.search.bm25_index import BM25Index
from src.search.document_text import document_text

logging.basicConfig(level=logging.INFO, format='%(levelname)s  %(message)s')
logger = logging.getLogger(__name__)

COLLECTIONS = ('startups', 'articles', 'github_repos')


def build_dense_index(mongo, generator):
    print("\n" + "=" * 72)
    print("DENSE INDEX  (E5-base-v2 -> FAISS)")
    print("=" * 72)

    texts, doc_ids, collections, documents = [], [], [], []

    for collection in COLLECTIONS:
        docs = list(mongo.db[collection].find())
        print(f"  {collection:<15} {len(docs):>4} documents")
        for doc in docs:
            text = document_text(doc, collection)
            if not text.strip():
                continue
            texts.append(text)
            doc_ids.append(str(doc['_id']))
            collections.append(collection)
            documents.append(doc)

    if not texts:
        raise SystemExit(
            "No documents found in MongoDB. Run the scrapers before indexing."
        )

    print(f"\n  Embedding {len(texts)} documents with the 'passage: ' prefix...")
    embeddings = generator.embed_passages_batch(texts, show_progress=True)
    embeddings = np.asarray(embeddings, dtype='float32')
    print(f"  Embedding matrix: {embeddings.shape}")

    print("  Writing embeddings back to MongoDB...")
    now = datetime.now(timezone.utc).isoformat()
    for i, doc in enumerate(documents):
        mongo.db[collections[i]].update_one(
            {'_id': doc['_id']},
            {'$set': {
                'embedding': embeddings[i].tolist(),
                'embedding_generated_at': now,
            }}
        )

    # Inner product on normalized vectors is cosine similarity. The corpus
    # is small enough that an exact index beats an approximate one.
    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)

    settings = get_settings()
    os.makedirs(settings.index_dir, exist_ok=True)
    index_path = settings.faiss_index_path
    metadata_path = settings.faiss_metadata_path

    faiss.write_index(index, index_path)
    with open(metadata_path, 'wb') as f:
        pickle.dump({
            'ids': doc_ids,
            'metadata': [{'collection': c} for c in collections],
            'model': 'intfloat/e5-base-v2',
            'prefix': 'passage: ',
            'built_at': now,
        }, f)

    print(f"  Saved {index.ntotal} vectors ({index.d}-dim) -> {index_path}")
    return index.ntotal


def build_lexical_index(mongo):
    print("\n" + "=" * 72)
    print("LEXICAL INDEX  (Okapi BM25)")
    print("=" * 72)

    bm25 = BM25Index().build(mongo)
    path = bm25.save(get_settings().bm25_index_path)
    print(f"  Indexed {len(bm25)} documents -> {path}")
    return len(bm25)


def main():
    print("=" * 72)
    print("TRENDSCOUT AI — INDEX BUILD")
    print("=" * 72)

    mongo = MongoDBClient()
    print(f"  database: {mongo.db_name}\n  index dir: {get_settings().index_dir}")
    generator = EmbeddingGenerator()

    dense_count = build_dense_index(mongo, generator)
    lexical_count = build_lexical_index(mongo)

    print("\n" + "=" * 72)
    print(f"DONE — {dense_count} dense vectors, {lexical_count} BM25 documents")
    print("=" * 72)

    mongo.close()


if __name__ == "__main__":
    main()

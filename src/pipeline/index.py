"""
Rebuild FAISS and BM25 from what is stored.

Full rebuilds, deliberately: a flat inner-product index over a few
thousand 768-dim vectors builds in well under a second, and BM25 in a few
seconds. Nothing is re-embedded here — vectors come from MongoDB.
"""

import logging
import os
import pickle
from datetime import datetime, timezone
from typing import Dict

import numpy as np

from src.corpus.embeddings import from_stored
from src.corpus.types import COLLECTION
from src.search.bm25_index import BM25Index

logger = logging.getLogger(__name__)


def build_indexes(db, index_dir: str, model_name: str = 'intfloat/e5-base-v2') -> Dict:
    # Imported here, not at module level: on macOS, importing faiss before
    # spaCy's transformer model is loaded segfaults the process (OpenMP
    # runtime clash). The pipeline loads the extractor first; this keeps
    # faiss out of the picture until the index stage actually runs.
    import faiss

    ids, types, vectors = [], [], []
    for doc in db[COLLECTION].find({'embedding': {'$exists': True}},
                                   {'embedding': 1, 'type': 1}):
        vector = from_stored(doc.get('embedding'))
        if vector is None or not len(vector):
            continue
        ids.append(str(doc['_id']))
        types.append(doc.get('type', ''))
        vectors.append(vector)

    if not vectors:
        raise ValueError("No embeddings stored. Run the embed stage first.")

    matrix = np.vstack(vectors).astype('float32')
    index = faiss.IndexFlatIP(matrix.shape[1])
    index.add(matrix)

    os.makedirs(index_dir, exist_ok=True)
    built_at = datetime.now(timezone.utc).isoformat()
    faiss.write_index(index, os.path.join(index_dir, 'faiss_index.bin'))
    with open(os.path.join(index_dir, 'faiss_metadata.pkl'), 'wb') as f:
        pickle.dump({
            'ids': ids,
            'metadata': [{'type': t} for t in types],
            'model': model_name,
            'prefix': 'passage: ',
            'built_at': built_at,
        }, f)

    bm25 = BM25Index().build(db)
    bm25.save(os.path.join(index_dir, 'bm25_index.pkl'))

    return {'vectors': index.ntotal, 'dimension': index.d,
            'bm25_documents': len(bm25), 'built_at': built_at}

"""Okapi BM25 lexical index over the document corpus."""

import os
import pickle
import re
import logging
from typing import Dict, List, Optional

from rank_bm25 import BM25Okapi

from src.config import get_settings
from src.corpus.types import COLLECTION
from src.search.document_text import document_text

logger = logging.getLogger(__name__)

# Deliberately short: BM25's IDF already discounts ubiquitous terms, and
# aggressive stopwording breaks phrases like "AI for healthcare".
STOPWORDS = {
    'a', 'an', 'the', 'and', 'or', 'but', 'if', 'then', 'else', 'of', 'at',
    'by', 'for', 'with', 'about', 'into', 'to', 'from', 'in', 'on', 'is',
    'are', 'was', 'were', 'be', 'been', 'being', 'it', 'its', 'this', 'that',
    'these', 'those', 'as', 'i', 'me', 'my', 'we', 'our', 'you', 'your',
}

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\+\#\.\-]*")


def default_index_path() -> str:
    """Resolved at call time so INDEX_DIR can change per process."""
    return get_settings().bm25_index_path


def tokenize(text: str) -> List[str]:
    """Keeps internal punctuation so c++, gpt-4 and node.js stay one token."""
    if not text:
        return []
    tokens = _TOKEN_RE.findall(text.lower())
    return [t.strip('.-') for t in tokens
            if t not in STOPWORDS and len(t.strip('.-')) > 1]


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.bm25: Optional[BM25Okapi] = None
        self.doc_ids: List[str] = []
        self.types: List[str] = []
        self.titles: List[str] = []

    def build(self, mongo) -> "BM25Index":
        from src.search.document_text import document_title

        corpus_tokens: List[List[str]] = []
        self.doc_ids, self.types, self.titles = [], [], []

        for doc in mongo.db[COLLECTION].find():
            doc_type = doc.get('type', '')
            text = document_text(doc, doc_type)
            if not text.strip():
                continue
            corpus_tokens.append(tokenize(text))
            self.doc_ids.append(str(doc['_id']))
            self.types.append(doc_type)
            self.titles.append(document_title(doc, doc_type))

        if not corpus_tokens:
            raise ValueError(
                "No documents found to index. Is MongoDB populated? "
                "Run the ingestion first."
            )

        self.bm25 = BM25Okapi(corpus_tokens, k1=self.k1, b=self.b)

        avg_len = sum(len(t) for t in corpus_tokens) / len(corpus_tokens)
        logger.info(
            f"Built BM25 index: {len(corpus_tokens)} docs, "
            f"avg length {avg_len:.1f} tokens, k1={self.k1}, b={self.b}"
        )
        return self

    def save(self, path: str = None) -> str:
        path = os.path.abspath(path or default_index_path())
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            pickle.dump({
                'bm25': self.bm25,
                'doc_ids': self.doc_ids,
                'types': self.types,
                'titles': self.titles,
                'k1': self.k1,
                'b': self.b,
            }, f)
        logger.info(f"Saved BM25 index to {path}")
        return path

    @classmethod
    def load(cls, path: str = None) -> "BM25Index":
        path = os.path.abspath(path or default_index_path())
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"BM25 index not found at {path}. "
                "Run: python scripts/build_indexes.py"
            )
        with open(path, 'rb') as f:
            state = pickle.load(f)

        if 'types' not in state:
            raise ValueError(
                f"BM25 index at {path} predates the unified documents "
                "collection. Run: python scripts/build_indexes.py"
            )

        index = cls(k1=state.get('k1', 1.5), b=state.get('b', 0.75))
        index.bm25 = state['bm25']
        index.doc_ids = state['doc_ids']
        index.types = state['types']
        index.titles = state['titles']
        logger.info(f"Loaded BM25 index with {len(index.doc_ids)} documents")
        return index

    def search(
        self,
        query: str,
        doc_type: str = None,
        top_k: int = 20,
        allowed_ids: set = None
    ) -> List[Dict]:
        """
        Score the whole corpus and return the top_k hits.

        Args:
            query: the search query
            doc_type: restrict to one document type
            top_k: results to return
            allowed_ids: if given, only these doc_ids are eligible

        `allowed_ids` exists so that structured filters are applied BEFORE
        truncation, not after. Ranking the whole corpus, cutting to top_k
        and only then discarding documents that fail the filter is a recall
        bug: for a query like "AI startup funding" restricted to San
        Francisco, the global top-40 is dominated by non-SF startups, so
        almost nothing survives the filter and the genuinely relevant SF
        documents are never seen. BM25 already scores every document, so
        filtering inside this loop costs nothing and loses nothing.

        Returns dicts of {doc_id, type, score, title} — deliberately NOT
        the full document. Hydrating from MongoDB is the caller's job, so a
        fused ranking only fetches the documents it actually keeps.
        """
        if self.bm25 is None:
            raise RuntimeError("BM25 index is not built or loaded.")

        tokens = tokenize(query)
        if not tokens:
            return []

        scores = self.bm25.get_scores(tokens)

        ranked = []
        for i, score in enumerate(scores):
            if score <= 0:
                continue
            if doc_type and self.types[i] != doc_type:
                continue
            if allowed_ids is not None and self.doc_ids[i] not in allowed_ids:
                continue
            ranked.append({
                'doc_id': self.doc_ids[i],
                'type': self.types[i],
                'score': float(score),
                'title': self.titles[i],
            })

        ranked.sort(key=lambda r: r['score'], reverse=True)
        return ranked[:top_k]

    def __len__(self) -> int:
        return len(self.doc_ids)

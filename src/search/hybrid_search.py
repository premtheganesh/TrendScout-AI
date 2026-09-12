"""
Hybrid search: BM25 + E5/FAISS + graph expansion, fused with Reciprocal
Rank Fusion.

RRF fuses by rank rather than score because BM25 scores are unbounded,
cosine similarities live in [-1, 1] and graph scores are log weights.
k=60 follows Cormack et al. (2009).
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import pickle
import logging
from typing import List, Dict, Optional

import faiss
import numpy as np
from bson import ObjectId

from src.config import get_settings
from src.corpus.types import COLLECTION
from src.database.mongo_client import MongoDBClient
from src.embeddings.embedding_generator import EmbeddingGenerator
from src.search.bm25_index import BM25Index
from src.search.graph_expansion import GraphExpander
from src.search.document_text import document_title, document_url

logger = logging.getLogger(__name__)

# Tuned with scripts/evaluate_retrieval.py --sweep. Weighting BM25 equally
# with dense scores 0.863 nDCG@10 against 0.881 at 0.5, because lexical
# noise drags semantic queries down; dropping BM25 entirely costs the
# lexical queries it exists for. Anything in 0.25-0.75 is within noise.
DEFAULT_WEIGHTS = {
    'keyword': 0.5,
    'semantic': 1.0,
    'graph': 0.5,
}

RRF_K = 60


class HybridSearchEngine:

    def __init__(
        self,
        neo4j_client=None,
        weights: Dict[str, float] = None,
        index_dir: str = None,
    ):
        logger.info("Initializing Hybrid Search Engine...")

        self.mongo = MongoDBClient()
        self.generator = EmbeddingGenerator()
        self.weights = dict(DEFAULT_WEIGHTS)
        if weights:
            self.weights.update(weights)

        settings = get_settings()
        self.index_dir = os.path.abspath(index_dir or settings.index_dir)
        index_path = os.path.join(self.index_dir, 'faiss_index.bin')
        metadata_path = os.path.join(self.index_dir, 'faiss_metadata.pkl')

        if not os.path.exists(index_path):
            raise FileNotFoundError(
                f"FAISS index not found at {index_path}. "
                "Run: python scripts/build_indexes.py"
            )

        self.faiss_index = faiss.read_index(index_path)
        with open(metadata_path, 'rb') as f:
            self.faiss_metadata = pickle.load(f)

        if self.faiss_index.d != self.generator.dimension:
            raise ValueError(
                f"Index/model dimension mismatch: FAISS index is "
                f"{self.faiss_index.d}-dim but the embedding model produces "
                f"{self.generator.dimension}-dim vectors. Rebuild the index."
            )

        if self.faiss_metadata['metadata'] and 'type' not in self.faiss_metadata['metadata'][0]:
            raise ValueError(
                f"FAISS metadata at {metadata_path} predates the unified "
                "documents collection. Run: python scripts/build_indexes.py"
            )

        self.bm25 = BM25Index.load(os.path.join(self.index_dir, 'bm25_index.pkl'))
        self.graph = GraphExpander(self.mongo, neo4j_client=neo4j_client)

        logger.info(
            f"Ready - {self.faiss_index.ntotal} dense vectors, "
            f"{len(self.bm25)} BM25 documents"
        )

    @property
    def documents(self):
        return self.mongo.db[COLLECTION]

    def _clean_document(self, doc: Optional[Dict]) -> Optional[Dict]:
        if doc is None:
            return None
        cleaned = dict(doc)
        if '_id' in cleaned:
            cleaned['_id'] = str(cleaned['_id'])
        cleaned.pop('embedding', None)
        return cleaned

    def _fetch_documents(self, doc_ids: List[str]) -> Dict[str, Dict]:
        """One query for the whole fused list rather than one per document."""
        object_ids = []
        for doc_id in doc_ids:
            try:
                object_ids.append(ObjectId(doc_id))
            except Exception:
                continue
        if not object_ids:
            return {}
        return {
            str(doc['_id']): self._clean_document(doc)
            for doc in self.documents.find({'_id': {'$in': object_ids}})
        }

    def keyword_search(
        self,
        query: str,
        doc_type: str = None,
        filters: Dict = None,
        top_k: int = 20
    ) -> List[Dict]:
        """
        BM25 over the corpus. Field filters resolve in MongoDB but are handed
        to BM25 so they apply before truncation rather than after.
        """
        allowed = None
        if filters:
            allowed = self._ids_matching_filters(filters, doc_type)
            if not allowed:
                return []

        return self.bm25.search(
            query,
            doc_type=doc_type,
            top_k=top_k,
            allowed_ids=allowed,
        )

    def _ids_matching_filters(self, filters: Dict, doc_type: str = None) -> set:
        query = dict(filters)
        if doc_type:
            query['type'] = doc_type
        return {str(doc['_id']) for doc in self.documents.find(query, {'_id': 1})}

    def semantic_search(
        self,
        query: str,
        doc_type: str = None,
        top_k: int = 20,
        filters: Dict = None
    ) -> List[Dict]:
        """
        Dense retrieval through FAISS. FAISS cannot filter on fields, so a
        filtered query scans the whole index and drops non-matching hits.
        """
        query_embedding = self.generator.embed_query(query).reshape(1, -1).astype('float32')

        allowed_ids = None
        if filters:
            allowed_ids = self._ids_matching_filters(filters, doc_type)
            if not allowed_ids:
                return []

        if doc_type or filters:
            search_k = self.faiss_index.ntotal
        else:
            search_k = min(top_k, self.faiss_index.ntotal)
        similarities, indices = self.faiss_index.search(query_embedding, search_k)

        results = []
        for idx, score in zip(indices[0], similarities[0]):
            if idx < 0:
                continue
            doc_id = self.faiss_metadata['ids'][idx]
            meta = self.faiss_metadata['metadata'][idx]
            hit_type = meta.get('type', '')

            if doc_type and hit_type != doc_type:
                continue
            if allowed_ids is not None and doc_id not in allowed_ids:
                continue

            results.append({
                'doc_id': doc_id,
                'type': hit_type,
                'score': float(score),
            })
            if len(results) >= top_k:
                break

        return results

    def reciprocal_rank_fusion(
        self,
        channels: Dict[str, List[Dict]],
        k: int = RRF_K
    ) -> List[Dict]:
        """Merge ranked lists, keeping per-channel ranks for explainability."""
        combined: Dict[str, Dict] = {}

        for channel_name, results in channels.items():
            weight = self.weights.get(channel_name, 1.0)
            for rank, result in enumerate(results, start=1):
                doc_id = result['doc_id']
                entry = combined.setdefault(doc_id, {
                    'doc_id': doc_id,
                    'type': result.get('type', ''),
                    'rrf_score': 0.0,
                    'ranks': {},
                    'channel_scores': {},
                    'shared_entities': [],
                })
                entry['rrf_score'] += weight / (k + rank)
                entry['ranks'][channel_name] = rank
                entry['channel_scores'][channel_name] = result.get('score', 0.0)
                if result.get('shared_entities'):
                    entry['shared_entities'] = result['shared_entities']
                if not entry['type']:
                    entry['type'] = result.get('type', '')

        fused = list(combined.values())
        fused.sort(key=lambda r: r['rrf_score'], reverse=True)
        return fused

    def search(
        self,
        query: str,
        doc_type: str = None,
        filters: Dict = None,
        top_k: int = 10,
        use_keyword: bool = True,
        use_semantic: bool = True,
        use_graph: bool = True,
        candidates_per_channel: int = 20,
        graph_expansion_only: bool = True,
    ) -> List[Dict]:
        """
        Run the enabled channels and fuse them.

        graph_expansion_only restricts the graph channel to documents the
        text channels missed. Letting it also re-score documents they already
        found costs 9.9% nDCG: a document ranked weakly by both text channels
        picks up a third contribution and overtakes one ranked strongly by a
        single channel.
        """
        if not query or not query.strip():
            return []

        logger.info(f"Searching: '{query}' (type={doc_type})")
        channels: Dict[str, List[Dict]] = {}

        if use_keyword:
            channels['keyword'] = self.keyword_search(
                query, doc_type, filters, top_k=candidates_per_channel)

        if use_semantic:
            channels['semantic'] = self.semantic_search(
                query, doc_type, top_k=candidates_per_channel, filters=filters)

        if use_graph:
            seeds: List[str] = []
            for name in ('keyword', 'semantic'):
                seeds.extend(r['doc_id'] for r in channels.get(name, [])[:5])
            seeds = list(dict.fromkeys(seeds))

            graph_hits = self.graph.expand(
                seeds, doc_type=doc_type, top_k=candidates_per_channel)

            if filters and graph_hits:
                allowed = self._ids_matching_filters(filters, doc_type)
                graph_hits = [g for g in graph_hits if g['doc_id'] in allowed]

            if graph_expansion_only:
                already_found = {
                    r['doc_id']
                    for name in ('keyword', 'semantic')
                    for r in channels.get(name, [])
                }
                graph_hits = [g for g in graph_hits
                              if g['doc_id'] not in already_found]

            channels['graph'] = graph_hits

        if not channels:
            return []

        fused = self.reciprocal_rank_fusion(channels)[:top_k]

        documents = self._fetch_documents([r['doc_id'] for r in fused])

        enriched = []
        for result in fused:
            doc = documents.get(result['doc_id'])
            if doc is None:
                continue
            if not result['type']:
                result['type'] = doc.get('type', '')
            result['document'] = doc
            result['title'] = document_title(doc, result['type'])
            result['url'] = document_url(doc, result['type'])
            enriched.append(result)

        return enriched

    def format_result(self, result: Dict) -> str:
        doc = result.get('document', {})
        doc_type = result.get('type', '')

        lines = [
            f"Type:       {doc_type.upper()}",
            f"RRF Score:  {result.get('rrf_score', 0):.5f}",
            f"Title:      {result.get('title', 'N/A')}",
        ]

        ranks = result.get('ranks', {})
        if ranks:
            lines.append("Ranks:      " + ", ".join(
                f"{name}={rank}" for name, rank in sorted(ranks.items())))

        if result.get('shared_entities'):
            lines.append("Via graph:  " + ", ".join(result['shared_entities'][:5]))

        if doc_type == 'startup':
            lines.append(f"Location:   {doc.get('location', 'N/A')}")
            lines.append(f"Funding:    {doc.get('funding', 'N/A')}")
        elif doc_type == 'repo':
            lines.append(f"Stars:      {doc.get('stars', 'N/A')}")

        description = str(doc.get('description', ''))[:140]
        if description:
            lines.append(f"About:      {description}...")

        return '\n'.join(lines)

    def close(self):
        self.mongo.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')

    engine = HybridSearchEngine()

    demos = [
        {'query': 'AI music generation startup', 'top_k': 3},
        {'query': 'open source framework for building LLM agents',
         'doc_type': 'repo', 'top_k': 3},
        {'query': 'startups that raised a Series A',
         'doc_type': 'startup', 'top_k': 3},
    ]

    for i, demo in enumerate(demos, 1):
        print("\n" + "=" * 72)
        print(f"QUERY {i}: {demo['query']!r}")
        print("=" * 72)
        for j, result in enumerate(engine.search(**demo), 1):
            print(f"\n{j}. " + "-" * 66)
            print(engine.format_result(result))

    engine.close()

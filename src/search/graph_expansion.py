"""Retrieval channel that walks shared-entity edges from the top text hits."""

import math
import logging
from collections import defaultdict
from typing import Dict, List, Optional

from src.corpus.types import COLLECTION, NEO4J_LABEL_TO_TYPE, normalize_type

logger = logging.getLogger(__name__)


class GraphExpander:
    """
    Finds documents connected to the seeds through shared entities.

    Reads canonical_entities from MongoDB so it works with Neo4j offline;
    expand_via_neo4j runs the same scoring as Cypher when Neo4j is up.
    """

    def __init__(self, mongo, neo4j_client=None):
        self.mongo = mongo
        self.neo4j = neo4j_client
        self._total_docs: Optional[int] = None

    def _corpus_size(self) -> int:
        if self._total_docs is None:
            self._total_docs = self.mongo.db[COLLECTION].count_documents({})
        return max(self._total_docs, 1)

    def expand(
        self,
        seed_doc_ids: List[str],
        doc_type: str = None,
        top_k: int = 20,
        max_entities_per_seed: int = 25,
    ) -> List[Dict]:
        """
        Score neighbours by the rarity of the entities they share with the
        seeds. max_entities_per_seed drops hub entities such as "AI", which
        appear almost everywhere and connect everything to everything.
        """
        if not seed_doc_ids:
            return []

        seed_set = set(seed_doc_ids)

        entities = list(self.mongo.db.canonical_entities.find({
            'mentioned_in.doc_id': {'$in': list(seed_set)}
        }))

        if not entities:
            return []

        n_docs = self._corpus_size()
        neighbour_scores: Dict[str, float] = defaultdict(float)
        neighbour_type: Dict[str, str] = {}
        shared: Dict[str, List[str]] = defaultdict(list)

        for entity in entities:
            mentions = entity.get('mentioned_in') or []
            if isinstance(mentions, str):
                continue

            linked = {}
            for m in mentions:
                if isinstance(m, dict) and m.get('doc_id'):
                    # `collection` is the pre-migration key; tolerate it.
                    linked[m['doc_id']] = (m.get('type')
                                           or normalize_type(m.get('collection'))
                                           or '')

            degree = len(linked)
            if degree <= 1 or degree > max_entities_per_seed:
                continue

            weight = math.log(1 + n_docs / degree)

            for doc_id, linked_type in linked.items():
                if doc_id in seed_set:
                    continue
                if doc_type and linked_type != doc_type:
                    continue
                neighbour_scores[doc_id] += weight
                neighbour_type[doc_id] = linked_type
                shared[doc_id].append(entity.get('entity_text', ''))

        results = [
            {
                'doc_id': doc_id,
                'type': neighbour_type.get(doc_id, ''),
                'score': score,
                'shared_entities': sorted(set(shared[doc_id]))[:8],
            }
            for doc_id, score in neighbour_scores.items()
        ]
        results.sort(key=lambda r: r['score'], reverse=True)

        logger.info(
            f"Graph expansion: {len(seed_set)} seeds -> {len(entities)} entities "
            f"-> {len(results)} neighbours"
        )
        return results[:top_k]

    def expand_via_neo4j(
        self,
        seed_doc_ids: List[str],
        doc_type: str = None,
        top_k: int = 20,
        max_entities_per_seed: int = 25,
    ) -> List[Dict]:
        """Same scoring as expand(), executed in Cypher. Falls back to
        MongoDB when Neo4j is unreachable."""
        if not self.neo4j or not getattr(self.neo4j, 'available', False):
            return self.expand(seed_doc_ids, doc_type=doc_type, top_k=top_k,
                               max_entities_per_seed=max_entities_per_seed)

        if not seed_doc_ids:
            return []

        cypher = """
        MATCH (seed)-[:MENTIONS]->(e:Entity)
        WHERE seed.doc_id IN $seed_ids
        WITH DISTINCT e

        MATCH (e)<-[:MENTIONS]-(d)
        WHERE d.doc_id IS NOT NULL
        WITH e, count(DISTINCT d) AS degree

        WHERE degree > 1 AND degree <= $max_degree
        WITH e, log(1 + toFloat($n_docs) / degree) AS weight

        MATCH (e)<-[:MENTIONS]-(neighbour)
        WHERE neighbour.doc_id IS NOT NULL
          AND NOT neighbour.doc_id IN $seed_ids
        WITH neighbour,
             sum(weight) AS score,
             collect(DISTINCT e.entity_text) AS shared_entities
        RETURN neighbour.doc_id     AS doc_id,
               labels(neighbour)[0] AS node_label,
               score,
               shared_entities
        ORDER BY score DESC
        LIMIT $top_k
        """
        try:
            records = self.neo4j.run_query(cypher, {
                'seed_ids': seed_doc_ids,
                'max_degree': max_entities_per_seed,
                'n_docs': self._corpus_size(),
                'top_k': top_k * 3 if doc_type else top_k,
            })
        except Exception as e:
            logger.warning(f"Neo4j expansion failed, using MongoDB path: {e}")
            return self.expand(seed_doc_ids, doc_type=doc_type, top_k=top_k,
                               max_entities_per_seed=max_entities_per_seed)

        results = []
        for r in records:
            linked_type = NEO4J_LABEL_TO_TYPE.get(r['node_label'], '')
            if doc_type and linked_type != doc_type:
                continue
            results.append({
                'doc_id': r['doc_id'],
                'type': linked_type,
                'score': float(r['score']),
                'shared_entities': sorted(set(r['shared_entities'] or []))[:8],
            })

        return results[:top_k]

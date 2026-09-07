"""Retrieval channel that walks shared-entity edges from the top text hits."""

import math
import logging
from collections import defaultdict
from typing import Dict, List, Optional

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
            self._total_docs = sum(
                self.mongo.db[c].count_documents({})
                for c in ('startups', 'articles', 'github_repos')
            )
        return max(self._total_docs, 1)

    def expand(
        self,
        seed_doc_ids: List[str],
        collection: str = None,
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
        neighbour_collection: Dict[str, str] = {}
        shared: Dict[str, List[str]] = defaultdict(list)

        for entity in entities:
            mentions = entity.get('mentioned_in') or []
            if isinstance(mentions, str):
                continue

            linked = {}
            for m in mentions:
                if isinstance(m, dict) and m.get('doc_id'):
                    linked[m['doc_id']] = m.get('collection', '')

            degree = len(linked)
            if degree <= 1 or degree > max_entities_per_seed:
                continue

            weight = math.log(1 + n_docs / degree)

            for doc_id, doc_collection in linked.items():
                if doc_id in seed_set:
                    continue
                if collection and doc_collection != collection:
                    continue
                neighbour_scores[doc_id] += weight
                neighbour_collection[doc_id] = doc_collection
                shared[doc_id].append(entity.get('entity_text', ''))

        results = [
            {
                'doc_id': doc_id,
                'collection': neighbour_collection.get(doc_id, ''),
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
        collection: str = None,
        top_k: int = 20,
        max_entities_per_seed: int = 25,
    ) -> List[Dict]:
        """Same scoring as expand(), executed in Cypher. Falls back to
        MongoDB when Neo4j is unreachable."""
        if not self.neo4j or not getattr(self.neo4j, 'available', False):
            return self.expand(seed_doc_ids, collection=collection, top_k=top_k,
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
        label_to_collection = {
            'Startup': 'startups',
            'Article': 'articles',
            'GitHubRepo': 'github_repos',
        }
        try:
            records = self.neo4j.run_query(cypher, {
                'seed_ids': seed_doc_ids,
                'max_degree': max_entities_per_seed,
                'n_docs': self._corpus_size(),
                'top_k': top_k * 3 if collection else top_k,
            })
        except Exception as e:
            logger.warning(f"Neo4j expansion failed, using MongoDB path: {e}")
            return self.expand(seed_doc_ids, collection=collection, top_k=top_k,
                               max_entities_per_seed=max_entities_per_seed)

        results = []
        for r in records:
            doc_collection = label_to_collection.get(r['node_label'], '')
            if collection and doc_collection != collection:
                continue
            results.append({
                'doc_id': r['doc_id'],
                'collection': doc_collection,
                'score': float(r['score']),
                'shared_entities': sorted(set(r['shared_entities'] or []))[:8],
            })

        return results[:top_k]

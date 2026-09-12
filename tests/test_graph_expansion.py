"""Shared-entity graph retrieval channel."""

import pytest

from src.search.graph_expansion import GraphExpander


class FakeEntities:
    def __init__(self, entities):
        self._entities = entities

    def find(self, query=None, *args, **kwargs):
        """Supports the one query shape the expander uses."""
        if not query:
            return iter(self._entities)
        wanted = set(query['mentioned_in.doc_id']['$in'])

        def matches(e):
            mentions = e.get('mentioned_in')
            # A legacy repr-string field cannot match a dotted subfield
            # query in real MongoDB either, so mirror that here.
            if not isinstance(mentions, list):
                return False
            return any(isinstance(m, dict) and m.get('doc_id') in wanted
                       for m in mentions)

        return iter([e for e in self._entities if matches(e)])


class FakeCounted:
    def __init__(self, n):
        self._n = n

    def count_documents(self, *args, **kwargs):
        return self._n


class FakeDatabase:
    """pymongo exposes collections by both attribute and item access."""
    def __init__(self, collections):
        self._collections = collections

    def __getitem__(self, name):
        return self._collections[name]

    def __getattr__(self, name):
        try:
            return self._collections[name]
        except KeyError as e:
            raise AttributeError(name) from e


class FakeMongo:
    def __init__(self, entities, corpus_size=100):
        self.db = FakeDatabase({
            'canonical_entities': FakeEntities(entities),
            'documents': FakeCounted(corpus_size),
        })


def entity(text, docs, etype='ORG'):
    return {
        'entity_text': text,
        'entity_type': etype,
        'mentioned_in': [{'doc_id': d, 'type': t} for d, t in docs],
    }


class TestGraphExpander:
    def test_finds_documents_sharing_an_entity(self):
        mongo = FakeMongo([
            entity('Suno', [('seed', 'startup'), ('article1', 'article')]),
        ])
        results = GraphExpander(mongo).expand(['seed'])
        assert [r['doc_id'] for r in results] == ['article1']
        assert results[0]['shared_entities'] == ['Suno']

    def test_seed_documents_are_never_returned(self):
        mongo = FakeMongo([
            entity('Suno', [('seed', 'startup'), ('seed2', 'startup')]),
        ])
        results = GraphExpander(mongo).expand(['seed', 'seed2'])
        assert results == []

    def test_rare_entities_outweigh_common_ones(self):
        """Co-mentioning a rare entity is stronger evidence than a common one."""
        common = entity('Google', [('seed', 'startup')] +
                        [(f'd{i}', 'article') for i in range(20)])
        rare = entity('Suno', [('seed', 'startup'), ('rare_hit', 'article')])
        results = GraphExpander(FakeMongo([common, rare])).expand(['seed'])
        assert results[0]['doc_id'] == 'rare_hit'

    def test_hub_entities_are_excluded(self):
        hub = entity('AI', [('seed', 'startup')] +
                     [(f'd{i}', 'article') for i in range(200)])
        results = GraphExpander(FakeMongo([hub])).expand(
            ['seed'], max_entities_per_seed=25)
        assert results == []

    def test_degree_one_entities_contribute_nothing(self):
        solo = entity('Nobody', [('seed', 'startup')])
        assert GraphExpander(FakeMongo([solo])).expand(['seed']) == []

    def test_more_shared_entities_ranks_higher(self):
        mongo = FakeMongo([
            entity('A', [('seed', 'startup'), ('two', 'article')]),
            entity('B', [('seed', 'startup'), ('two', 'article')]),
            entity('C', [('seed', 'startup'), ('one', 'article')]),
        ])
        results = GraphExpander(mongo).expand(['seed'])
        assert results[0]['doc_id'] == 'two'
        assert len(results[0]['shared_entities']) == 2

    def test_type_filter(self):
        mongo = FakeMongo([
            entity('X', [('seed', 'startup'), ('a1', 'article'),
                         ('r1', 'repo')]),
        ])
        results = GraphExpander(mongo).expand(['seed'], doc_type='article')
        assert [r['doc_id'] for r in results] == ['a1']

    def test_legacy_collection_key_on_links_is_understood(self):
        """Entity links written before the migration used `collection`."""
        legacy = {
            'entity_text': 'Suno', 'entity_type': 'ORG',
            'mentioned_in': [{'doc_id': 'seed', 'collection': 'startups'},
                             {'doc_id': 'hit', 'collection': 'articles'}],
        }
        results = GraphExpander(FakeMongo([legacy])).expand(['seed'], doc_type='article')
        assert [r['doc_id'] for r in results] == ['hit']
        assert results[0]['type'] == 'article' 

    def test_no_seeds_returns_nothing(self):
        assert GraphExpander(FakeMongo([])).expand([]) == []

    def test_no_matching_entities_returns_nothing(self):
        assert GraphExpander(FakeMongo([])).expand(['unknown']) == []

    def test_top_k_is_respected(self):
        ents = [entity(f'E{i}', [('seed', 'startup'), (f'n{i}', 'article')])
                for i in range(10)]
        assert len(GraphExpander(FakeMongo(ents)).expand(['seed'], top_k=3)) == 3

    def test_duplicate_mentions_count_once(self):
        dup = {
            'entity_text': 'Suno',
            'entity_type': 'ORG',
            'mentioned_in': [{'doc_id': 'seed', 'type': 'startup'}] * 3
                            + [{'doc_id': 'hit', 'type': 'article'}] * 4,
        }
        results = GraphExpander(FakeMongo([dup])).expand(['seed'])
        assert len(results) == 1
        assert results[0]['shared_entities'] == ['Suno']

    def test_legacy_string_mentions_are_skipped_not_crashed(self):
        """Older rows stored `mentioned_in` as a repr string; skip, do not raise."""
        good = entity('Suno', [('seed', 'startup'), ('hit', 'article')])
        broken = {'entity_text': 'X', 'entity_type': 'ORG',
                  'mentioned_in': "[{'doc_id': 'seed'}]"}

        expander = GraphExpander(FakeMongo([good, broken]))
        expander.mongo.db.canonical_entities._entities = [good, broken]
        results = expander.expand(['seed'])
        assert [r['doc_id'] for r in results] == ['hit']

    def test_neo4j_path_falls_back_when_unavailable(self):
        mongo = FakeMongo([
            entity('Suno', [('seed', 'startup'), ('hit', 'article')]),
        ])
        expander = GraphExpander(mongo, neo4j_client=None)
        results = expander.expand_via_neo4j(['seed'])
        assert [r['doc_id'] for r in results] == ['hit']

    def test_neo4j_error_falls_back_to_mongodb(self):
        class BrokenNeo4j:
            available = True
            def run_query(self, *a, **k):
                raise RuntimeError("connection lost")

        mongo = FakeMongo([
            entity('Suno', [('seed', 'startup'), ('hit', 'article')]),
        ])
        expander = GraphExpander(mongo, neo4j_client=BrokenNeo4j())
        results = expander.expand_via_neo4j(['seed'])
        assert [r['doc_id'] for r in results] == ['hit']

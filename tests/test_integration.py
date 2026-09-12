"""Integration tests against the real stack. See conftest.py for skipping."""

import pytest

from conftest import needs_mongo, needs_indexes
from src.corpus.types import COLLECTION, TYPE_NAMES


@needs_mongo
@needs_indexes
class TestRealSearch:
    def test_engine_loads_both_indexes(self, engine):
        assert engine.faiss_index.ntotal > 0
        assert len(engine.bm25) > 0

    def test_index_sizes_agree(self, engine):
        assert engine.faiss_index.ntotal == len(engine.bm25)

    def test_faiss_dimension_matches_the_model(self, engine):
        assert engine.faiss_index.d == engine.generator.dimension == 768

    def test_known_query_finds_the_obvious_document(self, engine):
        results = engine.search('AI music generation startup', top_k=5)
        assert results
        assert any('suno' in r['title'].lower() for r in results)

    def test_results_carry_hydrated_documents(self, engine):
        results = engine.search('AI startup', top_k=3)
        for r in results:
            assert r['document']
            assert r['title']
            assert isinstance(r['document']['_id'], str)  # JSON-safe

    def test_embeddings_are_stripped_from_responses(self, engine):
        for r in engine.search('AI', top_k=3):
            assert 'embedding' not in r['document']

    def test_type_filter_is_honoured(self, engine):
        results = engine.search('framework', doc_type='repo', top_k=5)
        assert results
        assert all(r['type'] == 'repo' for r in results)

    def test_structured_filter_does_not_leak(self, engine):
        """Dense hits used to bypass the location filter entirely."""
        results = engine.search(
            'AI startup', doc_type='startup',
            filters={'location': {'$regex': 'Boston', '$options': 'i'}},
            top_k=10)
        assert results
        for r in results:
            assert 'boston' in str(r['document'].get('location', '')).lower()

    def test_channels_can_be_disabled_independently(self, engine):
        keyword_only = engine.search('Suno', use_semantic=False,
                                     use_graph=False, top_k=5)
        semantic_only = engine.search('Suno', use_keyword=False,
                                      use_graph=False, top_k=5)
        assert keyword_only and semantic_only
        assert all(set(r['ranks']) == {'keyword'} for r in keyword_only)
        assert all(set(r['ranks']) == {'semantic'} for r in semantic_only)

    def test_all_channels_disabled_returns_nothing(self, engine):
        assert engine.search('Suno', use_keyword=False, use_semantic=False,
                             use_graph=False) == []

    def test_empty_query_returns_nothing(self, engine):
        assert engine.search('') == []
        assert engine.search('   ') == []

    def test_rrf_scores_are_descending(self, engine):
        results = engine.search('AI startup funding', top_k=10)
        scores = [r['rrf_score'] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_top_k_is_respected(self, engine):
        assert len(engine.search('AI', top_k=3)) <= 3

    def test_nonsense_query_does_not_crash(self, engine):
        engine.search('zzzzqqqq nonexistent gibberish term', top_k=5)


@needs_mongo
class TestCorpusIntegrity:
    def test_every_type_is_populated(self, mongo):
        for name in TYPE_NAMES:
            assert mongo.db[COLLECTION].count_documents({'type': name}) > 0, f'no {name} documents'

    def test_every_document_has_a_registered_type(self, mongo):
        stray = mongo.db[COLLECTION].count_documents({'type': {'$nin': list(TYPE_NAMES)}})
        assert stray == 0

    def test_doc_keys_are_unique_and_indexed(self, mongo):
        unique_keys = [dict(i['key']) for i in mongo.db[COLLECTION].list_indexes()
                       if i.get('unique')]
        assert {'doc_key': 1} in unique_keys
        assert mongo.db[COLLECTION].count_documents({'doc_key': {'$exists': False}}) == 0

    def test_every_document_has_an_embedding(self, mongo):
        missing = mongo.db[COLLECTION].count_documents({'embedding': {'$exists': False}})
        assert missing == 0, f'{missing} documents lack embeddings'

    def test_embeddings_are_the_right_width(self, mongo):
        doc = mongo.db[COLLECTION].find_one({'embedding': {'$exists': True}})
        assert len(doc['embedding']) == 768

    def test_entities_were_extracted_for_every_document(self, mongo):
        """Every document was processed; a few with one-word descriptions
        legitimately yield no entities, so the bar is 95%, not 100%."""
        total = mongo.db[COLLECTION].count_documents({})
        processed = mongo.db[COLLECTION].count_documents({'entities': {'$exists': True}})
        with_entities = mongo.db[COLLECTION].count_documents(
            {'entities': {'$exists': True, '$ne': []}})
        assert processed == total, f'{total - processed} documents never went through NER'
        assert with_entities >= 0.95 * total, (
            f'only {with_entities}/{total} documents have entities')

    def test_entity_links_carry_a_type(self, mongo):
        legacy = mongo.db.canonical_entities.count_documents(
            {'mentioned_in.collection': {'$exists': True}})
        assert legacy == 0, f'{legacy} entities still link by legacy collection name'

    def test_canonical_entities_exist_and_link_documents(self, mongo):
        total = mongo.db.canonical_entities.count_documents({})
        assert total > 0
        connecting = mongo.db.canonical_entities.count_documents(
            {'document_count': {'$gt': 1}})
        assert connecting > 0, 'no entity links two documents — the graph has no edges'

    def test_no_junk_entity_types_remain(self, mongo):
        """Quantity entities used to become graph nodes joining unrelated docs."""
        junk = mongo.db.canonical_entities.count_documents(
            {'entity_type': {'$in': ['CARDINAL', 'ORDINAL', 'QUANTITY',
                                     'DATE', 'TIME', 'PERCENT', 'MONEY']}})
        assert junk == 0, f'{junk} quantity-type entities are still in the graph'

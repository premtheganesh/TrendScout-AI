"""
Incremental processing against a throwaway MongoDB: only stale rows are
touched, legacy rows are adopted, the canonical index swaps atomically and
snapshots are idempotent. Heavy models are replaced by fakes.
"""

from datetime import date

import numpy as np
import pytest

from conftest import needs_mongo
from src.corpus.embeddings import from_stored, to_binary
from src.corpus.identity import content_hash
from src.corpus.schema import ensure_indexes
from src.corpus.types import COLLECTION
from src.ingest.store import prepare
from src.pipeline import embed, entities, hashes, index, snapshots
from src.pipeline.run import Pipeline

pytestmark = needs_mongo

DIM = 8


class FakeExtractor:
    def __init__(self):
        self.calls = 0

    def extract_entities(self, text):
        self.calls += 1
        words = [w.strip('.,') for w in text.split() if w[:1].isupper()]
        return [{'entity_text': w, 'entity_type': 'ORG', 'count': 1} for w in words]


class FakeGenerator:
    dimension = DIM

    def __init__(self):
        self.calls = 0

    def embed_passages_batch(self, texts, show_progress=False):
        self.calls += len(texts)
        return np.array([[float(len(t) % 7)] * DIM for t in texts], dtype='float32')


@pytest.fixture
def db():
    from pymongo import MongoClient
    from src.config import get_settings
    client = MongoClient(get_settings().mongodb_uri, tz_aware=True)
    name = 'trendscout_test_pipeline'
    client.drop_database(name)
    database = client[name]
    ensure_indexes(database)
    yield database
    client.drop_database(name)
    client.close()


def seed(db, n=3):
    docs = [prepare({'full_name': f'org/repo{i}', 'description': f'Repo Number {i} by Acme',
                     'stars': 10 * i, 'forks': i, 'created_at': '2026-08-30T00:00:00Z'},
                    'repo', 'github') for i in range(n)]
    db[COLLECTION].insert_many(docs)
    return docs


class TestEmbeddingStorage:
    def test_binary_roundtrip(self):
        vec = np.arange(DIM, dtype='float32') / 3
        stored = to_binary(vec)
        assert len(bytes(stored)) == DIM * 4
        assert np.allclose(from_stored(stored), vec)

    def test_legacy_list_is_decoded(self):
        assert from_stored([1.0, 2.0]).dtype == np.float32
        assert from_stored(None) is None


class TestRefreshHashes:
    def test_adopts_legacy_rows_and_rehashes_changed_text(self, db):
        seed(db, 1)
        doc = db[COLLECTION].find_one()
        # Legacy shape: embedding present, no marker, stale hash.
        db[COLLECTION].update_one({'_id': doc['_id']}, {'$set': {
            'embedding': [0.1] * DIM, 'entities': [], 'content_hash': 'old'}})

        stats = hashes.refresh_hashes(db)
        assert stats == {'scanned': 1, 'adopted': 1, 'rehashed': 1, 'converted': 1}
        after = db[COLLECTION].find_one()
        assert from_stored(after['embedding']).shape == (DIM,) and not isinstance(after['embedding'], list)
        assert after['embedding_hash'] == 'old' and after['entities_hash'] == 'old'
        assert after['content_hash'] == content_hash(after, 'repo') != 'old'

    def test_is_idempotent(self, db):
        seed(db, 2)
        hashes.refresh_hashes(db)
        assert hashes.refresh_hashes(db)['rehashed'] == 0


class TestIncrementalStages:
    def test_entities_only_for_stale_documents(self, db):
        seed(db, 3)
        extractor = FakeExtractor()
        assert entities.extract_stale(db, extractor) == 3
        assert extractor.calls == 3

        # Nothing changed -> nothing processed.
        assert entities.extract_stale(db, extractor) == 0

        # One document's text changes -> exactly one re-extraction.
        doc = db[COLLECTION].find_one({'full_name': 'org/repo1'})
        db[COLLECTION].update_one({'_id': doc['_id']},
                                  {'$set': {'description': 'Now About Zeta', 'content_hash': 'changed'}})
        assert entities.extract_stale(db, extractor) == 1
        assert db[COLLECTION].find_one({'_id': doc['_id']})['entities_hash'] == 'changed'

    def test_embed_only_for_stale_documents(self, db):
        seed(db, 3)
        generator = FakeGenerator()
        assert embed.embed_stale(db, generator) == 3
        assert embed.embed_stale(db, generator) == 0
        stored = db[COLLECTION].find_one()['embedding']
        assert from_stored(stored).shape == (DIM,)

    def test_force_redoes_everything(self, db):
        seed(db, 2)
        generator = FakeGenerator()
        embed.embed_stale(db, generator)
        assert embed.embed_stale(db, generator, force=True) == 2

    def test_canonical_index_is_rebuilt_atomically(self, db):
        seed(db, 2)
        entities.extract_stale(db, FakeExtractor())
        db['canonical_entities'].insert_one({'entity_text': 'Stale', 'entity_type': 'ORG'})

        result = entities.rebuild_canonical_index(db)
        names = {e['entity_text'] for e in db['canonical_entities'].find()}
        assert 'Stale' not in names and 'Acme' in names
        assert result['linking'] >= 1                     # "Acme" links both repos
        assert 'canonical_entities_building' not in db.list_collection_names()
        acme = db['canonical_entities'].find_one({'entity_text': 'Acme'})
        assert {m['type'] for m in acme['mentioned_in']} == {'repo'}

    def test_index_build_uses_stored_vectors(self, db, tmp_path):
        seed(db, 3)
        embed.embed_stale(db, FakeGenerator())
        result = index.build_indexes(db, str(tmp_path))
        assert result['vectors'] == 3 and result['dimension'] == DIM
        assert result['bm25_documents'] == 3
        assert (tmp_path / 'faiss_index.bin').exists()

    def test_snapshots_are_one_row_per_document_per_day(self, db):
        seed(db, 2)
        day = date(2026, 9, 12)
        assert snapshots.capture(db, today=day) == {'repo': 2}
        assert snapshots.capture(db, today=day) == {'repo': 2}
        assert db['metric_snapshots'].count_documents({}) == 2
        row = db['metric_snapshots'].find_one({'date': '2026-09-12'})
        assert row['stars'] in (0, 10) and row['type'] == 'repo'


class TestPipelineRun:
    def test_runs_stages_in_order_and_logs(self, db, tmp_path):
        seed(db, 2)
        pipeline = Pipeline(db, index_dir=str(tmp_path),
                            extractor=FakeExtractor(), generator=FakeGenerator())
        record = pipeline.run(['refresh', 'entities', 'embed', 'index', 'snapshots'])
        assert record['status'] == 'ok'
        assert list(record['results']) == ['refresh', 'entities', 'embed', 'index', 'snapshots']
        assert record['results']['embed']['embedded'] == 2
        assert db['runs'].find_one({'source': 'pipeline'})['status'] == 'ok'

    def test_second_run_touches_nothing(self, db, tmp_path):
        seed(db, 2)
        generator = FakeGenerator()
        pipeline = Pipeline(db, index_dir=str(tmp_path),
                            extractor=FakeExtractor(), generator=generator)
        pipeline.run(['refresh', 'entities', 'embed'])
        second = pipeline.run(['refresh', 'entities', 'embed'])
        assert second['results']['entities']['processed'] == 0
        assert second['results']['embed']['embedded'] == 0
        assert generator.calls == 2

    def test_failed_stage_stops_and_is_recorded(self, db, tmp_path):
        pipeline = Pipeline(db, index_dir=str(tmp_path),
                            extractor=FakeExtractor(), generator=FakeGenerator())
        record = pipeline.run(['index'])          # nothing embedded -> index fails
        assert record['status'] == 'failed'
        assert record['error'].startswith('index:')
        assert 'index' not in record['results']

"""
Upsert semantics and failure isolation, against a throwaway MongoDB
database so the real unique index and update paths are exercised.
"""

from datetime import datetime, timedelta, timezone

import pytest

from conftest import needs_mongo
from src.corpus.schema import ensure_indexes
from src.corpus.types import COLLECTION
from src.ingest.runner import run_source, run_sources
from src.ingest.store import DocumentStore, prepare
from src.sources.base import Source

pytestmark = needs_mongo

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
T1 = T0 + timedelta(days=7)


@pytest.fixture
def db():
    from pymongo import MongoClient
    from src.config import get_settings
    client = MongoClient(get_settings().mongodb_uri, tz_aware=True)
    name = 'trendscout_test_ingest'
    client.drop_database(name)
    database = client[name]
    ensure_indexes(database)
    yield database
    client.drop_database(name)
    client.close()


def repo(full_name='a/b', description='first', stars=1):
    return prepare({'full_name': full_name, 'description': description,
                    'stars': stars, 'created_at': '2026-08-30T00:00:00Z'},
                   'repo', 'github')


class TestDocumentStore:
    def test_first_upsert_is_new_and_stamps_first_seen(self, db):
        store = DocumentStore(db)
        assert store.upsert(repo(), now=T0) == 'new'
        stored = db[COLLECTION].find_one({'doc_key': 'repo:gh:a/b'})
        assert stored['first_seen_at'] == T0 and stored['last_seen_at'] == T0
        assert stored['event_at'] == datetime(2026, 8, 30, tzinfo=timezone.utc)

    def test_same_content_is_unchanged_but_bumps_last_seen(self, db):
        store = DocumentStore(db)
        store.upsert(repo(), now=T0)
        assert store.upsert(repo(), now=T1) == 'unchanged'
        stored = db[COLLECTION].find_one({'doc_key': 'repo:gh:a/b'})
        assert stored['first_seen_at'] == T0 and stored['last_seen_at'] == T1
        assert db[COLLECTION].count_documents({}) == 1

    def test_changed_text_overwrites_fields_but_keeps_identity(self, db):
        store = DocumentStore(db)
        store.upsert(repo(), now=T0)
        original = db[COLLECTION].find_one({'doc_key': 'repo:gh:a/b'})
        db[COLLECTION].update_one({'_id': original['_id']},
                                  {'$set': {'entities': [{'entity_text': 'x'}]}})

        assert store.upsert(repo(description='rewritten'), now=T1) == 'changed'
        stored = db[COLLECTION].find_one({'doc_key': 'repo:gh:a/b'})
        assert stored['_id'] == original['_id']
        assert stored['description'] == 'rewritten'
        assert stored['first_seen_at'] == T0
        assert stored['entities'] == [{'entity_text': 'x'}]   # protected
        assert stored['content_hash'] != original['content_hash']

    def test_unique_key_index_blocks_duplicates(self, db):
        db[COLLECTION].insert_one(repo())
        from pymongo.errors import DuplicateKeyError
        with pytest.raises(DuplicateKeyError):
            db[COLLECTION].insert_one(repo())


class FakeSource(Source):
    doc_type = 'repo'
    source_tag = 'github'
    default_window_days = 7

    def __init__(self, name, items=(), fail=False):
        self.name = name
        self.items = list(items)
        self.fail = fail

    def fetch(self, since):
        if self.fail:
            raise RuntimeError('feed is down')
        yield from self.items

    def normalize(self, raw):
        if raw == 'skip':
            return None
        if raw == 'boom':
            raise ValueError('bad item')
        return {'full_name': raw, 'description': 'd', 'created_at': '2026-08-30T00:00:00Z'}


class TestRunner:
    def test_counts_new_changed_unchanged_skipped_errors(self, db):
        source = FakeSource('fake', ['a/b', 'c/d', 'skip', 'boom'])
        first = run_source(source, db)
        assert (first['new'], first['skipped'], first['errors']) == (2, 1, 1)
        assert first['status'] == 'ok'

        second = run_source(source, db)
        assert second['new'] == 0 and second['unchanged'] == 2

        assert db['runs'].count_documents({'source': 'fake'}) == 2

    def test_failing_source_is_isolated_and_logged(self, db):
        records = run_sources([FakeSource('broken', fail=True),
                               FakeSource('fine', ['x/y'])], db)
        assert [r['status'] for r in records] == ['failed', 'ok']
        assert 'feed is down' in records[0]['error']
        assert db[COLLECTION].count_documents({}) == 1
        assert db['runs'].find_one({'source': 'broken'})['status'] == 'failed'

    def test_dry_run_writes_nothing(self, db):
        record = run_source(FakeSource('dry', ['a/b']), db, dry_run=True)
        assert record['new'] == 1
        assert db[COLLECTION].count_documents({}) == 0
        assert db['runs'].count_documents({}) == 0

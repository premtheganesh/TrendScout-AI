"""Topic normalisation, rising arithmetic, velocity from snapshots."""

from datetime import date, datetime, timedelta, timezone

import pytest

from conftest import needs_mongo
from src.corpus.schema import ensure_indexes
from src.corpus.types import COLLECTION
from src.digest.weeks import week_bounds
from src.pipeline.snapshots import SNAPSHOTS
from src.trends.compute import (TOPIC_WEEKLY, compute_topic_weekly, previous_weeks,
                                rising_topics, velocity)
from src.trends.topics import document_topics, normalize_topic


class TestTopics:
    def test_normalises_spelling_and_aliases(self):
        assert normalize_topic('Large Language Models') == 'llm'
        assert normalize_topic('AI Agents') == 'agent'
        assert normalize_topic('Retrieval-Augmented Generation') == 'rag'
        assert normalize_topic('  Generative AI ') == 'generative-ai'

    def test_drops_generic_and_junk(self):
        assert normalize_topic('AI') == '' and normalize_topic('python') == ''
        assert normalize_topic('license:mit') == ''
        assert normalize_topic('') == '' and normalize_topic(None) == ''

    def test_topics_per_type(self):
        repo = {'type': 'repo', 'topics': ['llm', 'agents', 'python', 'LLM']}
        assert document_topics(repo) == ['llm', 'agent']
        model = {'type': 'model', 'tags': ['text-generation', 'fp8'], 'pipeline_tag': 'text-generation'}
        assert document_topics(model) == ['text-generation', 'fp8']
        assert document_topics({'type': 'repo'}) == []


class TestPreviousWeeks:
    def test_walks_back_across_a_year_boundary(self):
        assert previous_weeks('2026-W02', 3) == ['2026-W01', '2025-W52', '2025-W51']


WEEK = '2026-W37'
START, _ = week_bounds(WEEK)


@needs_mongo
class TestRisingAndVelocity:
    @pytest.fixture
    def db(self):
        from pymongo import MongoClient
        from src.config import get_settings
        client = MongoClient(get_settings().mongodb_uri, tz_aware=True)
        name = 'trendscout_test_trends'
        client.drop_database(name)
        database = client[name]
        ensure_indexes(database)
        yield database
        client.drop_database(name)
        client.close()

    def seed_docs(self, db, per_week):
        """per_week: {weeks_ago: {topic: n}} -> documents with event_at in that week."""
        docs, i = [], 0
        for weeks_ago, topics in per_week.items():
            for topic, n in topics.items():
                for _ in range(n):
                    i += 1
                    docs.append({'_id': f'd{i}', 'type': 'repo', 'doc_key': f'k{i}',
                                 'topics': [topic], 'event_at': START - timedelta(days=7 * weeks_ago - 1)})
        db[COLLECTION].insert_many(docs)

    def test_rising_scores_and_min_count(self, db):
        self.seed_docs(db, {0: {'agent': 9, 'rag': 2, 'steady': 4},
                            1: {'agent': 1, 'steady': 4}, 2: {'agent': 1, 'steady': 4},
                            3: {'agent': 1, 'steady': 4}, 4: {'agent': 1, 'steady': 4}})
        compute_topic_weekly(db, WEEK, trailing_weeks=6)
        result = rising_topics(db, WEEK)
        assert result['insufficient_history'] is False and result['history_weeks'] == 4
        topics = {r['topic']: r for r in result['rising']}
        assert 'rag' not in topics                                 # below MIN_COUNT
        assert topics['agent']['baseline'] == 1.0
        assert topics['agent']['score'] == round((9 - 1) / (2 ** 0.5), 3)
        assert topics['steady']['score'] == 0.0
        assert result['rising'][0]['topic'] == 'agent'

    def test_insufficient_history_is_flagged_not_hidden(self, db):
        self.seed_docs(db, {0: {'agent': 5}, 1: {'agent': 1}})
        compute_topic_weekly(db, WEEK)
        result = rising_topics(db, WEEK)
        assert result['insufficient_history'] is True and result['history_weeks'] == 1
        assert result['rising'][0]['topic'] == 'agent'

    def test_recount_is_idempotent(self, db):
        self.seed_docs(db, {0: {'agent': 3}})
        compute_topic_weekly(db, WEEK)
        compute_topic_weekly(db, WEEK)
        assert db[TOPIC_WEEKLY].count_documents({'topic': 'agent', 'week': WEEK}) == 1

    def test_velocity_from_snapshots(self, db):
        db[SNAPSHOTS].insert_many([
            {'doc_id': 'a', 'type': 'repo', 'date': '2026-09-05', 'stars': 100},
            {'doc_id': 'a', 'type': 'repo', 'date': '2026-09-12', 'stars': 400},
            {'doc_id': 'b', 'type': 'repo', 'date': '2026-09-05', 'stars': 50},
            {'doc_id': 'b', 'type': 'repo', 'date': '2026-09-12', 'stars': 60},      # below floor
            {'doc_id': 'c', 'type': 'repo', 'date': '2026-09-12', 'stars': 9000},    # one snapshot only
        ])
        now = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)
        result = velocity(db, 'repo', days=7, now=now)
        assert result['insufficient_history'] is False
        assert [r['doc_id'] for r in result['items']] == ['a']
        assert result['items'][0]['gained'] == 300

    def test_velocity_with_one_day_of_snapshots_is_insufficient(self, db):
        db[SNAPSHOTS].insert_one({'doc_id': 'a', 'type': 'repo', 'date': '2026-09-12', 'stars': 100})
        result = velocity(db, 'repo', now=datetime(2026, 9, 12, 12, tzinfo=timezone.utc))
        assert result['insufficient_history'] is True and result['items'] == []

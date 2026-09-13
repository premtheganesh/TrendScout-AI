"""Funding extraction: schema, rule-derived confidence, dedupe across outlets."""

from datetime import datetime, timedelta, timezone

import pytest

from conftest import needs_mongo
from src.corpus.schema import ensure_indexes
from src.corpus.types import COLLECTION
from src.extraction.funding import (EXTRACTION_VERSION, FUNDING_ROUNDS, ExtractedRound,
                                    amount_usd, confidence_for, dedupe_rounds, extract_stale,
                                    is_single_announcement, merge_into, purge_non_rounds,
                                    round_key, same_round, to_record)

T = datetime(2026, 9, 10, tzinfo=timezone.utc)


class TestSchema:
    def test_normalises_round_and_currency(self):
        e = ExtractedRound.model_validate({'is_funding_round': True, 'company': 'Acme',
                                           'amount': 5e6, 'currency': 'usd', 'round': 'Series_A',
                                           'investors': ['a16z', ' Accel ', '']})
        assert e.currency == 'USD' and e.round == 'series a' and e.investors == ['a16z', 'Accel']

    def test_unknown_round_becomes_other_and_junk_is_dropped(self):
        e = ExtractedRound.model_validate({'is_funding_round': True, 'round': 'mezzanine', 'investors': 'a16z'})
        assert e.round == 'other' and e.investors == []

    def test_negative_amount_is_rejected(self):
        with pytest.raises(Exception):
            ExtractedRound.model_validate({'is_funding_round': True, 'amount': -1})


class TestAmounts:
    def test_conversion_table(self):
        assert amount_usd(75e6, 'USD') == 75_000_000
        assert amount_usd(2.6e6, 'EUR') == 2_808_000
        assert amount_usd(47e7, 'INR') == 5_640_000
        assert amount_usd(1, 'XYZ') is None and amount_usd(None, 'USD') is None


class TestConfidence:
    def test_high_when_company_and_amount_are_literal(self):
        e = ExtractedRound(is_funding_round=True, company='Kinetix AI', amount=75e6, currency='USD')
        assert confidence_for(e, 'Kinetix AI raises $75M angel round') == 'high'
        assert confidence_for(e, 'Kinetix AI raises $75 million') == 'high'

    def test_medium_when_amount_is_absent_or_paraphrased(self):
        e = ExtractedRound(is_funding_round=True, company='Harvey', amount=None, currency=None)
        assert confidence_for(e, 'Harvey reaches $15.5B valuation in new round') == 'medium'
        e = ExtractedRound(is_funding_round=True, company='Harvey', amount=550e6, currency='USD')
        assert confidence_for(e, 'Harvey raised half a billion') == 'medium'

    def test_low_when_company_is_not_in_the_text(self):
        e = ExtractedRound(is_funding_round=True, company='Boring Company', amount=3e9, currency='USD')
        assert confidence_for(e, "Elon Musk's tunnel startup raises $3 billion") == 'low'


def record(company='Graph AI', amount=13.3e6, currency='USD', round_='series a', day=0, doc='a1', **extra):
    e = ExtractedRound(is_funding_round=True, company=company, amount=amount, currency=currency, round=round_, **extra)
    article = {'_id': doc, 'event_at': T + timedelta(days=day), 'publisher': 'x'}
    return to_record(e, article, f'{company} raises ${amount / 1e6:g} million', 'stub')


class TestSameRound:
    def test_same_company_amount_within_10pct_and_two_weeks(self):
        assert same_round(record(), record(amount=13.5e6, day=3, doc='a2'))

    def test_currency_differences_still_match_within_tolerance(self):
        a = record('Kinetix AI', 75e6, 'USD', 'angel')
        b = record('Kinetix AI', 5e8, 'CNY', 'angel', doc='a2')     # 70M USD
        assert same_round(a, b)

    def test_different_round_or_amount_or_date_is_a_different_round(self):
        assert not same_round(record(), record(round_='series b', doc='a2'))
        assert not same_round(record(), record(amount=30e6, doc='a2'))
        assert not same_round(record(), record(day=40, doc='a2'))
        assert not same_round(record(company='A'), record(company='B'))


@needs_mongo
class TestMergeAndExtract:
    @pytest.fixture
    def db(self):
        from pymongo import MongoClient
        from src.config import get_settings
        client = MongoClient(get_settings().mongodb_uri, tz_aware=True)
        name = 'trendscout_test_funding'
        client.drop_database(name)
        database = client[name]
        ensure_indexes(database)
        yield database
        client.drop_database(name)
        client.close()

    def test_two_outlets_become_one_round_with_both_sources(self, db):
        rid1, how1 = merge_into(db, record(doc='a1'))
        rid2, how2 = merge_into(db, record(amount=13.3e6, day=1, doc='a2', lead_investors=['Insight Partners']))
        assert (how1, how2) == ('new', 'merged') and rid1 == rid2
        stored = db[FUNDING_ROUNDS].find_one({'_id': rid1})
        assert stored['source_doc_ids'] == ['a1', 'a2']
        assert stored['lead_investors'] == ['Insight Partners']
        assert db[FUNDING_ROUNDS].count_documents({}) == 1

    def test_extract_stale_processes_each_article_once(self, db):
        db[COLLECTION].insert_many([
            {'_id': 'a1', 'type': 'article', 'doc_key': 'k1', 'content_hash': 'h1', 'event_at': T,
             'title': 'Acme raises $5M seed', 'description': 'Acme, a startup, raised $5 million.'},
            {'_id': 'a2', 'type': 'article', 'doc_key': 'k2', 'content_hash': 'h2', 'event_at': T,
             'title': 'Why agents fail', 'description': 'opinion'},
            {'_id': 'a3', 'type': 'article', 'doc_key': 'k3', 'content_hash': 'h3', 'event_at': T,
             'title': 'Seed Capital raises €130M for Fund V', 'description': 'a VC fund raising its own capital'},
        ])

        class StubLLM:
            model = 'stub'
            calls = 0

            def generate_json(self, prompt, system_prompt=None, temperature=0.0):
                StubLLM.calls += 1
                if 'Acme' in prompt:
                    return {'is_funding_round': True, 'company': 'Acme', 'amount': 5e6,
                            'currency': 'USD', 'round': 'seed', 'investors': []}
                return {'is_funding_round': False}

        stats = extract_stale(db, StubLLM(), 'stub')
        assert stats['prefiltered_out'] == 1                   # "Why agents fail"
        assert stats['extracted'] == 1 and stats['no_round'] == 1 and stats['new'] == 1
        assert StubLLM.calls == 2                              # regex saved one call
        assert db[COLLECTION].find_one({'_id': 'a1'})['funding_round_id']
        assert db[COLLECTION].find_one({'_id': 'a3'})['funding_round_id'] is None
        assert db[COLLECTION].find_one({'_id': 'a1'})['funding_extraction_version'] == EXTRACTION_VERSION

        again = extract_stale(db, StubLLM(), 'stub')
        assert again['considered'] == 0 and StubLLM.calls == 2

        stored = db[FUNDING_ROUNDS].find_one()
        assert stored['confidence'] == 'high' and stored['amount_usd'] == 5_000_000


class TestNotARound:
    def test_roundups_and_rumours_are_filtered_before_the_model(self):
        for title in ("The Week's 10 Biggest Funding Rounds: Cognition Leads", "Funding Wrap: three startups raise",
                      "AI Firm Cohere in Talks for Up to $3 Billion Raise", "Positron reportedly raising at $5B",
                      "China And AI Lead Asia's Startup Funding To Multiyear Peak In Q2", "Weekly funding round-up!"):
            assert not is_single_announcement(title), title

    def test_single_announcements_pass(self):
        for title in ("Harvey raises $550M at $15.5B valuation", "Graph AI raises $13.3M in Series A funding led by Insight"):
            assert is_single_announcement(title), title


class TestRoundKey:
    def test_drops_a_trailing_ai(self):
        assert round_key('mistralai') == 'mistral' == round_key('mistral')
        assert round_key('cognitionai') == 'cognition'
        assert round_key('ai') == 'ai'                       # too short to strip

    def test_same_round_across_ai_suffix(self):
        a = record('Mistral', 3e9, 'EUR', None)
        b = record('Mistral AI', 3.5e9, 'USD', None, doc='a2')   # €3B ≈ $3.24B, within 20%
        assert same_round(a, b)


@needs_mongo
class TestSelfHealing:
    @pytest.fixture
    def db(self):
        from pymongo import MongoClient
        from src.config import get_settings
        client = MongoClient(get_settings().mongodb_uri, tz_aware=True)
        name = 'trendscout_test_funding2'
        client.drop_database(name)
        database = client[name]
        ensure_indexes(database)
        yield database
        client.drop_database(name)
        client.close()

    def test_id_collision_does_not_overwrite_a_different_round(self, db):
        rid1, _ = merge_into(db, record('Jaipur Robotics', 47e7, 'INR', 'seed', doc='a1'))     # $5.64M
        rid2, how = merge_into(db, record('Jaipur Robotics', 1e6, 'USD', 'seed', doc='a2'))    # clearly different
        assert how == 'new' and rid1 != rid2
        assert db[FUNDING_ROUNDS].count_documents({}) == 2

    def test_dedupe_merges_ai_suffix_variants(self, db):
        db[FUNDING_ROUNDS].insert_many([
            {**record('Mistral', 3e9, 'EUR', None, doc='a1'), '_id': 'r1', 'extracted_at': T},
            {**record('Mistral AI', 3.5e9, 'USD', None, doc='a2'), '_id': 'r2', 'extracted_at': T + timedelta(hours=1)},
        ])
        db[COLLECTION].insert_one({'_id': 'a2', 'type': 'article', 'doc_key': 'k', 'funding_round_id': 'r2'})
        assert dedupe_rounds(db) == 1
        left = list(db[FUNDING_ROUNDS].find())
        assert len(left) == 1 and set(left[0]['source_doc_ids']) == {'a1', 'a2'}
        assert db[COLLECTION].find_one({'_id': 'a2'})['funding_round_id'] == left[0]['_id']
        assert dedupe_rounds(db) == 0

    def test_purge_removes_rounds_whose_only_sources_are_roundups(self, db):
        from bson import ObjectId
        good, bad = ObjectId(), ObjectId()
        db[COLLECTION].insert_many([
            {'_id': good, 'type': 'article', 'doc_key': 'k1', 'title': 'Harvey raises $550M', 'funding_round_id': 'r1'},
            {'_id': bad, 'type': 'article', 'doc_key': 'k2', 'title': "The Week's 10 Biggest Funding Rounds", 'funding_round_id': 'r2'},
        ])
        db[FUNDING_ROUNDS].insert_many([
            {'_id': 'r1', 'company_key': 'harvey', 'source_doc_ids': [str(good)]},
            {'_id': 'r2', 'company_key': 'ssi', 'source_doc_ids': [str(bad)]},
        ])
        assert purge_non_rounds(db) == 1
        assert db[FUNDING_ROUNDS].count_documents({}) == 1
        assert db[COLLECTION].find_one({'_id': bad})['funding_round_id'] is None

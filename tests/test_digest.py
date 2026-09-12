"""
Weekly digest: deterministic selection, global citation numbering,
citation validation, and idempotent regeneration. The LLM is stubbed.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from conftest import needs_mongo
from src.corpus.schema import ensure_indexes
from src.corpus.types import COLLECTION
from src.digest.generate import (DIGESTS, build_digest, generate_week,
                                 number_sources, validate)
from src.digest.select import FUNDING_TITLE, Selection, select_week
from src.digest.weeks import resolve_week, week_bounds, week_id

WEEK = '2026-W37'
START, END = week_bounds(WEEK)


class TestWeeks:
    def test_bounds_are_monday_to_monday_utc(self):
        assert START == datetime(2026, 9, 7, tzinfo=timezone.utc)
        assert END == datetime(2026, 9, 14, tzinfo=timezone.utc)

    def test_week_id_round_trips(self):
        assert week_id(date(2026, 9, 12)) == WEEK
        assert week_id(date(2026, 9, 14)) == '2026-W38'

    def test_resolve(self):
        today = date(2026, 9, 12)
        assert resolve_week('current', today) == WEEK
        assert resolve_week('previous', today) == '2026-W36'
        assert resolve_week('2026-W30', today) == '2026-W30'
        with pytest.raises(ValueError):
            resolve_week('last week', today)


class TestFundingTitle:
    def test_matches_announcements(self):
        for title in ('Acme raises $50M Series B', 'Startup secures seed round',
                      'AI lab closes $1B round led by a16z', 'Harvey hits $15.5B valuation'):
            assert FUNDING_TITLE.search(title), title

    def test_ignores_other_news(self):
        for title in ('OpenAI ships new model', 'Why agents fail', 'The week in AI'):
            assert not FUNDING_TITLE.search(title), title


class TestValidate:
    def test_strips_unknown_citations_and_counts_uncited(self):
        text = "- Acme raised $5M [1]\n- Beta launched [9]\n- Gamma is cool\n- Delta【2】"
        cleaned, stats = validate(text, allowed={1, 2})
        assert '[9]' not in cleaned and '[1]' in cleaned and '[2]' in cleaned
        assert stats == {'invalid_citations': 1, 'uncited_bullets': 2, 'bullets': 4}


def doc(_id, doc_type, day, **fields):
    return {'_id': _id, 'type': doc_type, 'content_hash': f'h{_id}', 'doc_key': f'test:{_id}',
            'event_at': START + timedelta(days=day), **fields}


class StubLLM:
    model = 'stub'

    def __init__(self):
        self.calls = []

    def generate(self, prompt, system_prompt=None, temperature=0.0, max_tokens=0, reasoning_effort=None):
        self.calls.append(prompt)
        # Cite the first source given, plus a bogus one to be stripped.
        first = prompt.split('[', 1)[1].split(']', 1)[0]
        return f"- Something notable [{first}]\n- Fabricated [999]"


@pytest.fixture
def db():
    from pymongo import MongoClient
    from src.config import get_settings
    client = MongoClient(get_settings().mongodb_uri, tz_aware=True)
    name = 'trendscout_test_digest'
    client.drop_database(name)
    database = client[name]
    ensure_indexes(database)
    database[COLLECTION].insert_many([
        doc('l1', 'launch', 1, title='Volt', points=140, description='LLM gateway'),
        doc('l2', 'launch', 2, title='Orchestra', points=30, description='inference cloud'),
        doc('s1', 'startup', 3, name='Sitefire', description='AI content', points=0),
        doc('a1', 'article', 2, title='Acme raises $50M Series B', description='...'),
        doc('a2', 'article', 1, title='Why agents fail', description='opinion'),
        doc('a3', 'article', 3, title='Beta secures seed round', description='...'),
        doc('r1', 'repo', 4, full_name='x/fastrag', stars=1200, description='RAG'),
        doc('r2', 'repo', 4, full_name='y/tiny', stars=30, description='tiny'),
        doc('m1', 'model', 2, hf_id='org/model', trending_score=99),
        doc('p1', 'paper', 1, title='NCP', upvotes=231, summary='latent'),
        # outside the week
        doc('old', 'launch', -3, title='Old launch', points=999),
        {'_id': 'undated', 'type': 'launch', 'title': 'No date', 'points': 5, 'content_hash': 'x', 'doc_key': 'test:undated'},
    ])
    yield database
    client.drop_database(name)
    client.close()


@needs_mongo
class TestSelection:
    def test_groups_and_orders_deterministically(self, db):
        sel = select_week(db, WEEK, START, END)
        assert [d['_id'] for d in sel.sections['launches']] == ['l1', 'l2', 's1']
        assert [d['_id'] for d in sel.sections['funding']] == ['a3', 'a1']      # newest first
        assert [d['_id'] for d in sel.sections['open_source']] == ['r1', 'r2', 'm1', 'p1']

    def test_outside_and_undated_documents_are_excluded(self, db):
        ids = {d['_id'] for d in select_week(db, WEEK, START, END).documents}
        assert 'old' not in ids and 'undated' not in ids and 'a2' not in ids

    def test_input_hash_is_stable_and_content_sensitive(self, db):
        first = select_week(db, WEEK, START, END).input_hash
        assert select_week(db, WEEK, START, END).input_hash == first
        db[COLLECTION].update_one({'_id': 'l1'}, {'$set': {'content_hash': 'changed'}})
        assert select_week(db, WEEK, START, END).input_hash != first


@needs_mongo
class TestGeneration:
    def test_citations_are_numbered_globally_before_generation(self, db):
        sel = select_week(db, WEEK, START, END)
        per_section, flat = number_sources(sel)
        assert [s['n'] for s in flat] == list(range(1, 10))
        assert per_section['funding'][0]['n'] == 4          # after 3 launches

    def test_build_validates_each_section_against_its_own_numbers(self, db):
        sel = select_week(db, WEEK, START, END)
        llm = StubLLM()
        digest = build_digest(sel, llm, 'stub')
        assert len(llm.calls) == 3
        assert digest['warnings'] == {'invalid_citations': 3, 'uncited_bullets': 3}
        funding = next(s for s in digest['sections'] if s['key'] == 'funding')
        assert '[4]' in funding['markdown'] and '[999]' not in funding['markdown']
        assert digest['counts'] == {'launches': 3, 'funding': 2, 'open_source': 4}

    def test_regeneration_is_a_noop_when_inputs_are_unchanged(self, db):
        llm = StubLLM()
        first, status = generate_week(db, WEEK, START, END, llm, 'stub')
        assert status == 'generated' and len(llm.calls) == 3
        again, status = generate_week(db, WEEK, START, END, llm, 'stub')
        assert status == 'unchanged' and len(llm.calls) == 3
        assert again['input_hash'] == first['input_hash']
        assert db[DIGESTS].count_documents({}) == 1

    def test_changed_inputs_or_force_regenerate(self, db):
        llm = StubLLM()
        generate_week(db, WEEK, START, END, llm, 'stub')
        db[COLLECTION].update_one({'_id': 'a1'}, {'$set': {'content_hash': 'new'}})
        _, status = generate_week(db, WEEK, START, END, llm, 'stub')
        assert status == 'generated' and len(llm.calls) == 6
        _, status = generate_week(db, WEEK, START, END, llm, 'stub', force=True)
        assert status == 'generated' and len(llm.calls) == 9

    def test_empty_week_writes_nothing(self, db):
        llm = StubLLM()
        digest, status = generate_week(db, '2020-W01', *week_bounds('2020-W01'), llm, 'stub')
        assert digest is None and status == 'empty' and llm.calls == []

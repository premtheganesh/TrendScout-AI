"""Company resolution: strict match order, unique-name rule, deterministic rebuild."""

import pytest

from conftest import needs_mongo
from src.corpus.schema import ensure_indexes
from src.corpus.types import COLLECTION
from src.entities.resolve import (COMPANIES, FUNDING_ROUNDS, Resolver, build_companies,
                                  company_slug, registered_domain)


class TestRegisteredDomain:
    def test_strips_www_and_subdomains(self):
        assert registered_domain('https://www.app.withspecific.com/x?y=1') == 'withspecific.com'
        assert registered_domain('http://suno.com') == 'suno.com'

    def test_two_part_public_suffixes(self):
        assert registered_domain('https://www.deepmind.co.uk/about') == 'deepmind.co.uk'

    def test_shared_hosts_identify_nobody(self):
        assert registered_domain('https://github.com/acme/repo') == ''
        assert registered_domain('https://www.ycombinator.com/companies/x') == ''
        assert registered_domain('https://acme.vercel.app') == ''

    def test_garbage(self):
        assert registered_domain('') == '' and registered_domain('not a url') == ''


class TestResolver:
    def startup(self, _id, name, link='', yc_slug=''):
        return {'_id': _id, 'name': name, 'link': link, 'yc_slug': yc_slug, 'type': 'startup'}

    def test_yc_slug_beats_domain_beats_name(self):
        r = Resolver()
        r.add_startup(self.startup('a', 'Harvey', 'https://harvey.ai', 'harvey'))
        assert r.match(yc_slug='harvey') == 'yc-harvey'
        assert r.match(domain='harvey.ai') == 'yc-harvey'
        assert r.match(key='harvey') == 'yc-harvey'

    def test_same_company_from_two_sources_merges(self):
        r = Resolver()
        first = r.add_startup(self.startup('a', 'webAI', 'https://www.webai.com'))
        second = r.add_startup(self.startup('b', 'WebAI Inc.', 'https://webai.com/about'))
        assert first == second == 'd-webai-com'
        assert r.companies[first]['doc_ids']['startup'] == ['a', 'b']

    def test_ambiguous_name_never_matches(self):
        r = Resolver()
        r.add_startup(self.startup('a', 'Candor', 'https://candor.com'))
        r.add_startup(self.startup('b', 'Candor', 'https://candor.ai'))
        assert r.match(key='candor') is None
        assert r.match(domain='candor.ai') == 'd-candor-ai'

    def test_no_fuzzy_matching(self):
        r = Resolver()
        r.add_startup(self.startup('a', 'Harvey AI', 'https://harvey.ai'))
        assert r.match(key='harvey') is None          # "Harvey" != "Harvey AI"

    def test_slug_shapes(self):
        assert company_slug('suno', 'suno.com', 'suno') == 'yc-suno'
        assert company_slug('', 'suno.com', 'suno') == 'd-suno-com'
        assert company_slug('', '', 'suno') == 'n-suno'


@needs_mongo
class TestBuildCompanies:
    @pytest.fixture
    def db(self):
        from pymongo import MongoClient
        from src.config import get_settings
        client = MongoClient(get_settings().mongodb_uri, tz_aware=True)
        name = 'trendscout_test_companies'
        client.drop_database(name)
        database = client[name]
        ensure_indexes(database)
        database[COLLECTION].insert_many([
            {'_id': 's1', 'type': 'startup', 'doc_key': 'k1', 'name': 'Harvey', 'link': 'https://harvey.ai', 'yc_slug': 'harvey', 'yc_batch': 'W22'},
            {'_id': 's2', 'type': 'startup', 'doc_key': 'k2', 'name': 'Corvera', 'link': 'https://corvera.ai', 'yc_slug': 'corvera'},
            {'_id': 'l1', 'type': 'launch', 'doc_key': 'k3', 'company_slug': 'corvera', 'company_name': 'Corvera'},
            {'_id': 'l2', 'type': 'launch', 'doc_key': 'k4', 'company_slug': '', 'company_name': 'Harvey', 'link': ''},
            {'_id': 'l3', 'type': 'launch', 'doc_key': 'k5', 'company_slug': '', 'company_name': 'Nobody Known', 'link': ''},
        ])
        database[FUNDING_ROUNDS].insert_many([
            {'_id': 'r1', 'company': 'Harvey', 'company_key': 'harvey', 'amount_usd': 550_000_000, 'source_doc_ids': ['a1'], 'confidence': 'high'},
            {'_id': 'r2', 'company': 'Ghost', 'company_key': 'ghost', 'amount_usd': 1, 'source_doc_ids': [], 'confidence': 'high'},
            {'_id': 'r3', 'company': 'Cognition', 'company_key': 'cognition', 'amount_usd': 2_000_000_000, 'source_doc_ids': ['a2'], 'confidence': 'high'},
            {'_id': 'r4', 'company': 'Cognition', 'company_key': 'cognition', 'amount_usd': 1, 'source_doc_ids': ['a3'], 'confidence': 'low'},
        ])
        yield database
        client.drop_database(name)
        client.close()

    def test_links_by_slug_then_name_and_totals_funding(self, db):
        stats = build_companies(db)
        assert stats['companies'] == 4                      # 2 startups + Ghost + Cognition from news
        assert stats['launches_linked'] == 2 and stats['launches_unlinked'] == 1
        assert stats['rounds_linked'] == 1
        assert stats['companies_from_news'] == 2 and stats['rounds_to_news_companies'] == 2
        cognition = db[COMPANIES].find_one({'_id': 'n-cognition'})
        assert cognition['from_news_only'] and cognition['funding_total_usd'] == 2_000_000_000
        assert cognition['rounds'] == ['r3']                # the low-confidence one is ignored
        harvey = db[COMPANIES].find_one({'_id': 'yc-harvey'})
        assert harvey['funding_total_usd'] == 550_000_000 and harvey['rounds'] == ['r1']
        assert harvey['doc_ids'] == {'startup': ['s1'], 'launch': ['l2'], 'article': ['a1']}
        assert harvey['yc_batch'] == 'W22'

    def test_rebuild_is_deterministic_and_atomic(self, db):
        build_companies(db)
        db[COMPANIES].insert_one({'_id': 'stale'})
        build_companies(db)
        ids = {c['_id'] for c in db[COMPANIES].find()}
        assert ids == {'yc-harvey', 'yc-corvera', 'n-ghost', 'n-cognition'}
        assert 'companies_building' not in db.list_collection_names()

"""
Every source's normalize() on saved fixtures, with sockets disabled so a
test can never quietly hit the network.
"""

import json
import os
from datetime import datetime, timezone

import pytest

from src.corpus.identity import doc_key
from src.ingest.store import prepare
from src.sources.github import GitHubNewReposSource
from src.sources.rss import RSSSource
from src.sources.yc_oss import YCOSSSource, batch_year, looks_ai

pytestmark = pytest.mark.disable_socket

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures', 'sources')


def load_json(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


def load_bytes(name):
    with open(os.path.join(FIXTURES, name), 'rb') as f:
        return f.read()


class TestYCOSS:
    @pytest.fixture
    def companies(self):
        return load_json('yc_oss.json')

    def test_keeps_recent_ai_companies_only(self, companies):
        source = YCOSSSource(min_batch_year=2023)
        kept = [source.normalize(c) for c in companies]
        assert [k['name'] if k else None for k in kept] == ['Suno', None, None, None]

    def test_filters_are_explainable(self, companies):
        assert looks_ai(companies[0]) and looks_ai(companies[1])
        assert not looks_ai(companies[2])
        assert batch_year('Summer 2015') == 2015
        assert batch_year(None) is None

    def test_normalized_shape_and_key(self, companies):
        doc = YCOSSSource().normalize(companies[0])
        assert doc['description'] == 'Suno lets anyone make a song with AI.'
        assert doc['location'] == 'Cambridge, MA, USA'
        assert doc['yc_batch'] == 'Winter 2024'
        assert doc['company_url'] == 'https://www.ycombinator.com/companies/suno-ai'
        assert doc['link'] == 'https://suno.com'
        assert doc_key(doc, 'startup') == 'startup:yc:suno-ai'

    def test_prepare_sets_event_at_from_launch_date(self, companies):
        doc = prepare(YCOSSSource().normalize(companies[0]), 'startup', 'ycombinator')
        assert doc['event_at'] == datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert doc['type'] == 'startup' and doc['source'] == 'ycombinator'
        assert len(doc['content_hash']) == 40

    def test_no_ai_filter_keeps_old_ai_company_out_by_year(self, companies):
        source = YCOSSSource(min_batch_year=2023, ai_only=False)
        assert source.normalize(companies[2])['name'] == 'Plain Fintech'
        assert source.normalize(companies[1]) is None


class TestRSS:
    @pytest.fixture
    def source(self):
        return RSSSource(name='techcrunch_ai', url='https://example.invalid/feed/',
                         source_tag='techcrunch', max_pages=3)

    @pytest.fixture
    def entries(self, source):
        return source.parse_feed(load_bytes('techcrunch_ai.xml'))

    def test_parses_three_entries(self, entries):
        assert len(entries) == 3

    def test_normalizes_html_and_metadata(self, source, entries):
        doc = source.normalize(entries[0])
        assert doc['title'] == 'Acme AI raises $50M Series B to automate compliance'
        assert doc['description'] == 'Acme AI, a compliance startup , raised $50 million .'
        assert doc['author'] == 'Julie Bort'
        assert doc['categories'] == ['AI', 'Fundraising']
        assert doc['published_date'] == 'Thu, 10 Sep 2026 14:02:11 +0000'

    def test_key_strips_tracking_params(self, source, entries):
        doc = source.normalize(entries[0])
        assert doc_key(doc, 'article') == 'article:https://techcrunch.com/2026/09/10/acme-ai-raises-50m'

    def test_missing_author_and_tags_are_defaults(self, source, entries):
        doc = source.normalize(entries[1])
        assert doc['author'] == 'Unknown'
        assert doc['categories'] == []

    def test_entry_without_title_is_skipped(self, source, entries):
        assert source.normalize(entries[2]) is None

    def test_prepare_parses_published_date(self, source, entries):
        doc = prepare(source.normalize(entries[0]), 'article', 'techcrunch')
        assert doc['event_at'] == datetime(2026, 9, 10, 14, 2, 11, tzinfo=timezone.utc)


class TestGitHub:
    @pytest.fixture
    def items(self):
        return load_json('github_search.json')['items']

    def test_normalizes_a_repo(self, items):
        doc = GitHubNewReposSource().normalize(items[0])
        assert doc['full_name'] == 'IntelLabs/fastRAG'
        assert doc['stars'] == 1200
        assert doc['primary_language'] == 'Python'
        assert doc['topics'] == ['rag', 'llm']
        assert doc_key(doc, 'repo') == 'repo:gh:intellabs/fastrag'

    def test_awesome_lists_are_skipped(self, items):
        assert GitHubNewReposSource().normalize(items[1]) is None

    def test_nameless_is_skipped(self, items):
        assert GitHubNewReposSource().normalize(items[2]) is None

    def test_prepare_uses_created_at(self, items):
        doc = prepare(GitHubNewReposSource().normalize(items[0]), 'repo', 'github')
        assert doc['event_at'] == datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)


class TestYCLaunches:
    @pytest.fixture
    def hits(self):
        return load_json('yc_launches.json')['hits']

    def test_keeps_ai_launches_only(self, hits):
        from src.sources.yc_launches import YCLaunchesSource
        docs = [YCLaunchesSource().normalize(h) for h in hits]
        assert [d['title'] if d else None for d in docs] == ['Specific Labs', None, None]

    def test_shape_key_and_date(self, hits):
        from src.sources.yc_launches import YCLaunchesSource
        doc = prepare(YCLaunchesSource().normalize(hits[0]), 'launch', 'ycombinator')
        assert doc['doc_key'] == 'launch:yc:114670'
        assert doc['company_name'] == 'Specific Labs' and doc['yc_batch'] == 'Fall 2025'
        assert doc['company_url'] == 'https://www.ycombinator.com/companies/specific-labs'
        assert doc['event_at'] == datetime(2026, 9, 10, 19, 30, 5, 764000, tzinfo=timezone.utc)
        assert doc['points'] == 12


class TestHackerNews:
    @pytest.fixture
    def hits(self):
        return load_json('hn.json')

    def test_show_hn_needs_points_and_an_ai_title(self, hits):
        from src.sources.hn import HackerNewsSource
        source = HackerNewsSource(min_show_points=10)
        assert source.normalize(hits[0])['title'] == 'Volt – an open-source LLM gateway'
        assert source.normalize(hits[1]) is None      # 4 points
        assert source.normalize(hits[2]) is None      # not AI

    def test_show_hn_fields(self, hits):
        from src.sources.hn import HackerNewsSource
        doc = prepare(HackerNewsSource().normalize(hits[0]), 'launch', 'hackernews')
        assert doc['doc_key'] == 'launch:hn:45001'
        assert doc['company_name'] == 'Volt'
        assert doc['description'] == 'We built Volt to route requests across providers.'
        assert doc['url'] == 'https://volt.dev' and doc['hn_url'].endswith('45001')
        assert doc['event_at'] == datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)

    def test_launch_hn_parses_company_and_batch(self, hits):
        from src.sources.hn import HackerNewsSource
        doc = HackerNewsSource().normalize(hits[3])
        assert doc['kind'] == 'Launch HN'
        assert doc['company_name'] == 'Corvera' and doc['yc_batch'] == 'W26'
        assert doc['title'] == 'Corvera: Context layer for brand AI agents'
        assert doc['url'].endswith('45004')          # no external url -> HN thread


class TestHuggingFace:
    def test_model_normalization_drops_packaging_tags(self):
        from src.sources.huggingface import HFModelsSource
        items = load_json('hf_models.json')
        doc = prepare(HFModelsSource().normalize(items[0]), 'model', 'huggingface')
        assert doc['doc_key'] == 'model:hf:deepseek-ai/deepseek-v4.1-flash'
        assert doc['organization'] == 'deepseek-ai'
        assert 'license:mit' not in doc['tags'] and 'safetensors' not in doc['tags']
        assert 'deepseek_v41' in doc['tags']
        assert doc['event_at'].year == 2026 and doc['likes'] == 1997
        assert HFModelsSource().normalize(items[1]) is None

    def test_paper_normalization(self):
        from src.sources.huggingface import HFPapersSource
        items = load_json('hf_papers.json')
        doc = prepare(HFPapersSource().normalize(items[0]), 'paper', 'huggingface')
        assert doc['doc_key'] == 'paper:arxiv:2609.10715'
        assert doc['summary'].startswith('A latent-space language model')
        assert doc['keywords'] == ['latent-space language model', 'next-token prediction']
        assert doc['authors'] == ['NCP Team', 'Jiaqi Cao']
        assert doc['github_repo'] == 'https://github.com/ncp/ncp' and doc['github_stars'] == 410
        assert doc['event_at'] == datetime(2026, 9, 9, tzinfo=timezone.utc)
        assert HFPapersSource().normalize(items[1]) is None
        assert HFPapersSource(min_upvotes=500).normalize(items[0]) is None


class TestGoogleNews:
    def test_publisher_suffix_is_split_off(self):
        from src.sources.google_news import GoogleNewsSource
        source = GoogleNewsSource()
        entries = source.parse_feed(load_bytes('google_news.xml'))
        doc = source.normalize(entries[0])
        assert doc['title'] == 'Acme AI raises $50M Series B to automate compliance'
        assert doc['publisher'] == 'TechCrunch'
        assert doc['title_key'] == 'acmeairaises50mseriesbtoautomatecompliance'
        assert doc['description'] == ''

    def test_duplicate_of_an_original_outlet_story_is_skipped(self):
        from src.sources.google_news import GoogleNewsSource

        class FakeDocs:
            def find_one(self, query, *a, **k):
                return {'_id': 1} if query['title_key'] == 'acmeairaises50mseriesbtoautomatecompliance' else None

        db = {'documents': FakeDocs()}
        source = GoogleNewsSource()
        assert source.is_duplicate({'title_key': 'acmeairaises50mseriesbtoautomatecompliance'}, db)
        assert not source.is_duplicate({'title_key': 'somethingelse'}, db)


class TestStartupSavant:
    def test_parses_heading_metadata_and_link(self):
        from src.sources.startupsavant import StartupSavantSource, parse_page
        headings = parse_page(load_bytes('startupsavant.html').decode())
        source = StartupSavantSource()
        doc = prepare(source.normalize(headings[0]), 'startup', 'startupsavant')
        assert doc['name'] == 'webAI'
        assert doc['location'] == 'Austin, Texas'
        assert doc['funding'] == 'Series A, $43 Million'
        assert doc['investors'] == ['Forerunner Ventures', 'Mike Abbott', 'David Shuman']
        assert doc['link'] == 'https://www.webai.com'
        assert doc['doc_key'] == 'startup:savant:webai'     # same key as the migrated rows
        assert source.normalize(headings[1]) is None

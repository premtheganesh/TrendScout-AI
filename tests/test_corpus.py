"""Document identity, dates and the type registry. No database."""

from datetime import datetime, timezone

import pytest

from src.corpus.dates import event_at_for, first_seen_for, parse_datetime
from src.corpus.identity import canonical_url, content_hash, doc_key, name_key
from src.corpus.types import (DOC_TYPES, LEGACY_COLLECTIONS, NEO4J_LABEL_TO_TYPE,
                              TYPE_NAMES, label_for, normalize_type)


class TestRegistry:
    def test_every_type_has_a_label_and_neo4j_label(self):
        for name in TYPE_NAMES:
            assert DOC_TYPES[name].label and DOC_TYPES[name].neo4j_label

    def test_legacy_names_map_to_types(self):
        assert LEGACY_COLLECTIONS == {'startups': 'startup', 'articles': 'article',
                                      'github_repos': 'repo'}

    def test_six_types_are_registered(self):
        assert TYPE_NAMES == ('startup', 'article', 'repo', 'launch', 'model', 'paper')

    def test_normalize_type_accepts_both_spellings(self):
        assert normalize_type('repo') == 'repo'
        assert normalize_type('github_repos') == 'repo'
        assert normalize_type(' startup ') == 'startup'
        assert normalize_type('podcast') is None
        assert normalize_type(None) is None

    def test_neo4j_labels_round_trip(self):
        for name in TYPE_NAMES:
            assert NEO4J_LABEL_TO_TYPE[DOC_TYPES[name].neo4j_label] == name

    def test_label_for_unknown_type_is_harmless(self):
        assert label_for('startup') == 'Startup'
        assert label_for('mystery') == 'mystery'


class TestCanonicalUrl:
    def test_strips_tracking_and_normalises(self):
        url = 'HTTP://www.TechCrunch.com/2025/11/13/story/?utm_source=x&fbclid=y&id=7#top'
        assert canonical_url(url) == 'https://techcrunch.com/2025/11/13/story?id=7'

    def test_trailing_slash_and_scheme(self):
        assert canonical_url('http://example.com/a/') == 'https://example.com/a'

    def test_garbage_is_empty(self):
        assert canonical_url('not a url') == ''
        assert canonical_url(None) == ''


class TestNameKey:
    def test_drops_legal_suffixes_and_punctuation(self):
        assert name_key('Suno, Inc.') == 'suno'
        assert name_key('Abridge LLC') == 'abridge'

    def test_drops_a_trailing_parenthesised_alias(self):
        assert name_key('The Exploration Company (TEC)') == name_key('The Exploration Company')

    def test_keeps_ai(self):
        assert name_key('Harvey AI') == 'harveyai'
        assert name_key('Harvey') != name_key('Harvey AI')


class TestDocKey:
    def test_yc_startup_uses_its_slug(self):
        doc = {'name': 'Suno', 'source': 'ycombinator',
               'company_url': 'https://www.ycombinator.com/companies/suno-ai'}
        assert doc_key(doc, 'startup') == 'startup:yc:suno-ai'

    def test_savant_startup_uses_its_name(self):
        assert doc_key({'name': 'webAI', 'source': 'startupsavant'}, 'startup') == 'startup:savant:webai'

    def test_article_uses_canonical_url(self):
        doc = {'title': 'x', 'article_url': 'https://www.techcrunch.com/a/?utm_medium=rss'}
        assert doc_key(doc, 'article') == 'article:https://techcrunch.com/a'

    def test_article_without_url_falls_back_to_title(self):
        assert doc_key({'title': 'Big News!', 'source': 'techcrunch'}, 'article') == 'article:techcrunch:bignews'

    def test_repo_uses_full_name_lowercased(self):
        assert doc_key({'full_name': 'LangChain-AI/LangChain'}, 'repo') == 'repo:gh:langchain-ai/langchain'

    def test_new_type_keys(self):
        assert doc_key({'platform': 'yc', 'yc_launch_id': 7}, 'launch') == 'launch:yc:7'
        assert doc_key({'platform': 'hn', 'hn_id': '99'}, 'launch') == 'launch:hn:99'
        assert doc_key({'hf_id': 'Org/Model'}, 'model') == 'model:hf:org/model'
        assert doc_key({'arxiv_id': '2609.10715'}, 'paper') == 'paper:arxiv:2609.10715'
        with pytest.raises(ValueError):
            doc_key({'platform': 'yc'}, 'launch')

    def test_missing_identity_raises(self):
        with pytest.raises(ValueError):
            doc_key({}, 'repo')
        with pytest.raises(ValueError):
            doc_key({'name': 'x'}, 'podcast')

    def test_same_content_same_hash(self, sample_startup):
        assert content_hash(sample_startup, 'startup') == content_hash(dict(sample_startup), 'startup')
        changed = {**sample_startup, 'description': 'different'}
        assert content_hash(changed, 'startup') != content_hash(sample_startup, 'startup')


class TestDates:
    def test_rfc_2822(self):
        dt = parse_datetime('Thu, 13 Nov 2025 15:02:11 +0000')
        assert dt == datetime(2025, 11, 13, 15, 2, 11, tzinfo=timezone.utc)

    def test_iso_with_z_and_naive(self):
        assert parse_datetime('2025-11-13T01:19:25Z').tzinfo is not None
        assert parse_datetime('2025-11-13T01:19:25.317745').tzinfo == timezone.utc

    def test_unix_seconds(self):
        assert parse_datetime(0) == datetime(1970, 1, 1, tzinfo=timezone.utc)

    def test_garbage_is_none(self):
        assert parse_datetime('yesterday') is None
        assert parse_datetime('') is None
        assert parse_datetime(None) is None

    def test_event_at_per_type(self):
        assert event_at_for({'published_date': 'Thu, 13 Nov 2025 15:02:11 +0000'}, 'article').year == 2025
        assert event_at_for({'created_at': '2023-01-05T00:00:00Z'}, 'repo').year == 2023
        assert event_at_for({'name': 'no date'}, 'startup') is None
        assert event_at_for({'launched_at': 1704067200}, 'launch').year == 2024
        assert event_at_for({'created_at': '2026-09-10T02:17:58.000Z'}, 'model').day == 10
        assert event_at_for({'published_at': '2026-09-09T00:00:00.000Z'}, 'paper').day == 9

    def test_event_at_never_falls_back_to_first_seen(self):
        doc = {'name': 'Old Co', 'scraped_at': '2025-11-13T01:19:25', 'inserted_at': '2025-11-13T01:19:25'}
        assert event_at_for(doc, 'startup') is None
        assert first_seen_for(doc).year == 2025

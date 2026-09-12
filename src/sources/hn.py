"""
Hacker News launches via the Algolia API: "Show HN" posts with enough
points and an AI-ish title, and every "Launch HN" (YC companies launching
on HN). There is no `launch_hn` tag — those are found by title prefix.
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from src.search.document_text import normalize_whitespace
from src.sources import http
from src.sources.base import Source
from src.sources.rss import strip_html

logger = logging.getLogger(__name__)

SEARCH_BY_DATE = 'https://hn.algolia.com/api/v1/search_by_date'
SEARCH = 'https://hn.algolia.com/api/v1/search'

_AI_WORDS = re.compile(
    r'\b(ai|llm|llms|gpt|gpt-\d|agent|agents|agentic|ml|rag|copilot|chatbot|'
    r'neural|transformer|diffusion|embedding|embeddings|vector|openai|claude|'
    r'gemini|llama|mistral|ollama|whisper|voice ai|ai-powered|ai-native)\b',
    re.IGNORECASE)
_PREFIX = re.compile(r'^(show|launch)\s+hn\s*:\s*', re.IGNORECASE)
_LAUNCH_META = re.compile(r'^(?P<company>.+?)\s*\((?P<batch>YC\s+[A-Z]?\d{2,4}|YC\s+\w+\s*\d{4})\)\s*[–—:-]?\s*(?P<tagline>.*)$')
_SPLIT = re.compile(r'\s+[–—-]\s+')


class HackerNewsSource(Source):
    name = 'hn_launches'
    doc_type = 'launch'
    source_tag = 'hackernews'
    schedule = 'daily'
    default_window_days = 7

    def __init__(self, min_show_points: int = 10, max_pages: int = 5):
        self.min_show_points = min_show_points
        self.max_pages = max_pages

    def fetch(self, since: Optional[datetime]) -> Iterable[Any]:
        since = since or self.default_since()
        since_ts = int(since.timestamp())

        for page in range(self.max_pages):
            payload = http.get(SEARCH_BY_DATE, params={
                'tags': 'show_hn', 'numericFilters': f'created_at_i>{since_ts}',
                'hitsPerPage': 200, 'page': page,
            }).json()
            hits = payload.get('hits') or []
            for hit in hits:
                hit['_kind'] = 'Show HN'
            yield from hits
            if page + 1 >= payload.get('nbPages', 0):
                break

        payload = http.get(SEARCH, params={
            'query': 'Launch HN', 'restrictSearchableAttributes': 'title',
            'tags': 'story', 'numericFilters': f'created_at_i>{since_ts}',
            'hitsPerPage': 200,
        }).json()
        for hit in payload.get('hits') or []:
            if (hit.get('title') or '').lower().startswith('launch hn'):
                hit['_kind'] = 'Launch HN'
                yield hit

    def normalize(self, raw: Any) -> Optional[Dict[str, Any]]:
        raw_title = normalize_whitespace(raw.get('title') or '')
        object_id = raw.get('objectID')
        if not raw_title or not object_id:
            return None
        kind = raw.get('_kind') or ('Launch HN' if raw_title.lower().startswith('launch hn') else 'Show HN')
        points = raw.get('points') or 0

        title = _PREFIX.sub('', raw_title).strip()
        company_name, batch, tagline = '', '', ''
        if kind == 'Launch HN':
            match = _LAUNCH_META.match(title)
            if match:
                company_name = match.group('company').strip()
                batch = match.group('batch').replace('YC', '').strip()
                tagline = match.group('tagline').strip()
                title = f'{company_name}: {tagline}' if tagline else company_name
        else:
            if points < self.min_show_points or not _AI_WORDS.search(title):
                return None
            pieces = _SPLIT.split(title, maxsplit=1)
            if len(pieces) == 2:
                company_name, tagline = pieces[0].strip(), pieces[1].strip()

        story = strip_html(raw.get('story_text') or '')[:1500]
        return {
            'title': title,
            'description': story or tagline,
            'hn_id': str(object_id),
            'hn_url': f'https://news.ycombinator.com/item?id={object_id}',
            'url': (raw.get('url') or '').strip() or f'https://news.ycombinator.com/item?id={object_id}',
            'company_name': company_name,
            'yc_batch': batch,
            'tags': [],
            'points': points,
            'num_comments': raw.get('num_comments') or 0,
            'author': raw.get('author') or '',
            'launched_at': raw.get('created_at') or raw.get('created_at_i'),
            'platform': 'hn',
            'kind': kind,
        }

"""
Generic RSS/Atom source. One class covers every news feed; each feed is a
configuration, not code. Paging (`?paged=N`, WordPress-style) is optional
and stops as soon as a page is entirely older than `since`.
"""

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

import feedparser
from bs4 import BeautifulSoup

from src.corpus.dates import parse_datetime
from src.search.document_text import normalize_whitespace
from src.sources import http
from src.sources.base import Source

logger = logging.getLogger(__name__)


def strip_html(text: str) -> str:
    if not text:
        return ''
    return normalize_whitespace(BeautifulSoup(text, 'html.parser').get_text(' '))


class RSSSource(Source):
    doc_type = 'article'
    schedule = 'daily'
    default_window_days = 7

    def __init__(self, name: str, url: str, source_tag: str,
                 max_pages: int = 1, page_param: str = 'paged',
                 schedule: str = 'daily'):
        self.name = name
        self.url = url
        self.source_tag = source_tag
        self.max_pages = max_pages
        self.page_param = page_param
        self.schedule = schedule

    # -- network --------------------------------------------------------
    def fetch(self, since: Optional[datetime]) -> Iterable[Any]:
        for page in range(1, self.max_pages + 1):
            params = {self.page_param: page} if page > 1 else None
            response = http.get(self.url, params=params)
            entries = self.parse_feed(response.content)
            if not entries:
                break
            yield from entries

            if since is not None:
                dates = [parse_datetime(self.entry_date(e)) for e in entries]
                dates = [d for d in dates if d is not None]
                if dates and max(dates) < since:
                    break

    @staticmethod
    def parse_feed(content: bytes) -> list:
        return list(feedparser.parse(content).entries)

    @staticmethod
    def entry_date(entry) -> Optional[str]:
        return entry.get('published') or entry.get('updated')

    # -- pure -----------------------------------------------------------
    def normalize(self, raw: Any) -> Optional[Dict[str, Any]]:
        title = normalize_whitespace(raw.get('title') or '')
        link = (raw.get('link') or '').strip()
        if not title or not link:
            return None

        summary = raw.get('summary') or ''
        if not summary and raw.get('content'):
            summary = raw['content'][0].get('value', '')

        tags = [t.get('term') for t in raw.get('tags') or [] if t.get('term')]

        return {
            'title': title,
            'article_url': link,
            'published_date': self.entry_date(raw) or '',
            'description': strip_html(summary),
            'author': normalize_whitespace(raw.get('author') or '') or 'Unknown',
            'categories': tags,
            'publisher': self.source_tag,
        }

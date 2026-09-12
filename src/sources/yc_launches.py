"""
Y Combinator Launches (ycombinator.com/launches). Unofficial JSON behind
the page: 20 hits per page, newest first, `page=0` first. AI-ish launches
only, judged from the company's tags/industry or the launch text.
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from src.corpus.dates import parse_datetime
from src.search.document_text import normalize_whitespace
from src.sources import http
from src.sources.base import Source
from src.sources.yc_oss import looks_ai

logger = logging.getLogger(__name__)

LAUNCHES_URL = 'https://www.ycombinator.com/launches.json'
_AI_WORDS = re.compile(r'\b(ai|llm|llms|gpt|agent|agents|ml|machine learning|rag|copilot|'
                       r'chatbot|neural|model|models|automation|autonomous)\b', re.IGNORECASE)


class YCLaunchesSource(Source):
    name = 'yc_launches'
    doc_type = 'launch'
    source_tag = 'ycombinator'
    schedule = 'weekly'
    default_window_days = 7

    def __init__(self, max_pages: int = 5):
        self.max_pages = max_pages

    def fetch(self, since: Optional[datetime]) -> Iterable[Any]:
        since = since or self.default_since()
        for page in range(self.max_pages):
            payload = http.get(LAUNCHES_URL, params={'page': page}).json()
            hits = payload.get('hits') or []
            if not hits:
                break
            yield from hits
            dates = [parse_datetime(h.get('created_at')) for h in hits]
            dates = [d for d in dates if d]
            if since is not None and dates and max(dates) < since:
                break

    def normalize(self, raw: Any) -> Optional[Dict[str, Any]]:
        title = normalize_whitespace(raw.get('title') or '')
        launch_id = raw.get('id')
        if not title or launch_id is None:
            return None
        company = raw.get('company') or {}
        tagline = normalize_whitespace(raw.get('tagline') or '')
        if not (looks_ai(company) or _AI_WORDS.search(f'{title} {tagline}')):
            return None

        slug = (raw.get('slug') or '').strip()
        return {
            'title': title,
            'description': tagline,
            'yc_launch_id': launch_id,
            'launch_slug': slug,
            'url': raw.get('search_path') or f'https://www.ycombinator.com/launches/{slug}',
            'company_name': normalize_whitespace(company.get('name') or ''),
            'company_slug': company.get('slug') or '',
            'company_url': (f"https://www.ycombinator.com/companies/{company['slug']}"
                            if company.get('slug') else ''),
            'link': (company.get('url') or '').strip(),
            'yc_batch': company.get('batch') or '',
            'industry': company.get('industry') or '',
            'tags': list(company.get('tags') or []),
            'points': raw.get('total_vote_count') or 0,
            'launched_at': raw.get('created_at'),
            'platform': 'yc',
            'kind': 'YC Launch',
        }

"""
Y Combinator companies from the yc-oss mirror (rebuilt daily, no key,
no browser). Replaces the Playwright scraper that depended on `_coName`
CSS classes and a hardcoded 2025 batch URL.

The full feed is 6,200+ companies; we keep AI-ish ones from recent
batches so one-line YC blurbs do not become 95% of the corpus.
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from src.search.document_text import normalize_whitespace
from src.sources import http
from src.sources.base import Source

logger = logging.getLogger(__name__)

ALL_COMPANIES_URL = 'https://yc-oss.github.io/api/companies/all.json'

AI_TERMS = ('ai', 'artificial intelligence', 'machine learning', 'generative ai',
            'nlp', 'computer vision', 'llm', 'aiops', 'ai-powered', 'deep learning')

_YEAR = re.compile(r'(20\d\d)')


_AI_TERM_RE = re.compile(r'\b(' + '|'.join(re.escape(t) for t in AI_TERMS) + r')\b', re.IGNORECASE)


def looks_ai(company: Dict[str, Any]) -> bool:
    """Whole-word match on tags and industries. Substring matching is a
    trap here: "Retail", "Airlines" and "Training" all contain "ai"."""
    blobs = list(company.get('tags') or [])
    blobs += [company.get('industry') or '', company.get('subindustry') or '']
    return any(_AI_TERM_RE.search(b) for b in blobs if isinstance(b, str) and b)


def batch_year(batch: Optional[str]) -> Optional[int]:
    match = _YEAR.search(batch or '')
    return int(match.group(1)) if match else None


class YCOSSSource(Source):
    name = 'yc_oss'
    doc_type = 'startup'
    source_tag = 'ycombinator'
    schedule = 'weekly'
    default_window_days = None      # no time axis; the feed is the whole directory

    def __init__(self, min_batch_year: int = 2023, ai_only: bool = True):
        self.min_batch_year = min_batch_year
        self.ai_only = ai_only

    def fetch(self, since: Optional[datetime]) -> Iterable[Any]:
        response = http.get(ALL_COMPANIES_URL, timeout=120)
        companies = response.json()
        logger.info(f"yc-oss: {len(companies)} companies in feed")
        yield from companies

    def keep(self, company: Dict[str, Any]) -> bool:
        if self.ai_only and not looks_ai(company):
            return False
        year = batch_year(company.get('batch'))
        if self.min_batch_year and (year is None or year < self.min_batch_year):
            return False
        return True

    def normalize(self, raw: Any) -> Optional[Dict[str, Any]]:
        if not self.keep(raw):
            return None
        name = normalize_whitespace(raw.get('name') or '')
        slug = (raw.get('slug') or '').strip().lower()
        if not name or not slug:
            return None

        description = normalize_whitespace(raw.get('long_description') or '')
        one_liner = normalize_whitespace(raw.get('one_liner') or '')
        location = normalize_whitespace(raw.get('all_locations') or '')

        return {
            'name': name,
            'description': description or one_liner,
            'one_liner': one_liner,
            'location': location or 'Unknown',
            'yc_batch': raw.get('batch') or 'Unknown',
            'yc_slug': slug,
            'yc_id': raw.get('id'),
            'tags': list(raw.get('tags') or []),
            'industries': list(raw.get('industries') or []),
            'regions': list(raw.get('regions') or []),
            'team_size': raw.get('team_size'),
            'status': raw.get('status'),
            'stage': raw.get('stage'),
            'is_hiring': bool(raw.get('isHiring')),
            'launched_at': raw.get('launched_at'),        # unix seconds -> event_at
            'company_url': f'https://www.ycombinator.com/companies/{slug}',
            'link': (raw.get('website') or '').strip(),
        }

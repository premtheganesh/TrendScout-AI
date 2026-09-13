"""
GitHub repositories created inside the window, not the all-time most
starred. Several topic queries, de-duplicated by full name, capped per run
so the corpus gets the week's strongest new projects rather than 2,000
empty ones. Awesome-lists are skipped: they are link collections, not
projects.
"""

import logging
import re
import time

import requests
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

from src.config import get_settings
from src.sources import http
from src.sources.base import Source

logger = logging.getLogger(__name__)

SEARCH_URL = 'https://api.github.com/search/repositories'
DEFAULT_TOPICS = ('llm', 'generative-ai', 'ai-agents', 'rag')
_AWESOME = re.compile(r'\bawesome\b', re.IGNORECASE)


class GitHubNewReposSource(Source):
    name = 'github_new'
    doc_type = 'repo'
    source_tag = 'github'
    schedule = 'daily'          # daily so star counts (and their snapshots) stay fresh
    default_window_days = 7

    def __init__(self, topics=DEFAULT_TOPICS, per_topic: int = 50,
                 cap: int = 60, min_stars: int = 5):
        self.topics = tuple(topics)
        self.per_topic = per_topic
        self.cap = cap
        self.min_stars = min_stars
        self._token_rejected = False

    def _headers(self) -> Dict[str, str]:
        headers = {'Accept': 'application/vnd.github+json',
                   'X-GitHub-Api-Version': '2022-11-28'}
        token = get_settings().github_token
        if token and not token.startswith('ghp_your') and not self._token_rejected:
            headers['Authorization'] = f'Bearer {token}'
        return headers

    def fetch(self, since: Optional[datetime]) -> Iterable[Any]:
        """One window per week, so a backfill yields each week's strongest
        repos rather than the whole period's top 60."""
        since = since or self.default_since()
        until = datetime.now(timezone.utc)
        step = timedelta(days=7)
        start = since
        while start < until:
            end = min(start + step, until)
            if until - end < timedelta(days=1):   # fold a trailing sliver in
                end = until
            yield from self.fetch_window(start, end)
            start = end

    def _search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        for attempt in range(4):
            headers = self._headers()
            try:
                return http.get(SEARCH_URL, headers=headers, params=params, retries=1).json()
            except requests.HTTPError as e:
                response = e.response
                status = response.status_code if response is not None else None
                # A dead token must not cost us the source: fall back to the
                # unauthenticated limit (10 searches/min).
                if status == 401 and 'Authorization' in headers:
                    logger.warning("GITHUB_TOKEN rejected (401); continuing unauthenticated "
                                   "(10 searches/min). Replace the token in .env.")
                    self._token_rejected = True
                    continue
                # Search rate limit: wait for the window to reset, then retry.
                if status in (403, 429) and 'rate limit' in response.text.lower():
                    reset = int(response.headers.get('X-RateLimit-Reset', 0))
                    wait = min(max(reset - time.time(), 5), 120) if reset else 60
                    logger.warning(f"GitHub search rate limit hit; sleeping {wait:.0f}s")
                    time.sleep(wait + 1)
                    continue
                raise
        raise RuntimeError("GitHub search: gave up after repeated rate limiting")

    def fetch_window(self, since: datetime, until: datetime) -> Iterable[Any]:
        """Top repos per topic created in [since, until]; each repo once."""
        window = f'{since.date().isoformat()}..{until.date().isoformat()}'
        seen = set()
        collected = []
        for topic in self.topics:
            items = self._search({
                'q': f'topic:{topic} created:{window} stars:>={self.min_stars}',
                'sort': 'stars', 'order': 'desc',
                'per_page': min(self.per_topic, 100),
            }).get('items', [])
            logger.info(f"github topic:{topic} created:{window} -> {len(items)} repos")
            for repo in items:
                key = (repo.get('full_name') or '').lower()
                if key and key not in seen:
                    seen.add(key)
                    collected.append(repo)

        collected.sort(key=lambda r: r.get('stargazers_count', 0), reverse=True)
        yield from collected[:self.cap]

    def normalize(self, raw: Any) -> Optional[Dict[str, Any]]:
        full_name = (raw.get('full_name') or '').strip()
        if not full_name:
            return None
        description = raw.get('description') or ''
        if _AWESOME.search(raw.get('name') or '') or _AWESOME.search(description[:80]):
            return None

        owner = raw.get('owner') or {}
        return {
            'name': raw.get('name', ''),
            'full_name': full_name,
            'description': description or 'No description',
            'html_url': raw.get('html_url', ''),
            'stars': raw.get('stargazers_count', 0),
            'forks': raw.get('forks_count', 0),
            'watchers': raw.get('watchers_count', 0),
            'open_issues': raw.get('open_issues_count', 0),
            'primary_language': raw.get('language') or 'Unknown',
            'topics': list(raw.get('topics') or []),
            'owner_name': owner.get('login', 'Unknown'),
            'owner_type': owner.get('type', 'Unknown'),
            'created_at': raw.get('created_at', ''),      # ISO -> event_at
            'updated_at': raw.get('updated_at', ''),
            'pushed_at': raw.get('pushed_at', ''),
            'homepage': raw.get('homepage') or '',
            'is_fork': bool(raw.get('fork', False)),
        }

"""Every configured source, by name. `scripts/ingest.py --list` prints it."""

from typing import Dict

from src.sources.base import Source
from src.sources.github import GitHubNewReposSource
from src.sources.rss import RSSSource
from src.sources.yc_oss import YCOSSSource


def build_sources() -> Dict[str, Source]:
    sources = [
        YCOSSSource(min_batch_year=2023, ai_only=True),
        RSSSource(
            name='techcrunch_ai',
            url='https://techcrunch.com/category/artificial-intelligence/feed/',
            source_tag='techcrunch',
            max_pages=5,
        ),
        GitHubNewReposSource(),
    ]
    return {s.name: s for s in sources}

"""Every configured source, by name. `scripts/ingest.py --list` prints it."""

from typing import Dict

from src.sources.base import Source
from src.sources.github import GitHubNewReposSource
from src.sources.google_news import GoogleNewsSource
from src.sources.hn import HackerNewsSource
from src.sources.huggingface import HFModelsSource, HFPapersSource
from src.sources.rss import RSSSource
from src.sources.startupsavant import StartupSavantSource
from src.sources.yc_launches import YCLaunchesSource
from src.sources.yc_oss import YCOSSSource


def build_sources() -> Dict[str, Source]:
    sources = [
        # startups
        YCOSSSource(min_batch_year=2023, ai_only=True),
        StartupSavantSource(),
        # launches
        YCLaunchesSource(),
        HackerNewsSource(),
        # news
        RSSSource(name='techcrunch_ai',
                  url='https://techcrunch.com/category/artificial-intelligence/feed/',
                  source_tag='techcrunch', max_pages=5),
        RSSSource(name='crunchbase_news', url='https://news.crunchbase.com/feed/',
                  source_tag='crunchbase'),
        RSSSource(name='eu_startups', url='https://www.eu-startups.com/feed/',
                  source_tag='eu-startups'),
        GoogleNewsSource(),
        # open source & models
        GitHubNewReposSource(),
        HFModelsSource(),
        HFPapersSource(),
    ]
    return {s.name: s for s in sources}

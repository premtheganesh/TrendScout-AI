"""
Hugging Face Hub: trending models and the daily papers feed. Both are
free, structured and dated. The papers link research to the repositories
that implement it, which is what makes "what's hot technically" answerable.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

from src.search.document_text import normalize_whitespace
from src.sources import http
from src.sources.base import Source

logger = logging.getLogger(__name__)

MODELS_URL = 'https://huggingface.co/api/models'
PAPERS_URL = 'https://huggingface.co/api/daily_papers'

# Tags that describe packaging, not the model.
_NOISE_TAG_PREFIXES = ('license:', 'region:', 'arxiv:', 'dataset:', 'base_model:', 'doi:')
_NOISE_TAGS = {'endpoints_compatible', 'safetensors', 'eval-results', 'autotrain_compatible',
               'text-generation-inference', 'custom_code', 'has_space', 'model-index'}


def clean_tags(tags) -> list:
    out = []
    for tag in tags or []:
        if not isinstance(tag, str) or tag in _NOISE_TAGS or tag.startswith(_NOISE_TAG_PREFIXES):
            continue
        out.append(tag)
    return out


class HFModelsSource(Source):
    name = 'hf_models'
    doc_type = 'model'
    source_tag = 'huggingface'
    schedule = 'weekly'
    default_window_days = None          # "trending" is a ranking, not a window

    def __init__(self, limit: int = 50):
        self.limit = limit

    def fetch(self, since: Optional[datetime]) -> Iterable[Any]:
        yield from http.get(MODELS_URL, params={'sort': 'trendingScore', 'limit': self.limit}).json()

    def normalize(self, raw: Any) -> Optional[Dict[str, Any]]:
        hf_id = (raw.get('id') or raw.get('modelId') or '').strip()
        if not hf_id:
            return None
        organization = hf_id.split('/')[0] if '/' in hf_id else ''
        return {
            'hf_id': hf_id,
            'name': hf_id.split('/')[-1],
            'organization': organization,
            'pipeline_tag': raw.get('pipeline_tag') or '',
            'library_name': raw.get('library_name') or '',
            'tags': clean_tags(raw.get('tags')),
            'likes': raw.get('likes') or 0,
            'downloads': raw.get('downloads') or 0,
            'trending_score': raw.get('trendingScore') or 0,
            'created_at': raw.get('createdAt') or '',
            'url': f'https://huggingface.co/{hf_id}',
        }


class HFPapersSource(Source):
    name = 'hf_papers'
    doc_type = 'paper'
    source_tag = 'huggingface'
    schedule = 'daily'
    default_window_days = 7

    def __init__(self, min_upvotes: int = 10):
        # ~150 papers/week is more than the corpus needs; upvotes are the
        # community's own filter. The window is re-fetched daily, so a
        # paper that crosses the bar later still gets in.
        self.min_upvotes = min_upvotes

    def fetch(self, since: Optional[datetime]) -> Iterable[Any]:
        since = since or self.default_since()
        day = since.date()
        today = datetime.now(timezone.utc).date()
        while day <= today:
            try:
                yield from http.get(PAPERS_URL, params={'date': day.isoformat()}).json()
            except Exception as e:      # one empty/failed day must not end the run
                logger.warning(f"daily_papers {day}: {e}")
            day += timedelta(days=1)

    def normalize(self, raw: Any) -> Optional[Dict[str, Any]]:
        paper = raw.get('paper') or {}
        arxiv_id = (paper.get('id') or '').strip()
        title = normalize_whitespace(raw.get('title') or paper.get('title') or '')
        if not arxiv_id or not title:
            return None
        if (paper.get('upvotes') or 0) < self.min_upvotes:
            return None

        authors = [a.get('name') for a in (paper.get('authors') or []) if isinstance(a, dict) and a.get('name')]
        organization = paper.get('organization')
        if isinstance(organization, dict):
            organization = organization.get('name') or organization.get('fullname') or ''
        return {
            'arxiv_id': arxiv_id,
            'title': title,
            'summary': normalize_whitespace(paper.get('ai_summary') or paper.get('summary') or raw.get('summary') or ''),
            'abstract': normalize_whitespace(paper.get('summary') or raw.get('summary') or ''),
            'keywords': list(paper.get('ai_keywords') or []),
            'authors': authors[:12],
            'organization': organization or '',
            'github_repo': paper.get('githubRepo') or '',
            'github_stars': paper.get('githubStars') or 0,
            'upvotes': paper.get('upvotes') or 0,
            'num_comments': int(raw.get('numComments') or 0),
            'published_at': paper.get('publishedAt') or raw.get('publishedAt') or '',
            'submitted_at': paper.get('submittedOnDailyAt') or '',
            'url': f'https://huggingface.co/papers/{arxiv_id}',
            'arxiv_url': f'https://arxiv.org/abs/{arxiv_id}',
        }

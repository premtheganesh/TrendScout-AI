"""
Pick and order the week's documents, deterministically, before any model
is involved. Sections and their ordering rules are the editorial policy:

    launches     launch documents (YC Launches, Show/Launch HN) and startups
                 whose YC launch date falls in the week — by points, then date
    funding      articles whose title reads like a funding announcement — newest first
    open_source  repos by stars, models by trending score, papers by upvotes
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List

from src.corpus.types import COLLECTION

FUNDING_TITLE = re.compile(
    r'\b(raises?|raised|raising|funding|series [a-e]\b|seed round|pre-seed|'
    r'valuation|secures?|closes? .{0,30}round|led by|investment|invests?)\b',
    re.IGNORECASE)

SECTIONS = (
    ('launches', 'Launches'),
    ('funding', 'Funding'),
    ('open_source', 'Open source & models'),
)

CAPS = {'launches': 10, 'funding': 10, 'repo': 5, 'model': 3, 'paper': 4}

PROJECTION = {'embedding': 0, 'entities': 0}


@dataclass
class Selection:
    week: str
    start: datetime
    end: datetime
    sections: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)

    @property
    def documents(self) -> List[Dict[str, Any]]:
        return [d for docs in self.sections.values() for d in docs]

    @property
    def input_hash(self) -> str:
        """Same documents with the same text -> same hash -> no regeneration."""
        keys = sorted(f"{d['_id']}:{d.get('content_hash', '')}" for d in self.documents)
        return hashlib.sha1('\n'.join(keys).encode('utf-8')).hexdigest()


def _in_week(start: datetime, end: datetime) -> Dict[str, Any]:
    return {'event_at': {'$gte': start, '$lt': end}}


def select_week(db, week: str, start: datetime, end: datetime) -> Selection:
    docs = db[COLLECTION]
    window = _in_week(start, end)

    launches = list(docs.find({**window, 'type': 'launch'}, PROJECTION))
    launches += list(docs.find({**window, 'type': 'startup'}, PROJECTION))
    launches.sort(key=lambda d: (-(d.get('points') or 0), -(d['event_at'].timestamp()), d.get('title') or d.get('name') or ''))

    funding = [d for d in docs.find({**window, 'type': 'article'}, PROJECTION)
               if FUNDING_TITLE.search(d.get('title') or '')]
    funding.sort(key=lambda d: (-(d['event_at'].timestamp()), d.get('title') or ''))

    repos = list(docs.find({**window, 'type': 'repo'}, PROJECTION))
    repos.sort(key=lambda d: (-(d.get('stars') or 0), d.get('full_name') or ''))
    models = list(docs.find({**window, 'type': 'model'}, PROJECTION))
    models.sort(key=lambda d: (-(d.get('trending_score') or 0), d.get('hf_id') or ''))
    papers = list(docs.find({**window, 'type': 'paper'}, PROJECTION))
    papers.sort(key=lambda d: (-(d.get('upvotes') or 0), d.get('title') or ''))

    return Selection(week=week, start=start, end=end, sections={
        'launches': launches[:CAPS['launches']],
        'funding': funding[:CAPS['funding']],
        'open_source': repos[:CAPS['repo']] + models[:CAPS['model']] + papers[:CAPS['paper']],
    })

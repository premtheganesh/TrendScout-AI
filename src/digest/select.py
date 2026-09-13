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


def round_summary(r: Dict[str, Any]) -> str:
    amount = f"${r['amount_usd']:,.0f}" if r.get('amount_usd') else (
        f"{r['amount']:,.0f} {r['currency']}" if r.get('amount') and r.get('currency') else 'an undisclosed amount')
    parts = [f"{r.get('company', '?')} raised {amount}"]
    if r.get('round'):
        parts.append(f"({r['round']})")
    if r.get('lead_investors'):
        parts.append('led by ' + ', '.join(r['lead_investors'][:3]))
    if r.get('announced_at'):
        parts.append(f"on {r['announced_at'].date().isoformat()}")
    return ' '.join(parts) + '.'


def funding_for_week(db, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    """Structured rounds first (largest first), each represented by its
    primary article with the round summary attached; then any remaining
    funding-titled articles, newest first."""
    from bson import ObjectId
    docs = db[COLLECTION]
    chosen, seen = [], set()

    rounds = db['funding_rounds'].find({
        'announced_at': {'$gte': start, '$lt': end},
        'confidence': {'$in': ['high', 'medium']},
    }).sort([('amount_usd', -1), ('company', 1)])
    for r in rounds:
        for doc_id in r.get('source_doc_ids', []):
            if doc_id in seen or not ObjectId.is_valid(doc_id):
                continue
            doc = docs.find_one({'_id': ObjectId(doc_id)}, PROJECTION)
            if doc is None:
                continue
            doc['round_summary'] = round_summary(r)
            doc['round_amount_usd'] = r.get('amount_usd') or 0
            chosen.append(doc)
            seen.add(doc_id)
            break

    rest = [d for d in docs.find({**_in_week(start, end), 'type': 'article'}, PROJECTION)
            if str(d['_id']) not in seen and FUNDING_TITLE.search(d.get('title') or '')]
    rest.sort(key=lambda d: (-(d['event_at'].timestamp()), d.get('title') or ''))
    return chosen + rest


def select_week(db, week: str, start: datetime, end: datetime) -> Selection:
    docs = db[COLLECTION]
    window = _in_week(start, end)

    launches = list(docs.find({**window, 'type': 'launch'}, PROJECTION))
    launches += list(docs.find({**window, 'type': 'startup'}, PROJECTION))
    launches.sort(key=lambda d: (-(d.get('points') or 0), -(d['event_at'].timestamp()), d.get('title') or d.get('name') or ''))

    funding = funding_for_week(db, start, end)

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

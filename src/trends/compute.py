"""
Weekly topic counts and what is rising.

    topic_weekly {topic, week, doc_count, by_type}    recomputed for the trailing N weeks
    rising(week): count vs the mean of the four weeks before it

        baseline = mean(count[W-1..W-4])      (missing weeks count as 0)
        score    = (count - baseline) / sqrt(baseline + 1)
        keep     = count >= MIN_COUNT

Weeks with fewer than four prior weeks of any data are flagged
`insufficient_history` rather than dressed up as trends. Velocity for
repos and models comes from metric_snapshots: stars/likes now minus the
oldest snapshot inside the window.
"""

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.corpus.types import COLLECTION
from src.digest.weeks import week_bounds, week_id
from src.pipeline.snapshots import SNAPSHOTS
from src.trends.topics import document_topics

TOPIC_WEEKLY = 'topic_weekly'
MIN_COUNT = 3
BASELINE_WEEKS = 4
DEFAULT_TRAILING_WEEKS = 8

VELOCITY_METRIC = {'repo': 'stars', 'model': 'likes', 'paper': 'upvotes', 'launch': 'points'}
VELOCITY_FLOOR = {'repo': 20, 'model': 20, 'paper': 5, 'launch': 5}


def previous_weeks(week: str, n: int) -> List[str]:
    start, _ = week_bounds(week)
    return [week_id((start - timedelta(days=7 * i)).date()) for i in range(1, n + 1)]


def compute_topic_weekly(db, week: str, trailing_weeks: int = DEFAULT_TRAILING_WEEKS) -> Dict[str, int]:
    """Recount topics for `week` and the weeks before it. Idempotent: the
    rows for those weeks are replaced."""
    weeks = [week] + previous_weeks(week, trailing_weeks - 1)
    earliest, _ = week_bounds(weeks[-1])
    _, latest = week_bounds(week)

    counts: Dict[tuple, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for doc in db[COLLECTION].find({'event_at': {'$gte': earliest, '$lt': latest}},
                                   {'type': 1, 'event_at': 1, 'topics': 1, 'tags': 1,
                                    'pipeline_tag': 1, 'keywords': 1, 'industries': 1, 'categories': 1}):
        w = week_id(doc['event_at'].date())
        for topic in document_topics(doc):
            counts[(topic, w)][doc.get('type', '')] += 1

    rows = [{'topic': topic, 'week': w, 'doc_count': sum(by_type.values()),
             'by_type': dict(by_type)} for (topic, w), by_type in counts.items()]
    db[TOPIC_WEEKLY].delete_many({'week': {'$in': weeks}})
    if rows:
        db[TOPIC_WEEKLY].insert_many(rows)
    db[TOPIC_WEEKLY].create_index([('week', 1), ('doc_count', -1)])
    db[TOPIC_WEEKLY].create_index([('topic', 1), ('week', 1)])
    return {'weeks': len(weeks), 'rows': len(rows)}


def rising_topics(db, week: str, limit: int = 20) -> Dict[str, Any]:
    baseline_weeks = previous_weeks(week, BASELINE_WEEKS)
    rows = list(db[TOPIC_WEEKLY].find({'week': {'$in': [week] + baseline_weeks}}))

    weeks_with_data = {r['week'] for r in rows if r['week'] != week}
    history = len(weeks_with_data)

    current: Dict[str, Dict] = {r['topic']: r for r in rows if r['week'] == week}
    past: Dict[str, List[int]] = defaultdict(list)
    for r in rows:
        if r['week'] != week:
            past[r['topic']].append(r['doc_count'])

    scored = []
    for topic, row in current.items():
        count = row['doc_count']
        if count < MIN_COUNT:
            continue
        baseline = sum(past.get(topic, [])) / BASELINE_WEEKS
        score = (count - baseline) / math.sqrt(baseline + 1)
        scored.append({'topic': topic, 'count': count, 'baseline': round(baseline, 2),
                       'score': round(score, 3), 'by_type': row.get('by_type', {})})
    scored.sort(key=lambda r: (-r['score'], -r['count'], r['topic']))

    top = sorted(current.values(), key=lambda r: (-r['doc_count'], r['topic']))[:limit]
    return {
        'week': week,
        'insufficient_history': history < BASELINE_WEEKS,
        'history_weeks': history,
        'rising': scored[:limit],
        'top': [{'topic': r['topic'], 'count': r['doc_count'], 'by_type': r.get('by_type', {})} for r in top],
    }


def velocity(db, doc_type: str = 'repo', days: int = 7, limit: int = 20,
             now: Optional[datetime] = None) -> Dict[str, Any]:
    """Metric gained over the window, from snapshots. Needs at least two
    snapshots on different days per document to say anything."""
    metric = VELOCITY_METRIC.get(doc_type)
    if not metric:
        raise ValueError(f'no velocity metric for {doc_type!r}')
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).date().isoformat()

    by_doc: Dict[str, List[Dict]] = defaultdict(list)
    for snap in db[SNAPSHOTS].find({'type': doc_type, 'date': {'$gte': since}},
                                   {'doc_id': 1, 'date': 1, metric: 1}).sort('date', 1):
        if snap.get(metric) is not None:
            by_doc[snap['doc_id']].append(snap)

    rows = []
    for doc_id, snaps in by_doc.items():
        first, last = snaps[0], snaps[-1]
        if first['date'] == last['date']:
            continue
        gained = (last[metric] or 0) - (first[metric] or 0)
        if gained < VELOCITY_FLOOR.get(doc_type, 0):
            continue
        rows.append({'doc_id': doc_id, 'gained': gained, 'now': last[metric],
                     'from_date': first['date'], 'to_date': last['date']})
    rows.sort(key=lambda r: (-r['gained'], r['doc_id']))

    documents_with_history = len([1 for s in by_doc.values() if s[0]['date'] != s[-1]['date']])
    return {
        'type': doc_type, 'metric': metric, 'days': days,
        'insufficient_history': documents_with_history == 0,
        'documents_with_history': documents_with_history,
        'items': rows[:limit],
    }


def compute_trends(db, week: Optional[str] = None) -> Dict[str, Any]:
    week = week or week_id(datetime.now(timezone.utc).date())
    stats = compute_topic_weekly(db, week)
    summary = rising_topics(db, week, limit=10)
    return {'week': week, **stats, 'rising': len(summary['rising']),
            'insufficient_history': summary['insufficient_history']}

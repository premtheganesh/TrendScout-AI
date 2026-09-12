"""
Daily metric snapshots for the trends feature.

Star and fork counts are overwritten on every ingest; this is the only
place their history survives. One row per (document, day), upserted, so
re-running the stage on the same day is a no-op. History cannot be
backfilled — that is why this stage ships before the trends UI.
"""

from datetime import date, datetime, timezone
from typing import Dict, Optional

from src.corpus.types import COLLECTION

SNAPSHOTS = 'metric_snapshots'

METRICS = {
    'repo': ('stars', 'forks', 'watchers', 'open_issues'),
    'model': ('likes', 'downloads', 'trending_score'),
    'launch': ('points', 'num_comments'),
    'paper': ('upvotes', 'github_stars'),
}


def ensure_snapshot_indexes(db) -> None:
    db[SNAPSHOTS].create_index([('doc_id', 1), ('date', 1)], unique=True)
    db[SNAPSHOTS].create_index([('type', 1), ('date', -1)])


def capture(db, today: Optional[date] = None) -> Dict[str, int]:
    ensure_snapshot_indexes(db)
    today = today or datetime.now(timezone.utc).date()
    day = today.isoformat()
    captured_at = datetime.now(timezone.utc)
    counts = {}
    for doc_type, fields in METRICS.items():
        n = 0
        for doc in db[COLLECTION].find({'type': doc_type}, {f: 1 for f in fields}):
            metrics = {f: doc.get(f) for f in fields if doc.get(f) is not None}
            if not metrics:
                continue
            db[SNAPSHOTS].update_one(
                {'doc_id': str(doc['_id']), 'date': day},
                {'$set': {**metrics, 'type': doc_type, 'captured_at': captured_at}},
                upsert=True,
            )
            n += 1
        if n:
            counts[doc_type] = n
    return counts

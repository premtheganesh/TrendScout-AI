"""
Recount weekly topics and print what is rising.

    python scripts/compute_trends.py                 # current ISO week
    python scripts/compute_trends.py --week 2026-W36

Idempotent: rows for the recomputed weeks are replaced.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse

from src.database.mongo_client import MongoDBClient
from src.digest.weeks import resolve_week
from src.trends.compute import compute_topic_weekly, rising_topics, velocity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--week', default='current')
    args = parser.parse_args()

    week = resolve_week(args.week)
    mongo = MongoDBClient()
    stats = compute_topic_weekly(mongo.db, week)
    summary = rising_topics(mongo.db, week, limit=15)

    print("=" * 72)
    print(f"TRENDS {week}   recounted {stats['weeks']} weeks, {stats['rows']} topic-week rows")
    print("=" * 72)
    if summary['insufficient_history']:
        print(f"  insufficient history: only {summary['history_weeks']} of {4} prior weeks have data — "
              "scores below are indicative, not trends")
    print(f"\n  {'rising topic':<28}{'this wk':>8}{'baseline':>10}{'score':>8}")
    for r in summary['rising']:
        print(f"  {r['topic']:<28}{r['count']:>8}{r['baseline']:>10}{r['score']:>8}")
    print(f"\n  {'most mentioned':<28}{'this wk':>8}")
    for r in summary['top'][:10]:
        print(f"  {r['topic']:<28}{r['count']:>8}")

    for doc_type in ('repo', 'model'):
        v = velocity(mongo.db, doc_type)
        label = 'insufficient history' if v['insufficient_history'] else f"{len(v['items'])} movers"
        print(f"\n  {doc_type} velocity ({v['metric']}, {v['days']}d): {label}")
        for r in v['items'][:5]:
            print(f"    +{r['gained']:<7} {r['doc_id']}  ({r['from_date']} → {r['to_date']})")
    mongo.close()


if __name__ == '__main__':
    main()

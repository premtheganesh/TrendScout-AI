"""
Fetch every configured source (or one) into MongoDB.

    python scripts/ingest.py                              # all sources, default windows
    python scripts/ingest.py --source techcrunch_ai       # one source
    python scripts/ingest.py --source github_new --since 2026-07-18   # backfill
    python scripts/ingest.py --dry-run                    # fetch + normalize, write nothing
    python scripts/ingest.py --list

Each run writes one row per source to the `runs` collection. Re-running
a source over the same window reports new=0 changed=0: upserts are keyed
on doc_key. Afterwards: python scripts/run_pipeline.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
import logging
from datetime import datetime, timedelta, timezone

from src.corpus.dates import parse_datetime
from src.corpus.schema import ensure_indexes
from src.database.mongo_client import MongoDBClient
from src.ingest.runner import format_run, run_source
from src.sources.registry import build_sources

logging.basicConfig(level=logging.WARNING, format='%(levelname)s  %(message)s')
logging.getLogger('src.sources').setLevel(logging.INFO)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', action='append', help='run only this source (repeatable)')
    parser.add_argument('--schedule', choices=['daily', 'weekly', 'monthly'],
                        help='run only sources with this schedule')
    parser.add_argument('--since', help='ISO date; overrides the source default window')
    parser.add_argument('--days', type=int, help='window in days; overrides the default')
    parser.add_argument('--max-pages', type=int,
                        help='for RSS sources: pages to walk (backfills need more than the default)')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()

    sources = build_sources()
    if args.list:
        for s in sources.values():
            window = f'{s.default_window_days}d' if s.default_window_days else 'all'
            print(f"  {s.name:<16} type={s.doc_type:<8} schedule={s.schedule:<8} window={window}")
        return

    selected = list(sources.values())
    if args.schedule:
        selected = [s for s in selected if s.schedule == args.schedule]
    if args.source:
        unknown = [n for n in args.source if n not in sources]
        if unknown:
            raise SystemExit(f"unknown source(s): {unknown}; try --list")
        selected = [sources[n] for n in args.source]

    since = None
    if args.since:
        since = parse_datetime(args.since)
        if since is None:
            raise SystemExit(f"could not parse --since {args.since!r}")
    elif args.days:
        since = datetime.now(timezone.utc) - timedelta(days=args.days)

    if args.max_pages:
        for s in selected:
            if hasattr(s, 'max_pages'):
                s.max_pages = args.max_pages

    mongo = MongoDBClient()
    ensure_indexes(mongo.db)
    print("=" * 96)
    print(f"INGEST  database={mongo.db_name}"
          + (f"  since={since.date()}" if since else "")
          + ("  [DRY RUN]" if args.dry_run else ""))
    print("=" * 96)

    records = []
    for source in selected:
        record = run_source(source, mongo.db, since=since, dry_run=args.dry_run)
        print(format_run(record))
        records.append(record)

    total_new = sum(r['new'] for r in records)
    failed = [r['source'] for r in records if r['status'] != 'ok']
    print("-" * 96)
    print(f"  {total_new} new documents"
          + (f"; FAILED: {', '.join(failed)}" if failed else ""))
    mongo.close()
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()

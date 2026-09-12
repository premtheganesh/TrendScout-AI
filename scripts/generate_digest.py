"""
Write (or refresh) the weekly digest.

    python scripts/generate_digest.py                   # current ISO week
    python scripts/generate_digest.py --week previous   # last completed week (what the scheduler runs)
    python scripts/generate_digest.py --week 2026-W37 --force

Runs no model at all when the week's inputs have not changed since the
stored digest was built.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
import logging

from src.database.mongo_client import MongoDBClient
from src.digest.generate import generate_week
from src.digest.weeks import resolve_week, week_bounds
from src.llm.groq_client import GroqClient

logging.basicConfig(level=logging.WARNING)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--week', default='current', help="'current', 'previous' or YYYY-Www")
    parser.add_argument('--force', action='store_true', help='regenerate even if inputs are unchanged')
    args = parser.parse_args()

    week = resolve_week(args.week)
    start, end = week_bounds(week)
    mongo = MongoDBClient()
    llm = GroqClient()

    print("=" * 72)
    print(f"DIGEST {week}  ({start.date()} → {end.date()})  database={mongo.db_name}  model={llm.model}")
    print("=" * 72)

    digest, status = generate_week(mongo.db, week, start, end, llm, llm.model, force=args.force)
    print(f"  status: {status}")
    if digest:
        print(f"  inputs: {digest['counts']}   warnings: {digest['warnings']}")
        for section in digest['sections']:
            print(f"\n## {section['title']}  ({section['bullets']} bullets, {len(section['sources'])} sources)")
            print(section['markdown'] or '  (nothing this week)')
    mongo.close()
    sys.exit(0 if status != 'empty' else 1)


if __name__ == '__main__':
    main()

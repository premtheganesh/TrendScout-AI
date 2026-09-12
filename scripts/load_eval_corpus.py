"""
Load the frozen evaluation corpus into a separate database.

This is what makes the README's retrieval numbers reproducible from a fresh
clone: the live database keeps growing, but the evaluation always runs
against the same 210 documents.

    MONGODB_DB=trendscout_eval INDEX_DIR=data/eval_index \
        python scripts/load_eval_corpus.py --build-indexes
    MONGODB_DB=trendscout_eval INDEX_DIR=data/eval_index \
        python scripts/evaluate_retrieval.py

It refuses to load into the live database (`trendscout_ai`) unless --force
is given, because it drops the target collections first.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
import subprocess
from collections import defaultdict

from bson import json_util

from src.config import PROJECT_ROOT, get_settings
from src.corpus.schema import ensure_indexes
from src.database.mongo_client import MongoDBClient

LIVE_DB = 'trendscout_ai'
DEFAULT_CORPUS = os.path.join(PROJECT_ROOT, 'data', 'eval', 'corpus_v2.jsonl')


def load(mongo, path: str) -> dict:
    grouped = defaultdict(list)
    with open(path, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                record = json_util.loads(line)
                grouped[record['collection']].append(record['doc'])

    counts = {}
    for collection, docs in grouped.items():
        mongo.db[collection].drop()
        mongo.db[collection].insert_many(docs, ordered=True)
        counts[collection] = len(docs)

    ensure_indexes(mongo.db)

    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', default=DEFAULT_CORPUS)
    parser.add_argument('--force', action='store_true',
                        help=f'allow loading into the live database ({LIVE_DB})')
    parser.add_argument('--build-indexes', action='store_true',
                        help='run build_indexes.py afterwards, into INDEX_DIR')
    args = parser.parse_args()

    settings = get_settings()
    if settings.mongodb_db == LIVE_DB and not args.force:
        raise SystemExit(
            f"Refusing to overwrite the live database '{LIVE_DB}'. "
            "Set MONGODB_DB=trendscout_eval (or pass --force)."
        )

    mongo = MongoDBClient()
    print(f"Loading {args.corpus}\n  -> database '{mongo.db_name}'")
    counts = load(mongo, args.corpus)
    mongo.close()

    for collection, n in counts.items():
        print(f"  {collection:<20} {n:>5}")
    print(f"  {'total':<20} {sum(counts.values()):>5}")

    if args.build_indexes:
        print(f"\nBuilding indexes into {settings.index_dir} ...")
        subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), 'build_indexes.py')],
            check=True,
        )


if __name__ == '__main__':
    main()

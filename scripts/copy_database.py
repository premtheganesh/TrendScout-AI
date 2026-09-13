"""
Copy the corpus to another MongoDB (e.g. Atlas) with plain pymongo — no
mongodump needed. Embeddings are copied as they are (binary), so the
target API can rebuild its indexes at boot.

    python scripts/copy_database.py --to "mongodb+srv://user:pass@cluster.mongodb.net/" [--db trendscout_ai] [--drop]

Copies: documents, canonical_entities, funding_rounds, companies, digests,
metric_snapshots, topic_weekly, runs. Recreates the corpus indexes.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse

from pymongo import MongoClient

from src.corpus.schema import ensure_indexes
from src.database.mongo_client import MongoDBClient
from src.pipeline.snapshots import ensure_snapshot_indexes

COLLECTIONS = ('documents', 'canonical_entities', 'funding_rounds', 'companies',
               'digests', 'metric_snapshots', 'topic_weekly', 'runs')
BATCH = 500


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--to', required=True, help='target MongoDB URI')
    parser.add_argument('--db', default=None, help='target database name (default: same as source)')
    parser.add_argument('--drop', action='store_true', help='drop target collections first')
    args = parser.parse_args()

    source = MongoDBClient()
    target_client = MongoClient(args.to, tz_aware=True)
    target = target_client[args.db or source.db_name]
    target_client.admin.command('ping')
    print(f"{source.db_name} (local) -> {target.name} ({target_client.address[0] if target_client.address else 'remote'})")

    for name in COLLECTIONS:
        src = source.db[name]
        dst = target[name]
        if args.drop:
            dst.drop()
        total, batch = 0, []
        for doc in src.find():
            batch.append(doc)
            if len(batch) >= BATCH:
                dst.insert_many(batch, ordered=False)
                total += len(batch)
                batch = []
        if batch:
            dst.insert_many(batch, ordered=False)
            total += len(batch)
        print(f"  {name:<20} {total:>6} copied  (target now {dst.count_documents({})})")

    ensure_indexes(target)
    ensure_snapshot_indexes(target)
    target['funding_rounds'].create_index('company_key')
    target['funding_rounds'].create_index([('amount_usd', -1)])
    target['companies'].create_index([('funding_total_usd', -1)])
    target['topic_weekly'].create_index([('week', 1), ('doc_count', -1)])
    print("  indexes ensured")
    source.close()
    target_client.close()


if __name__ == '__main__':
    main()

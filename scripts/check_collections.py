"""Quick look at what MongoDB holds.   python scripts/check_collections.py"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.corpus.types import COLLECTION, TYPE_NAMES
from src.database.mongo_client import MongoDBClient


def main():
    mongo = MongoDBClient()
    db = mongo.db
    print(f"database: {mongo.db_name}")
    print(f"collections: {', '.join(sorted(db.list_collection_names()))}\n")

    docs = db[COLLECTION]
    total = docs.count_documents({})
    print(f"{COLLECTION}: {total}")
    for doc_type in TYPE_NAMES:
        n = docs.count_documents({'type': doc_type})
        dated = docs.count_documents({'type': doc_type, 'event_at': {'$ne': None}})
        embedded = docs.count_documents({'type': doc_type, 'embedding': {'$exists': True}})
        print(f"  {doc_type:<10} {n:>5}   event_at {dated:>5}   embedded {embedded:>5}")

    entities = db.canonical_entities.count_documents({})
    linking = db.canonical_entities.count_documents({'document_count': {'$gt': 1}})
    print(f"\ncanonical_entities: {entities} ({linking} link more than one document)")
    mongo.close()


if __name__ == '__main__':
    main()

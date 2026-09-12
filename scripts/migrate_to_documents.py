"""
One-time migration: three per-type collections -> one `documents` collection.

    python scripts/migrate_to_documents.py            # dry run: report only
    python scripts/migrate_to_documents.py --apply    # write `documents`
    python scripts/migrate_to_documents.py --apply --drop-legacy

Every document keeps its `_id`, so canonical_entities links, Neo4j doc_ids
and the evaluation labels stay valid. Each gets `type`, `doc_key`,
`event_at`, `first_seen_at`, `last_seen_at` and `content_hash`.
canonical_entities.mentioned_in entries are rewritten from
{doc_id, collection} to {doc_id, type}.

Refuses to run against a non-empty `documents` collection unless --force.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
from collections import Counter

from src.corpus.dates import event_at_for, first_seen_for
from src.corpus.identity import content_hash, doc_key
from src.corpus.schema import ensure_indexes
from src.corpus.types import COLLECTION, LEGACY_COLLECTIONS, normalize_type
from src.database.mongo_client import MongoDBClient


def convert(doc: dict, doc_type: str) -> dict:
    new = dict(doc)
    new['type'] = doc_type
    new['source'] = (doc.get('source') or 'manual').lower()
    new['doc_key'] = doc_key(new, doc_type)
    new['event_at'] = event_at_for(new, doc_type)
    new['first_seen_at'] = first_seen_for(new)
    new['last_seen_at'] = new['first_seen_at']
    new['content_hash'] = content_hash(new, doc_type)
    return new


def plan(mongo) -> list:
    converted, problems = [], []
    for legacy, doc_type in LEGACY_COLLECTIONS.items():
        for doc in mongo.db[legacy].find():
            try:
                converted.append(convert(doc, doc_type))
            except ValueError as e:
                problems.append((legacy, str(doc['_id']), str(e)))

    keys = Counter(d['doc_key'] for d in converted)
    for key, n in keys.items():
        if n > 1:
            ids = [str(d['_id']) for d in converted if d['doc_key'] == key]
            problems.append(('doc_key', key, f'{n} documents share it: {ids}'))

    if problems:
        print("\n  PROBLEMS — nothing written:")
        for where, what, why in problems:
            print(f"    {where}: {what}: {why}")
        raise SystemExit(1)

    return converted


def report(converted: list) -> None:
    by_type = Counter(d['type'] for d in converted)
    dated = Counter(d['type'] for d in converted if d['event_at'])
    print(f"\n  {len(converted)} documents would be written to `{COLLECTION}`:")
    for doc_type, n in by_type.items():
        print(f"    {doc_type:<10} {n:>4}   event_at set on {dated[doc_type]:>3}")
    print("\n  sample keys:")
    seen = set()
    for d in converted:
        if d['type'] not in seen:
            seen.add(d['type'])
            print(f"    {d['doc_key']}")


def rewrite_entity_links(mongo) -> int:
    changed = 0
    for entity in mongo.db.canonical_entities.find():
        mentions = entity.get('mentioned_in')
        if not isinstance(mentions, list):
            continue
        rewritten, touched = [], False
        for m in mentions:
            if not isinstance(m, dict):
                continue
            if 'type' not in m and 'collection' in m:
                m = {'doc_id': m['doc_id'], 'type': normalize_type(m['collection']) or ''}
                touched = True
            rewritten.append(m)
        if touched:
            mongo.db.canonical_entities.update_one(
                {'_id': entity['_id']}, {'$set': {'mentioned_in': rewritten}})
            changed += 1
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--apply', action='store_true', help='write the migration')
    parser.add_argument('--force', action='store_true',
                        help=f'overwrite a non-empty `{COLLECTION}` collection')
    parser.add_argument('--drop-legacy', action='store_true',
                        help='drop the per-type collections after a verified migration')
    args = parser.parse_args()

    mongo = MongoDBClient()
    print("=" * 72)
    print(f"MIGRATE TO `{COLLECTION}`  database={mongo.db_name}"
          + ("" if args.apply else "  [DRY RUN]"))
    print("=" * 72)

    existing = mongo.db[COLLECTION].count_documents({})
    if existing and args.apply and not args.force:
        raise SystemExit(
            f"`{COLLECTION}` already holds {existing} documents. "
            "Pass --force to replace them.")

    converted = plan(mongo)
    report(converted)

    if not args.apply:
        print("\n  Dry run. Re-run with --apply to write.")
        mongo.close()
        return

    if existing:
        mongo.db[COLLECTION].drop()
    mongo.db[COLLECTION].insert_many(converted, ordered=True)
    ensure_indexes(mongo.db)
    written = mongo.db[COLLECTION].count_documents({})
    print(f"\n  Wrote {written} documents, indexes ensured")

    links = rewrite_entity_links(mongo)
    print(f"  Rewrote mentioned_in on {links} canonical entities")

    # Verify before touching the legacy collections.
    legacy_total = sum(mongo.db[c].count_documents({}) for c in LEGACY_COLLECTIONS)
    if written != legacy_total:
        raise SystemExit(f"  MISMATCH: {written} written vs {legacy_total} legacy — "
                         "legacy collections kept")
    dangling = 0
    ids = {str(d['_id']) for d in mongo.db[COLLECTION].find({}, {'_id': 1})}
    for entity in mongo.db.canonical_entities.find({}, {'mentioned_in': 1}):
        for m in entity.get('mentioned_in') or []:
            if isinstance(m, dict) and m.get('doc_id') not in ids:
                dangling += 1
    print(f"  Verified: counts match, {dangling} dangling entity links")

    if args.drop_legacy:
        if dangling:
            raise SystemExit("  Dangling links present — legacy collections kept")
        for legacy in LEGACY_COLLECTIONS:
            mongo.db[legacy].drop()
        print(f"  Dropped {', '.join(LEGACY_COLLECTIONS)}")
    else:
        print("  Legacy collections kept (pass --drop-legacy to remove them)")

    print("\n  Next: python scripts/build_indexes.py")
    mongo.close()


if __name__ == '__main__':
    main()

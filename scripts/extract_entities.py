"""
Extract entities from every document and rebuild the canonical entity index.

Run:
    python scripts/extract_entities.py
    python scripts/extract_entities.py --dry-run
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import re
import argparse
import logging
from collections import defaultdict
from datetime import datetime, timezone

from src.database.mongo_client import MongoDBClient
from src.extractors.entity_extractor import EntityExtractor
from src.search.document_text import document_text

logging.basicConfig(level=logging.WARNING, format='%(levelname)s  %(message)s')
logger = logging.getLogger(__name__)

# The extractor logs one line per document, which buries the report.
logging.getLogger('src.extractors.entity_extractor').setLevel(logging.WARNING)

COLLECTIONS = ('startups', 'articles', 'github_repos')

# Quantity labels make bad graph nodes: every document mentioning "one"
# becomes a neighbour of every other.
EXCLUDED_TYPES = {
    'CARDINAL', 'ORDINAL', 'QUANTITY', 'DATE', 'TIME', 'PERCENT', 'MONEY',
}

# Generic terms spaCy frequently mislabels as organisations in this corpus.
# They are real words but carry no discriminative power — every second
# startup here "is an AI company".
GENERIC_ENTITIES = {
    'ai', 'the ai', 'llm', 'llms', 'api', 'apis', 'saas', 'ml', 'nlp',
    'app', 'apps', 'inc', 'inc.', 'llc', 'ltd', 'co', 'corp', 'company',
    'startup', 'startups', 'platform', 'technology', 'technologies',
    'software', 'data', 'cloud', 'open', 'first', 'one', 'new', 'series',
}

_LEADING_ARTICLE = re.compile(r'^(the|a|an)\s+', re.IGNORECASE)
_WHITESPACE = re.compile(r'\s+')


def normalize_entity(text: str) -> str:
    """Collapse whitespace, drop a leading article and trailing possessive."""
    text = _WHITESPACE.sub(' ', text).strip()
    text = _LEADING_ARTICLE.sub('', text)
    text = re.sub(r"['’]s$", '', text)
    return text.strip(" .,;:-–—\"'()[]")


def is_useful(text: str, entity_type: str) -> bool:
    """Reject entities that would only add noise to the graph."""
    if entity_type in EXCLUDED_TYPES:
        return False
    if len(text) < 2 or len(text) > 60:
        return False
    if text.casefold() in GENERIC_ENTITIES:
        return False
    if not any(ch.isalpha() for ch in text):
        return False          # pure numbers / punctuation
    if text.isdigit():
        return False
    return True


def extract_for_documents(extractor, mongo, dry_run=False):
    """Run NER over every document and store the result on it."""
    print("\n" + "=" * 72)
    print("ENTITY EXTRACTION  (spaCy en_core_web_sm)")
    print("=" * 72)

    now = datetime.now(timezone.utc).isoformat()
    stats = {}

    for collection in COLLECTIONS:
        docs = list(mongo.db[collection].find())
        with_entities = 0
        total_entities = 0

        for doc in docs:
            text = document_text(doc, collection)
            if not text.strip():
                continue

            raw = extractor.extract_entities(text)

            entities = []
            for ent in raw:
                name = normalize_entity(ent['entity_text'])
                if not is_useful(name, ent['entity_type']):
                    continue
                entities.append({
                    'entity_text': name,
                    'entity_type': ent['entity_type'],
                    'count': ent['count'],
                })

            if entities:
                with_entities += 1
                total_entities += len(entities)

            if not dry_run:
                mongo.db[collection].update_one(
                    {'_id': doc['_id']},
                    {'$set': {
                        'entities': entities,
                        'entities_extracted_at': now,
                    }}
                )

        stats[collection] = (with_entities, len(docs), total_entities)
        print(f"  {collection:<15} {with_entities:>3}/{len(docs)} documents "
              f"produced entities  ({total_entities} total)")

    return stats


def build_canonical_index(mongo, dry_run=False):
    print("\n" + "=" * 72)
    print("CANONICAL ENTITY INDEX")
    print("=" * 72)

    # Keep the most common surface form as the display name.
    grouped = defaultdict(lambda: {
        'surface_forms': defaultdict(int),
        'entity_type': None,
        'mention_count': 0,
        'mentioned_in': [],
        'seen_docs': set(),
    })

    for collection in COLLECTIONS:
        for doc in mongo.db[collection].find({'entities': {'$exists': True}}):
            doc_id = str(doc['_id'])
            entities = doc.get('entities') or []
            if isinstance(entities, str):
                continue

            for ent in entities:
                name = ent.get('entity_text')
                etype = ent.get('entity_type')
                if not name or not etype:
                    continue

                key = (name.casefold(), etype)
                bucket = grouped[key]
                bucket['surface_forms'][name] += 1
                bucket['entity_type'] = etype
                bucket['mention_count'] += ent.get('count', 1)

                # One edge per document, however often it is mentioned.
                if doc_id not in bucket['seen_docs']:
                    bucket['seen_docs'].add(doc_id)
                    bucket['mentioned_in'].append({
                        'doc_id': doc_id,
                        'collection': collection,
                    })

    now = datetime.now(timezone.utc).isoformat()
    records = []
    for (_, etype), bucket in grouped.items():
        display = max(bucket['surface_forms'].items(), key=lambda kv: kv[1])[0]
        records.append({
            'entity_text': display,
            'entity_type': etype,
            'mention_count': bucket['mention_count'],
            'document_count': len(bucket['mentioned_in']),
            'mentioned_in': bucket['mentioned_in'],
            'created_at': now,
        })

    records.sort(key=lambda r: r['document_count'], reverse=True)

    connecting = [r for r in records if r['document_count'] > 1]
    print(f"  {len(records)} canonical entities")
    print(f"  {len(connecting)} appear in more than one document "
          f"(these are the ones that create graph edges)")

    if not dry_run:
        mongo.db.canonical_entities.delete_many({})
        if records:
            mongo.db.canonical_entities.insert_many(records)
        mongo.db.canonical_entities.create_index('entity_text')
        mongo.db.canonical_entities.create_index('mentioned_in.doc_id')
        print(f"  Wrote {len(records)} entities to canonical_entities")

    print("\n  Top connecting entities:")
    for r in connecting[:12]:
        print(f"    {r['document_count']:>2} docs  {r['entity_type']:<9} {r['entity_text']}")

    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true',
                        help='report what would change without writing')
    args = parser.parse_args()

    print("=" * 72)
    print("TRENDSCOUT AI — ENTITY PIPELINE" + ("  [DRY RUN]" if args.dry_run else ""))
    print("=" * 72)

    mongo = MongoDBClient()
    extractor = EntityExtractor()

    extract_for_documents(extractor, mongo, dry_run=args.dry_run)
    build_canonical_index(mongo, dry_run=args.dry_run)

    print("\n" + "=" * 72)
    print("Done. Next: python scripts/build_indexes.py")
    print("=" * 72)
    mongo.close()


if __name__ == "__main__":
    main()

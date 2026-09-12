"""
Named-entity extraction for stale documents, and the canonical entity index.

The canonical index is a pure aggregation over stored per-document
entities, rebuilt in full (it is cheap) into a temporary collection and
swapped in atomically, so the API never reads a half-written index.
"""

import re
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List

from src.corpus.schema import ensure_indexes
from src.corpus.types import COLLECTION
from src.search.document_text import document_text

logger = logging.getLogger(__name__)

# Quantity labels make bad graph nodes: every document mentioning "one"
# becomes a neighbour of every other.
EXCLUDED_TYPES = {
    'CARDINAL', 'ORDINAL', 'QUANTITY', 'DATE', 'TIME', 'PERCENT', 'MONEY',
}

# Generic terms spaCy frequently mislabels as organisations in this corpus.
GENERIC_ENTITIES = {
    'ai', 'the ai', 'llm', 'llms', 'api', 'apis', 'saas', 'ml', 'nlp',
    'app', 'apps', 'inc', 'inc.', 'llc', 'ltd', 'co', 'corp', 'company',
    'startup', 'startups', 'platform', 'technology', 'technologies',
    'software', 'data', 'cloud', 'open', 'first', 'one', 'new', 'series',
}

_LEADING_ARTICLE = re.compile(r'^(the|a|an)\s+', re.IGNORECASE)
_WHITESPACE = re.compile(r'\s+')

STALE = {'$or': [
    {'entities_hash': {'$exists': False}},
    {'$expr': {'$ne': ['$entities_hash', '$content_hash']}},
]}


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
        return False
    return True


def clean_entities(raw: List[Dict]) -> List[Dict]:
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
    return entities


def extract_stale(db, extractor, force: bool = False) -> int:
    """Run NER on documents whose text changed since their entities were
    computed. Returns how many were processed."""
    query = {} if force else STALE
    now = datetime.now(timezone.utc).isoformat()
    processed = 0
    for doc in db[COLLECTION].find(query):
        text = document_text(doc, doc.get('type'))
        entities = clean_entities(extractor.extract_entities(text)) if text.strip() else []
        db[COLLECTION].update_one({'_id': doc['_id']}, {'$set': {
            'entities': entities,
            'entities_hash': doc.get('content_hash'),
            'entities_extracted_at': now,
        }})
        processed += 1
    return processed


def rebuild_canonical_index(db) -> Dict[str, int]:
    """Aggregate per-document entities into canonical_entities, atomically."""
    grouped = defaultdict(lambda: {
        'surface_forms': defaultdict(int),
        'entity_type': None,
        'mention_count': 0,
        'mentioned_in': [],
        'seen_docs': set(),
    })

    for doc in db[COLLECTION].find({'entities': {'$exists': True}},
                                   {'entities': 1, 'type': 1}):
        doc_id = str(doc['_id'])
        entities = doc.get('entities') or []
        if isinstance(entities, str):
            continue
        for ent in entities:
            name, etype = ent.get('entity_text'), ent.get('entity_type')
            if not name or not etype:
                continue
            bucket = grouped[(name.casefold(), etype)]
            bucket['surface_forms'][name] += 1
            bucket['entity_type'] = etype
            bucket['mention_count'] += ent.get('count', 1)
            if doc_id not in bucket['seen_docs']:
                bucket['seen_docs'].add(doc_id)
                bucket['mentioned_in'].append({'doc_id': doc_id, 'type': doc.get('type', '')})

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

    tmp = 'canonical_entities_building'
    db[tmp].drop()
    if records:
        db[tmp].insert_many(records)
    db[tmp].rename('canonical_entities', dropTarget=True)
    ensure_indexes(db)

    linking = sum(1 for r in records if r['document_count'] > 1)
    return {'entities': len(records), 'linking': linking}

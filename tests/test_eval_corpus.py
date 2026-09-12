"""
Integrity of the committed evaluation snapshot. No database: this reads the
file, so a broken or partial re-export fails here before it reaches the
evaluation.
"""

import os
from collections import Counter

import pytest
from bson import json_util

from src.config import PROJECT_ROOT

CORPUS = os.path.join(PROJECT_ROOT, 'data', 'eval', 'corpus_v2.jsonl')

EXPECTED = {'documents': 210, 'canonical_entities': 647}
EXPECTED_TYPES = {'startup': 140, 'article': 20, 'repo': 50}


@pytest.fixture(scope='module')
def records():
    with open(CORPUS, encoding='utf-8') as f:
        return [json_util.loads(line) for line in f if line.strip()]


def test_snapshot_has_the_frozen_document_counts(records):
    assert Counter(r['collection'] for r in records) == EXPECTED


def test_snapshot_has_the_frozen_type_counts(records):
    assert Counter(r['doc']['type'] for r in records
                   if r['collection'] == 'documents') == EXPECTED_TYPES


def test_every_document_has_a_doc_key_and_hash(records):
    for r in records:
        if r['collection'] == 'documents':
            assert r['doc']['doc_key'] and r['doc']['content_hash']


def test_embeddings_are_not_in_the_snapshot(records):
    assert not any('embedding' in r['doc'] for r in records)


def test_entity_links_resolve_to_documents_in_the_snapshot(records):
    """canonical_entities.mentioned_in.doc_id must match preserved _ids."""
    doc_ids = {str(r['doc']['_id']) for r in records
               if r['collection'] != 'canonical_entities'}
    dangling = [
        m['doc_id']
        for r in records if r['collection'] == 'canonical_entities'
        for m in r['doc'].get('mentioned_in', [])
        if m['doc_id'] not in doc_ids
    ]
    assert dangling == []


def test_every_query_label_resolves_to_a_snapshot_title(records):
    import json
    from src.search.document_text import document_title

    titles = {document_title(r['doc'])
              for r in records if r['collection'] == 'documents'}
    with open(os.path.join(PROJECT_ROOT, 'data', 'eval', 'queries.json')) as f:
        spec = json.load(f)
    missing = [name for q in spec['queries'] for name in q['relevant']
               if name not in titles]
    assert missing == []

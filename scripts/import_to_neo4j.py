"""
MongoDB -> Neo4j.

    python scripts/import_to_neo4j.py            # merge into whatever is there
    python scripts/import_to_neo4j.py --fresh    # clear the graph first
    python scripts/import_to_neo4j.py --yes      # never prompt (for schedulers)

One node per document, labelled by its type (see src/corpus/types.py),
carrying `doc_id` so graph-expansion retrieval can span every label with
one pattern. One Entity node per canonical entity, and a MENTIONS edge per
(document, entity) pair with the mention count. MERGE throughout, so
re-running updates rather than duplicates.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
import logging
from datetime import datetime

from src.corpus.types import COLLECTION, DOC_TYPES, TYPE_NAMES
from src.database.mongo_client import MongoDBClient
from src.database.neo4j_client import Neo4jClient

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

BATCH_SIZE = 500

# Fields copied onto the node, per type. Everything else stays in MongoDB.
NODE_FIELDS = {
    'startup': ('name', 'description', 'location', 'funding', 'source', 'link'),
    'article': ('title', 'description', 'author', 'published_date', 'source', 'article_url'),
    'repo': ('full_name', 'description', 'stars', 'forks', 'primary_language', 'source', 'html_url'),
}


def _scalar(value):
    """Neo4j properties must be primitives or lists of primitives."""
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    if isinstance(value, dict):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _batches(items, size=BATCH_SIZE):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def import_entities(mongo, neo4j) -> int:
    entities = [{
        'entity_text': e['entity_text'],
        'entity_type': e['entity_type'],
        'mention_count': e.get('mention_count', 0),
        'document_count': e.get('document_count', 0),
    } for e in mongo.db.canonical_entities.find()]

    for batch in _batches(entities):
        neo4j.run_write_query("""
            UNWIND $batch AS entity
            MERGE (e:Entity {entity_text: entity.entity_text,
                             entity_type: entity.entity_type})
            SET e.mention_count = entity.mention_count,
                e.document_count = entity.document_count
        """, {'batch': batch})
    return len(entities)


def import_documents(mongo, neo4j) -> dict:
    counts = {}
    for doc_type in TYPE_NAMES:
        label = DOC_TYPES[doc_type].neo4j_label
        fields = NODE_FIELDS.get(doc_type, ('name', 'title', 'description', 'source'))
        rows = []
        for doc in mongo.db[COLLECTION].find({'type': doc_type}):
            props = {f: _scalar(doc.get(f)) for f in fields if doc.get(f) is not None}
            props['doc_key'] = doc.get('doc_key')
            props['type'] = doc_type
            if doc.get('event_at'):
                props['event_at'] = _scalar(doc['event_at'])
            rows.append({'doc_id': str(doc['_id']), 'props': props})

        for batch in _batches(rows):
            neo4j.run_write_query(f"""
                UNWIND $batch AS row
                MERGE (d:{label} {{doc_id: row.doc_id}})
                SET d += row.props
            """, {'batch': batch})
        counts[doc_type] = len(rows)
    return counts


def import_mentions(mongo, neo4j) -> int:
    total = 0
    for doc_type in TYPE_NAMES:
        label = DOC_TYPES[doc_type].neo4j_label
        rows = []
        for doc in mongo.db[COLLECTION].find(
                {'type': doc_type, 'entities': {'$exists': True}},
                {'entities': 1}):
            entities = doc.get('entities') or []
            if isinstance(entities, str):
                continue
            for ent in entities:
                text = ent.get('entity_text')
                etype = ent.get('entity_type')
                if not text or not etype:
                    continue
                rows.append({
                    'doc_id': str(doc['_id']),
                    'entity_text': text,
                    'entity_type': etype,
                    'count': ent.get('count', 1),
                })

        for batch in _batches(rows):
            neo4j.run_write_query(f"""
                UNWIND $batch AS rel
                MATCH (d:{label} {{doc_id: rel.doc_id}})
                MATCH (e:Entity {{entity_text: rel.entity_text,
                                  entity_type: rel.entity_type}})
                MERGE (d)-[m:MENTIONS]->(e)
                SET m.count = rel.count
            """, {'batch': batch})
        total += len(rows)
    return total


def graph_summary(neo4j) -> dict:
    summary = {}
    for doc_type in TYPE_NAMES:
        label = DOC_TYPES[doc_type].neo4j_label
        summary[label] = neo4j.run_query(
            f"MATCH (n:{label}) RETURN count(n) AS n")[0]['n']
    summary['Entity'] = neo4j.run_query("MATCH (e:Entity) RETURN count(e) AS n")[0]['n']
    summary['MENTIONS'] = neo4j.run_query(
        "MATCH ()-[r:MENTIONS]->() RETURN count(r) AS n")[0]['n']
    summary['nodes'] = neo4j.get_node_count()
    summary['relationships'] = neo4j.get_relationship_count()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--fresh', action='store_true', help='clear the graph first')
    parser.add_argument('--yes', action='store_true', help='do not prompt')
    args = parser.parse_args()

    print("=" * 72)
    print("MONGODB -> NEO4J")
    print("=" * 72)

    mongo = MongoDBClient()
    neo4j = Neo4jClient()
    if not neo4j.available:
        raise SystemExit("Neo4j is not reachable; nothing imported.")

    existing = neo4j.get_node_count()
    print(f"  database: {mongo.db_name}    Neo4j nodes now: {existing}")

    if args.fresh and existing:
        if not args.yes:
            answer = input(f"  Delete all {existing} nodes and re-import? (y/n): ")
            if answer.strip().lower() != 'y':
                raise SystemExit("  Aborted.")
        neo4j.clear_database()
        print("  Cleared.")

    started = datetime.now()
    n_entities = import_entities(mongo, neo4j)
    print(f"  Entity nodes:      {n_entities}")
    doc_counts = import_documents(mongo, neo4j)
    for doc_type, n in doc_counts.items():
        print(f"  {DOC_TYPES[doc_type].neo4j_label + ' nodes:':<19}{n}")
    n_mentions = import_mentions(mongo, neo4j)
    print(f"  MENTIONS edges:    {n_mentions}")

    summary = graph_summary(neo4j)
    print(f"\n  Graph: {summary['nodes']} nodes, {summary['relationships']} relationships "
          f"({(datetime.now() - started).total_seconds():.1f}s)")

    mongo.close()
    neo4j.close()


if __name__ == '__main__':
    main()

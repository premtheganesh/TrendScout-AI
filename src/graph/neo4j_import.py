"""
MongoDB -> Neo4j sync. One node per document labelled by type, one Entity
node per canonical entity, a MENTIONS edge per (document, entity) with the
count. MERGE throughout, so re-running updates rather than duplicates.
"""

from datetime import datetime
from typing import Dict

from src.corpus.types import COLLECTION, DOC_TYPES, TYPE_NAMES

BATCH_SIZE = 500

# Fields copied onto the node, per type. Everything else stays in MongoDB.
NODE_FIELDS = {
    'startup': ('name', 'description', 'location', 'funding', 'source', 'link', 'yc_batch'),
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


def import_entities(db, neo4j) -> int:
    entities = [{
        'entity_text': e['entity_text'],
        'entity_type': e['entity_type'],
        'mention_count': e.get('mention_count', 0),
        'document_count': e.get('document_count', 0),
    } for e in db.canonical_entities.find()]

    for batch in _batches(entities):
        neo4j.run_write_query("""
            UNWIND $batch AS entity
            MERGE (e:Entity {entity_text: entity.entity_text,
                             entity_type: entity.entity_type})
            SET e.mention_count = entity.mention_count,
                e.document_count = entity.document_count
        """, {'batch': batch})
    return len(entities)


def import_documents(db, neo4j) -> Dict[str, int]:
    counts = {}
    for doc_type in TYPE_NAMES:
        label = DOC_TYPES[doc_type].neo4j_label
        fields = NODE_FIELDS.get(doc_type, ('name', 'title', 'description', 'source'))
        rows = []
        for doc in db[COLLECTION].find({'type': doc_type}):
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


def import_mentions(db, neo4j) -> int:
    total = 0
    for doc_type in TYPE_NAMES:
        label = DOC_TYPES[doc_type].neo4j_label
        rows = []
        for doc in db[COLLECTION].find(
                {'type': doc_type, 'entities': {'$exists': True}}, {'entities': 1}):
            entities = doc.get('entities') or []
            if isinstance(entities, str):
                continue
            for ent in entities:
                text, etype = ent.get('entity_text'), ent.get('entity_type')
                if not text or not etype:
                    continue
                rows.append({'doc_id': str(doc['_id']), 'entity_text': text,
                             'entity_type': etype, 'count': ent.get('count', 1)})

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


def graph_summary(neo4j) -> Dict[str, int]:
    summary = {}
    for doc_type in TYPE_NAMES:
        label = DOC_TYPES[doc_type].neo4j_label
        summary[label] = neo4j.run_query(f"MATCH (n:{label}) RETURN count(n) AS n")[0]['n']
    summary['Entity'] = neo4j.run_query("MATCH (e:Entity) RETURN count(e) AS n")[0]['n']
    summary['MENTIONS'] = neo4j.run_query("MATCH ()-[r:MENTIONS]->() RETURN count(r) AS n")[0]['n']
    summary['nodes'] = neo4j.get_node_count()
    summary['relationships'] = neo4j.get_relationship_count()
    return summary


def sync(db, neo4j, fresh: bool = False) -> Dict[str, int]:
    """Full merge of the corpus into Neo4j. `fresh` clears the graph first."""
    if fresh:
        neo4j.clear_database()
    n_entities = import_entities(db, neo4j)
    doc_counts = import_documents(db, neo4j)
    n_mentions = import_mentions(db, neo4j)
    summary = graph_summary(neo4j)
    summary.update({'imported_entities': n_entities, 'imported_mentions': n_mentions,
                    **{f'imported_{k}': v for k, v in doc_counts.items()}})
    return summary

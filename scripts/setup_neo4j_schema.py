"""
Neo4j constraints and indexes, derived from the document type registry.

    python scripts/setup_neo4j_schema.py

Every document label gets a unique `doc_id` (the MongoDB _id) — that is
the one property graph-expansion retrieval looks documents up by, across
all labels with a single pattern. Entities are unique on
(entity_text, entity_type).
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging

from src.corpus.types import DOC_TYPES, TYPE_NAMES
from src.database.neo4j_client import Neo4jClient

logging.basicConfig(level=logging.WARNING)

# Secondary lookups used by the API and the UI.
EXTRA_INDEXES = {
    'startup': ('name', 'location'),
    'article': ('title',),
    'repo': ('full_name',),
}


def statements():
    for doc_type in TYPE_NAMES:
        label = DOC_TYPES[doc_type].neo4j_label
        yield (f"{label.lower()}_doc_id_unique",
               f"CREATE CONSTRAINT {label.lower()}_doc_id_unique IF NOT EXISTS "
               f"FOR (n:{label}) REQUIRE n.doc_id IS UNIQUE")
        for field in EXTRA_INDEXES.get(doc_type, ()):
            yield (f"{label.lower()}_{field}_index",
                   f"CREATE INDEX {label.lower()}_{field}_index IF NOT EXISTS "
                   f"FOR (n:{label}) ON (n.{field})")

    yield ("entity_unique",
           "CREATE CONSTRAINT entity_unique IF NOT EXISTS "
           "FOR (e:Entity) REQUIRE (e.entity_text, e.entity_type) IS UNIQUE")
    yield ("entity_type_index",
           "CREATE INDEX entity_type_index IF NOT EXISTS FOR (e:Entity) ON (e.entity_type)")
    yield ("entity_mentions_index",
           "CREATE INDEX entity_mentions_index IF NOT EXISTS FOR (e:Entity) ON (e.mention_count)")


def main():
    print("=" * 72)
    print("NEO4J SCHEMA")
    print("=" * 72)

    neo4j = Neo4jClient()
    if not neo4j.available:
        raise SystemExit("Neo4j is not reachable.")

    for name, cypher in statements():
        try:
            neo4j.run_write_query(cypher)
            print(f"  ok   {name}")
        except Exception as e:
            print(f"  skip {name}: {e}")

    print("\n  Constraints:")
    for record in neo4j.run_query("SHOW CONSTRAINTS"):
        print(f"    {record['name']}")
    print("  Indexes:")
    for record in neo4j.run_query("SHOW INDEXES"):
        print(f"    {record['name']}  ({record['type']})")

    neo4j.close()


if __name__ == '__main__':
    main()

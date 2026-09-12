"""
MongoDB -> Neo4j.

    python scripts/import_to_neo4j.py            # merge into whatever is there
    python scripts/import_to_neo4j.py --fresh    # clear the graph first
    python scripts/import_to_neo4j.py --yes      # never prompt (for schedulers)

The work lives in src/graph/neo4j_import.py; the pipeline's `neo4j` stage
runs the same code. This script exists for a manual, verbose run.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
import logging
from datetime import datetime

from src.database.mongo_client import MongoDBClient
from src.database.neo4j_client import Neo4jClient
from src.graph.neo4j_import import sync

logging.basicConfig(level=logging.WARNING)


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
    if args.fresh and existing and not args.yes:
        if input(f"  Delete all {existing} nodes and re-import? (y/n): ").strip().lower() != 'y':
            raise SystemExit("  Aborted.")

    started = datetime.now()
    summary = sync(mongo.db, neo4j, fresh=args.fresh)
    for key in ('Startup', 'Article', 'GitHubRepo', 'Entity', 'MENTIONS'):
        print(f"  {key + ':':<12}{summary.get(key, 0)}")
    print(f"\n  Graph: {summary['nodes']} nodes, {summary['relationships']} relationships "
          f"({(datetime.now() - started).total_seconds():.1f}s)")
    mongo.close()
    neo4j.close()


if __name__ == '__main__':
    main()

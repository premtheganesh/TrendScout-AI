"""Setup Neo4j Schema - Constraints and Indexes"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database.neo4j_client import Neo4jClient
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_constraints(neo4j):
    """Create uniqueness constraints on node IDs"""

    print("\n" + "=" * 70)
    print("CREATING CONSTRAINTS")
    print("=" * 70)

    constraints = [
        # Startup nodes - unique by MongoDB _id
        """
        CREATE CONSTRAINT startup_id_unique IF NOT EXISTS
        FOR (s:Startup) REQUIRE s.startup_id IS UNIQUE
        """,

        # Article nodes - unique by MongoDB _id
        """
        CREATE CONSTRAINT article_id_unique IF NOT EXISTS
        FOR (a:Article) REQUIRE a.article_id IS UNIQUE
        """,

        # GitHubRepo nodes - unique by MongoDB _id
        """
        CREATE CONSTRAINT repo_id_unique IF NOT EXISTS
        FOR (r:GitHubRepo) REQUIRE r.repo_id IS UNIQUE
        """,

        # Entity nodes - unique by (entity_text, entity_type)
        # This ensures we don't have duplicate "Google (ORG)" entities
        """
        CREATE CONSTRAINT entity_unique IF NOT EXISTS
        FOR (e:Entity) REQUIRE (e.entity_text, e.entity_type) IS UNIQUE
        """
    ]

    for i, constraint in enumerate(constraints, 1):
        try:
            neo4j.run_write_query(constraint)
            constraint_name = constraint.split('\n')[1].strip().split()[2]
            print(f"[{i}] Created constraint: {constraint_name}")
        except Exception as e:
            print(f"[{i}] Constraint may already exist: {e}")

    logger.info("Constraints created successfully")


def create_indexes(neo4j):
    """Create indexes for fast queries"""

    print("\n" + "=" * 70)
    print("CREATING INDEXES")
    print("=" * 70)

    indexes = [
        # Index on Startup name (for "find startup named X" queries)
        """
        CREATE INDEX startup_name_index IF NOT EXISTS
        FOR (s:Startup) ON (s.name)
        """,

        # Index on Startup location (for "find startups in X city" queries)
        """
        CREATE INDEX startup_location_index IF NOT EXISTS
        FOR (s:Startup) ON (s.location)
        """,

        # Index on Article title
        """
        CREATE INDEX article_title_index IF NOT EXISTS
        FOR (a:Article) ON (a.title)
        """,

        # Index on GitHubRepo full_name
        """
        CREATE INDEX repo_name_index IF NOT EXISTS
        FOR (r:GitHubRepo) ON (r.full_name)
        """,

        # Index on Entity type (for "find all ORG entities" queries)
        """
        CREATE INDEX entity_type_index IF NOT EXISTS
        FOR (e:Entity) ON (e.entity_type)
        """,

        # Index on Entity mention_count (for "most mentioned entities" queries)
        """
        CREATE INDEX entity_mentions_index IF NOT EXISTS
        FOR (e:Entity) ON (e.mention_count)
        """,

        # doc_id is the uniform document identifier carried by all three
        # document labels, so graph-expansion retrieval can traverse across
        # them with one pattern. These back the
        # `WHERE d.doc_id IN $seed_ids` lookup in
        # src/search/graph_expansion.py — without them that becomes a full
        # label scan on every search request.
        """
        CREATE INDEX startup_doc_id_index IF NOT EXISTS
        FOR (s:Startup) ON (s.doc_id)
        """,
        """
        CREATE INDEX article_doc_id_index IF NOT EXISTS
        FOR (a:Article) ON (a.doc_id)
        """,
        """
        CREATE INDEX repo_doc_id_index IF NOT EXISTS
        FOR (r:GitHubRepo) ON (r.doc_id)
        """
    ]

    for i, index in enumerate(indexes, 1):
        try:
            neo4j.run_write_query(index)
            index_name = index.split('\n')[1].strip().split()[2]
            print(f"[{i}] Created index: {index_name}")
        except Exception as e:
            print(f"[{i}] Index may already exist: {e}")

    logger.info("Indexes created successfully")


def print_schema_info(neo4j):
    """Print current schema: constraints and indexes"""

    print("\n" + "=" * 70)
    print("CURRENT SCHEMA")
    print("=" * 70)

    # Get all constraints
    print("\nConstraints:")
    result = neo4j.run_query("SHOW CONSTRAINTS")
    for i, record in enumerate(result, 1):
        print(f"  {i}. {record['name']}: {record['type']}")

    # Get all indexes
    print("\nIndexes:")
    result = neo4j.run_query("SHOW INDEXES")
    for i, record in enumerate(result, 1):
        print(f"  {i}. {record['name']}: {record['type']}")


def print_planned_schema():
    """Print what our graph will look like after data import"""

    print("\n" + "=" * 70)
    print("PLANNED GRAPH SCHEMA")
    print("=" * 70)

    schema = """
    NODE TYPES:

    1. (:Startup)
       Properties: startup_id, name, description, location, funding_amount,
                   founded_date, website, source

    2. (:Article)
       Properties: article_id, title, description, url, published_date, source

    3. (:GitHubRepo)
       Properties: repo_id, full_name, description, stars, forks, language,
                   url, topics

    4. (:Entity)
       Properties: entity_text, entity_type, mention_count
       Types: ORG, PRODUCT, PERSON, GPE, MONEY, DATE, etc.

    RELATIONSHIP TYPES:

    1. (Startup)-[:MENTIONS]->(Entity)
       - Connects startups to entities they mention

    2. (Article)-[:MENTIONS]->(Entity)
       - Connects articles to entities they mention

    3. (GitHubRepo)-[:MENTIONS]->(Entity)
       - Connects repos to entities they mention

    EXAMPLE QUERIES YOU'LL BE ABLE TO RUN:

    1. "Which startups mention Google?"
       MATCH (s:Startup)-[:MENTIONS]->(e:Entity {entity_text: 'Google'})
       RETURN s.name

    2. "Find all AI-related entities"
       MATCH (e:Entity) WHERE e.entity_text CONTAINS 'AI'
       RETURN e.entity_text, e.mention_count

    3. "Most mentioned organizations"
       MATCH (e:Entity {entity_type: 'ORG'})
       RETURN e.entity_text, e.mention_count
       ORDER BY e.mention_count DESC
       LIMIT 10
    """

    print(schema)


def main():
    """Main function to setup Neo4j schema"""

    print("=" * 70)
    print("NEO4J SCHEMA SETUP")
    print("=" * 70)

    # Print planned schema first
    print_planned_schema()

    # Connect to Neo4j
    print("\n[1] Connecting to Neo4j...")
    neo4j = Neo4jClient()
    print("SUCCESS Connected\n")

    # Check current state
    node_count = neo4j.get_node_count()
    print(f"Current database state: {node_count} nodes")

    # Create constraints
    print("\n[2] Creating constraints...")
    create_constraints(neo4j)

    # Create indexes
    print("\n[3] Creating indexes...")
    create_indexes(neo4j)

    # Show schema
    print("\n[4] Displaying schema...")
    print_schema_info(neo4j)

    # Summary
    print("\n" + "=" * 70)
    print("SUCCESS SCHEMA SETUP COMPLETE")
    print("=" * 70)
    print("\nWhat just happened:")
    print("Created constraints to prevent duplicate nodes")
    print("Created indexes for fast queries")
    print("Database is ready for data import")
    print("\nNext steps:")
    print("  1. Review the schema above")
    print("  2. Ready for Sub-Phase 2.4 (MongoDB → Neo4j ETL)")
    print("  3. We'll import all 210 documents + 251 entities")

    # Cleanup
    neo4j.close()


if __name__ == "__main__":
    main()

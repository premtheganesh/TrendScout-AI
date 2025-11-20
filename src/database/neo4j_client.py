"""
Neo4j Database Client

This module handles connection to Neo4j graph database.

What it does:
- Connects to Neo4j using credentials from .env
- Provides methods to run Cypher queries
- Manages database sessions and transactions

Why we need this:
- Centralized Neo4j connection management
- Reusable across all scripts that need Neo4j
- Similar pattern to MongoDBClient for consistency
"""

import os
from neo4j import GraphDatabase
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)


class Neo4jClient:
    """
    Neo4j database client for TrendScout AI project

    Usage:
        neo4j = Neo4jClient()
        neo4j.run_query("CREATE (n:Person {name: 'Alice'})")
        neo4j.close()
    """

    def __init__(self):
        """
        Initialize Neo4j connection using .env credentials

        Reads:
            NEO4J_URI - bolt://localhost:7687
            NEO4J_USER - neo4j
            NEO4J_PASSWORD - your password
        """
        load_dotenv()

        self.uri = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
        self.user = os.getenv('NEO4J_USER', 'neo4j')
        self.password = os.getenv('NEO4J_PASSWORD')

        if not self.password:
            raise ValueError("NEO4J_PASSWORD not found in .env file")

        logger.info(f"Connecting to Neo4j at {self.uri}...")

        try:
            self.driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password)
            )

            # Verify connection
            self.driver.verify_connectivity()

            logger.info("✅ Connected to Neo4j")

        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            raise

    def run_query(self, query, parameters=None):
        """
        Run a Cypher query and return results

        Args:
            query: Cypher query string
            parameters: Dictionary of parameters for the query

        Returns:
            List of records from the query

        Example:
            results = neo4j.run_query(
                "CREATE (n:Person {name: $name}) RETURN n",
                parameters={'name': 'Alice'}
            )
        """
        with self.driver.session() as session:
            result = session.run(query, parameters or {})
            return list(result)

    def run_write_query(self, query, parameters=None):
        """
        Run a write query (CREATE, MERGE, DELETE, etc.)

        Args:
            query: Cypher query string
            parameters: Dictionary of parameters

        Returns:
            Query result summary
        """
        with self.driver.session() as session:
            result = session.run(query, parameters or {})
            summary = result.consume()
            return summary

    def clear_database(self):
        """
        DANGER: Deletes all nodes and relationships

        Use this only for:
        - Testing
        - Fresh start
        - Development

        DO NOT use in production without backup!
        """
        logger.warning("⚠️  Clearing entire Neo4j database...")

        query = "MATCH (n) DETACH DELETE n"
        self.run_write_query(query)

        logger.info("✅ Database cleared")

    def get_node_count(self):
        """
        Get total number of nodes in database

        Returns:
            Integer count of all nodes
        """
        result = self.run_query("MATCH (n) RETURN count(n) as count")
        return result[0]['count'] if result else 0

    def get_relationship_count(self):
        """
        Get total number of relationships in database

        Returns:
            Integer count of all relationships
        """
        result = self.run_query("MATCH ()-[r]->() RETURN count(r) as count")
        return result[0]['count'] if result else 0

    def close(self):
        """Close the Neo4j connection"""
        if self.driver:
            self.driver.close()
            logger.info("❌ Closed Neo4j connection")


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    """
    Test the Neo4jClient

    Run this file directly:
        python src/database/neo4j_client.py
    """

    logging.basicConfig(level=logging.INFO)

    print("=" * 70)
    print("TESTING NEO4J CLIENT")
    print("=" * 70)

    # Create client
    print("\n[1] Creating Neo4j client...")
    neo4j = Neo4jClient()

    # Test query
    print("\n[2] Running test query...")
    result = neo4j.run_query("RETURN 'Hello from Neo4j!' as message")
    print(f"Result: {result[0]['message']}")

    # Get counts
    print("\n[3] Getting database statistics...")
    node_count = neo4j.get_node_count()
    rel_count = neo4j.get_relationship_count()
    print(f"Nodes: {node_count}")
    print(f"Relationships: {rel_count}")

    # Close
    print("\n[4] Closing connection...")
    neo4j.close()

    print("\n" + "=" * 70)
    print("✅ NEO4J CLIENT TEST COMPLETE")
    print("=" * 70)

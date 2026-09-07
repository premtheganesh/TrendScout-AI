"""Neo4j Database Client"""

import os
from neo4j import GraphDatabase
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)


class Neo4jClient:
    """Neo4j database client for TrendScout AI project"""

    def __init__(self):
        """Initialize Neo4j connection using .env credentials"""
        load_dotenv(override=True)

        self.uri = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
        self.user = os.getenv('NEO4J_USER', 'neo4j')
        self.password = os.getenv('NEO4J_PASSWORD')

        if not self.password:
            raise ValueError("NEO4J_PASSWORD not found in .env file")

        logger.info(f"Connecting to Neo4j at {self.uri}...")

        self.available = False

        try:
            self.driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password)
            )

            # Verify connection
            self.driver.verify_connectivity()

            self.available = True
            logger.info("Connected to Neo4j")

        except Exception as e:
            logger.warning(
                f"Neo4j unavailable (graph features disabled): {e}\n"
                "    Graph endpoints will return 503 until it is reachable."
            )
            self.driver = None

    def run_query(self, query, parameters=None):
        """Run a Cypher query and return results"""
        if not self.available:
            raise RuntimeError("Neo4j is not available.")
        with self.driver.session() as session:
            result = session.run(query, parameters or {})
            return list(result)

    def run_write_query(self, query, parameters=None):
        """Run a write query (CREATE, MERGE, DELETE, etc.)"""
        if not self.available:
            raise RuntimeError("Neo4j is not available.")
        with self.driver.session() as session:
            result = session.run(query, parameters or {})
            summary = result.consume()
            return summary

    def clear_database(self):
        """DANGER: Deletes all nodes and relationships"""
        logger.warning("Clearing entire Neo4j database...")

        query = "MATCH (n) DETACH DELETE n"
        self.run_write_query(query)

        logger.info("Database cleared")

    def get_node_count(self):
        """Get total number of nodes in database"""
        result = self.run_query("MATCH (n) RETURN count(n) as count")
        return result[0]['count'] if result else 0

    def get_relationship_count(self):
        """Get total number of relationships in database"""
        result = self.run_query("MATCH ()-[r]->() RETURN count(r) as count")
        return result[0]['count'] if result else 0

    def close(self):
        """Close the Neo4j connection"""
        if self.driver and self.available:
            self.driver.close()
            logger.info("Closed Neo4j connection")


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
    print("NEO4J CLIENT TEST COMPLETE")
    print("=" * 70)

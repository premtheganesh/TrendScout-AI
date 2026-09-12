"""Optional Neo4j stage: skipped, not failed, when Neo4j is unreachable."""

import logging
from typing import Dict, Optional

from src.graph.neo4j_import import sync

logger = logging.getLogger(__name__)


def sync_graph(db, fresh: bool = False) -> Optional[Dict[str, int]]:
    try:
        from src.database.neo4j_client import Neo4jClient
        neo4j = Neo4jClient()
    except Exception as e:
        logger.warning(f"Neo4j not configured ({e}); graph stage skipped")
        return None
    if not neo4j.available:
        logger.warning("Neo4j unreachable; graph stage skipped")
        return None
    try:
        return sync(db, neo4j, fresh=fresh)
    finally:
        neo4j.close()

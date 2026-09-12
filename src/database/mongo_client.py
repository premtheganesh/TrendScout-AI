"""MongoDB connection for TrendScout AI."""

import logging

from pymongo import MongoClient

from src.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MongoDBClient:
    def __init__(self, db_name: str = None, uri: str = None):
        settings = get_settings()
        self.uri = uri or settings.mongodb_uri
        self.db_name = db_name or settings.mongodb_db
        # tz_aware: stored UTC datetimes come back timezone-aware, so they
        # compare correctly against datetime.now(timezone.utc).
        self.client = MongoClient(self.uri, tz_aware=True)
        self.db = self.client[self.db_name]
        logger.info(f"Connected to MongoDB {self.db_name}")

    def count_documents(self, collection: str) -> int:
        return self.db[collection].count_documents({})

    def close(self):
        self.client.close()
        logger.info("Closed MongoDB connection")

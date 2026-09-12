from pymongo import MongoClient
from datetime import datetime
import logging
from typing import List, Dict, Optional

from src.config import get_settings

logging.basicConfig(
    level = logging.INFO
)

logger = logging.getLogger(__name__)

class MongoDBClient:
    """MongoDB client for Trendscout AI"""
    def __init__(self, db_name: str = None, uri: str = None):
        settings = get_settings()
        self.uri = uri or settings.mongodb_uri
        self.db_name = db_name or settings.mongodb_db
        # tz_aware: stored UTC datetimes come back timezone-aware, so they
        # compare correctly against datetime.now(timezone.utc).
        self.client = MongoClient(self.uri, tz_aware=True)
        self.db = self.client[self.db_name]
        logger.info(f"Connected to MongoDB {self.db_name}")
    
    def insert_startup(self, data: Dict) -> str:
        data['inserted_at'] = datetime.utcnow()
        data['updated_at'] = datetime.utcnow()

        result = self.db.startups.insert_one(data)
        logger.info(f"Inserted startup: {data.get('name')}")
        
        return str(result.inserted_id)
    
    def get_all_startups(self, limit: int = 100) -> List[Dict]:
        """Get all startups (up to limit)"""
        return list(self.db.startups.find().limit(limit))
    
    def get_startup_by_name(self, name: str) -> Optional[Dict]:
        """Get a specific startup by name"""
        return self.db.startups.find_one({"name": name})
    
    def update_startup(self, name: str, update_data: Dict):
        """Update a startup document"""
        update_data['updated_at'] = datetime.utcnow()
        self.db.startups.update_one(
            {"name": name},
            {"$set": update_data}
        )
        logger.info(f"Updated startup: {name}")
    
    # ===== LINKEDIN OPERATIONS =====
    
    def insert_post(self, data: Dict) -> str:
        """Insert a LinkedIn post"""
        data['inserted_at'] = datetime.utcnow()
        result = self.db.linkedin_posts.insert_one(data)
        return str(result.inserted_id)
    
    def get_posts_by_author(self, author_name: str) -> List[Dict]:
        """Get all posts by a specific author"""
        return list(self.db.linkedin_posts.find({"author.name": author_name}))
    
    # ===== NEWS OPERATIONS =====
    
    def insert_article(self, data: Dict) -> str:
        """Insert a news article"""
        data['inserted_at'] = datetime.utcnow()
        result = self.db.news_articles.insert_one(data)
        return str(result.inserted_id)
    
    # ===== UTILITY METHODS =====
    
    def count_documents(self, collection: str) -> int:
        """Count documents in a collection"""
        return self.db[collection].count_documents({})
    
    def get_summary(self) -> Dict:
        """Get database summary"""
        return {
            'startups': self.count_documents('startups'),
            'posts': self.count_documents('linkedin_posts'),
            'articles': self.count_documents('news_articles'),
            'total': (
                self.count_documents('startups') +
                self.count_documents('linkedin_posts') +
                self.count_documents('news_articles')
            )
        }
    
    def close(self):
        """Close MongoDB connection"""
        self.client.close()
        logger.info("Closed MongoDB connection")
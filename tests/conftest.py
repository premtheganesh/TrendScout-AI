"""
Shared fixtures.

Unit tests run anywhere. Integration tests skip, rather than fail, when
MongoDB or the indexes are missing.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))


def _mongo_available() -> bool:
    try:
        from pymongo import MongoClient
        from dotenv import load_dotenv
        load_dotenv()
        client = MongoClient(os.getenv('MONGODB_URI'), serverSelectionTimeoutMS=1500)
        client.admin.command('ping')
        return True
    except Exception:
        return False


def _indexes_available() -> bool:
    return (os.path.exists(os.path.join(DATA_DIR, 'faiss_index.bin'))
            and os.path.exists(os.path.join(DATA_DIR, 'bm25_index.pkl')))


needs_mongo = pytest.mark.skipif(
    not _mongo_available(),
    reason="MongoDB is not reachable — start it with `brew services start mongodb-community`"
)

needs_indexes = pytest.mark.skipif(
    not _indexes_available(),
    reason="Indexes not built — run `python scripts/build_indexes.py`"
)


@pytest.fixture(scope="session")
def mongo():
    from src.database.mongo_client import MongoDBClient
    client = MongoDBClient()
    yield client
    client.close()


@pytest.fixture(scope="session")
def engine():
    """A real HybridSearchEngine. Session-scoped because constructing one
    loads a 440MB transformer — doing that per-test would be unusable."""
    from src.search.hybrid_search import HybridSearchEngine
    engine = HybridSearchEngine()
    yield engine
    engine.close()


@pytest.fixture
def sample_startup():
    return {
        '_id': 'abc123',
        'name': 'Suno',
        'description': 'Suno is an AI music generation startup.',
        'location': 'Cambridge, Massachusetts',
        'funding': 'Series B, $125 Million',
        'investors': "['Lightspeed', 'Founder Collective']",
        'link': 'https://suno.com',
        'embedding': [0.1] * 768,
    }


@pytest.fixture
def sample_repo():
    return {
        '_id': 'def456',
        'name': 'langchain',
        'full_name': 'langchain-ai/langchain',
        'description': 'Build context-aware reasoning applications.',
        'primary_language': 'Python',
        'topics': "['ai', 'llm', 'agents']",
        'stars': '119517',
        'html_url': 'https://github.com/langchain-ai/langchain',
    }


@pytest.fixture
def sample_article():
    return {
        '_id': 'ghi789',
        'title': 'AI startup raises $50M',
        'description': 'A funding round led by Kleiner Perkins.',
        'author': 'Julie Bort',
        'categories': "['AI', 'Startups']",
        'article_url': 'https://techcrunch.com/example',
    }

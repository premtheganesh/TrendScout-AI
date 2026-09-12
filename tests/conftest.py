"""
Shared fixtures and skip logic.

Unit tests run anywhere. Tests marked `needs_mongo` / `needs_indexes` skip,
rather than fail, when MongoDB or the built indexes are missing. Markers
are registered in pytest.ini, so `pytest -m "not needs_mongo"` works.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.config import get_settings  # noqa: E402

needs_mongo = pytest.mark.needs_mongo
needs_indexes = pytest.mark.needs_indexes


def _mongo_available() -> bool:
    try:
        from pymongo import MongoClient
        client = MongoClient(get_settings().mongodb_uri, serverSelectionTimeoutMS=1500)
        client.admin.command('ping')
        return True
    except Exception:
        return False


def _indexes_available() -> bool:
    s = get_settings()
    return os.path.exists(s.faiss_index_path) and os.path.exists(s.bm25_index_path)


def pytest_collection_modifyitems(config, items):
    wanted = {m for item in items for m in ('needs_mongo', 'needs_indexes')
              if m in item.keywords}
    if not wanted:
        return

    skips = {}
    if 'needs_mongo' in wanted and not _mongo_available():
        skips['needs_mongo'] = pytest.mark.skip(
            reason="MongoDB is not reachable — start it with "
                   "`brew services start mongodb-community`")
    if 'needs_indexes' in wanted and not _indexes_available():
        skips['needs_indexes'] = pytest.mark.skip(
            reason=f"Indexes not built in {get_settings().index_dir} — run "
                   "`python scripts/build_indexes.py`")

    for item in items:
        for marker, skip in skips.items():
            if marker in item.keywords:
                item.add_marker(skip)


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

"""Settings resolution. No database, no network."""

import os

from src.config import Settings, PROJECT_ROOT, get_settings


class TestSettings:
    def test_defaults_point_at_the_live_corpus(self):
        s = Settings(_env_file=None)
        assert s.mongodb_db == 'trendscout_ai'
        assert s.index_dir == os.path.join(PROJECT_ROOT, 'data')

    def test_environment_overrides_dotenv(self, monkeypatch):
        monkeypatch.setenv('MONGODB_DB', 'trendscout_eval')
        monkeypatch.setenv('INDEX_DIR', 'data/eval_index')
        s = Settings()
        assert s.mongodb_db == 'trendscout_eval'
        assert s.index_dir == os.path.join(PROJECT_ROOT, 'data', 'eval_index')

    def test_absolute_index_dir_is_kept(self):
        s = Settings(_env_file=None, index_dir='/tmp/somewhere')
        assert s.index_dir == '/tmp/somewhere'
        assert s.faiss_index_path == '/tmp/somewhere/faiss_index.bin'
        assert s.faiss_metadata_path == '/tmp/somewhere/faiss_metadata.pkl'
        assert s.bm25_index_path == '/tmp/somewhere/bm25_index.pkl'

    def test_cors_origins_split_on_commas(self):
        s = Settings(_env_file=None, cors_origins=' http://a.com, http://b.com ,')
        assert s.cors_origin_list == ['http://a.com', 'http://b.com']
        assert Settings(_env_file=None).cors_origin_list == ['*']

    def test_unknown_env_keys_are_ignored(self, monkeypatch):
        monkeypatch.setenv('LINKEDIN_EMAIL', 'x@y.z')
        Settings()  # must not raise


class TestClientsReadSettings:
    def test_mongo_client_uses_configured_database(self, monkeypatch):
        """MongoClient connects lazily, so this touches no server."""
        from src.database.mongo_client import MongoDBClient
        monkeypatch.setenv('MONGODB_DB', 'trendscout_eval')
        get_settings.cache_clear()
        try:
            client = MongoDBClient()
            assert client.db.name == 'trendscout_eval'
            assert MongoDBClient(db_name='explicit').db.name == 'explicit'
        finally:
            get_settings.cache_clear()

    def test_bm25_default_path_follows_index_dir(self, monkeypatch):
        from src.search.bm25_index import default_index_path
        monkeypatch.setenv('INDEX_DIR', 'data/eval_index')
        get_settings.cache_clear()
        try:
            assert default_index_path().endswith(
                os.path.join('data', 'eval_index', 'bm25_index.pkl'))
        finally:
            get_settings.cache_clear()

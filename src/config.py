"""
Central configuration.

Every value comes from the environment or `.env`, with environment variables
taking precedence. Nothing else in the codebase should read os.getenv for
these keys — import get_settings() instead, so one process can be pointed at
a different database and index directory:

    MONGODB_DB=trendscout_eval INDEX_DIR=data/eval_index \
        python scripts/evaluate_retrieval.py
"""

import os
from functools import lru_cache
from typing import List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(PROJECT_ROOT, '.env'),
        env_file_encoding='utf-8',
        extra='ignore',
    )

    # --- Databases ---
    mongodb_uri: str = 'mongodb://localhost:27017/'
    mongodb_db: str = 'trendscout_ai'
    neo4j_uri: str = 'neo4j://127.0.0.1:7687'
    neo4j_user: str = 'neo4j'
    neo4j_password: Optional[str] = None

    # --- Built indexes (FAISS + BM25) ---
    # A relative path resolves against the repository root, so the live
    # corpus and the frozen evaluation corpus can keep separate indexes.
    index_dir: str = 'data'

    # --- Models ---
    embedding_model: str = 'intfloat/e5-base-v2'
    spacy_model: str = 'en_core_web_trf'   # what the corpus's entities were built with
    groq_api_key: Optional[str] = None
    groq_model: str = 'openai/gpt-oss-120b'

    # --- External APIs ---
    github_token: Optional[str] = None

    # --- API server ---
    cors_origins: str = '*'          # comma-separated
    admin_token: Optional[str] = None

    @field_validator('index_dir')
    @classmethod
    def _absolute_index_dir(cls, value: str) -> str:
        if os.path.isabs(value):
            return value
        return os.path.abspath(os.path.join(PROJECT_ROOT, value))

    @property
    def faiss_index_path(self) -> str:
        return os.path.join(self.index_dir, 'faiss_index.bin')

    @property
    def faiss_metadata_path(self) -> str:
        return os.path.join(self.index_dir, 'faiss_metadata.pkl')

    @property
    def bm25_index_path(self) -> str:
        return os.path.join(self.index_dir, 'bm25_index.pkl')

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(',') if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings. Call get_settings.cache_clear() in tests that
    change the environment after the first call."""
    return Settings()

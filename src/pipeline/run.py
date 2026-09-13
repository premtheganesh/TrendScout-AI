"""
Orchestrate the stages and log the run.

    refresh    recompute content_hash; adopt pre-marker rows
    entities   NER for stale documents, then rebuild canonical_entities
    embed      E5 vectors for stale documents
    index      FAISS + BM25 from stored vectors
    snapshots  today's metric snapshot per repo / model / launch / paper
    funding    LLM extraction of funding rounds from unprocessed funding news
    companies  rebuild the companies collection from documents + rounds
    trends     weekly topic counts for the trailing 8 weeks
    neo4j      merge into Neo4j if reachable (skipped otherwise)

Heavy models load lazily, only if a stage that needs them runs.
"""

import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.config import get_settings
from src.pipeline import embed, entities, hashes, index, snapshots
from src.pipeline.graph import sync_graph
from src.entities.resolve import build_companies
from src.extraction.funding import extract_stale as extract_funding
from src.trends.compute import compute_trends

logger = logging.getLogger(__name__)

STAGES = ('refresh', 'entities', 'embed', 'index', 'snapshots', 'funding', 'companies', 'trends', 'neo4j')
DEFAULT_STAGES = ('refresh', 'entities', 'embed', 'index', 'snapshots', 'funding', 'companies', 'trends', 'neo4j')


class Pipeline:
    def __init__(self, db, index_dir: Optional[str] = None,
                 extractor=None, generator=None, llm=None, funding_limit: int = 40):
        self.db = db
        self.index_dir = index_dir or get_settings().index_dir
        self._extractor = extractor
        self._generator = generator
        self._llm = llm
        self.funding_limit = funding_limit

    @property
    def llm(self):
        if self._llm is None:
            from src.llm.groq_client import GroqClient
            self._llm = GroqClient()
        return self._llm

    @property
    def extractor(self):
        if self._extractor is None:
            from src.extractors.entity_extractor import EntityExtractor
            self._extractor = EntityExtractor(get_settings().spacy_model)
        return self._extractor

    @property
    def generator(self):
        if self._generator is None:
            from src.embeddings.embedding_generator import EmbeddingGenerator
            self._generator = EmbeddingGenerator()
        return self._generator

    def run_stage(self, stage: str, force: bool = False) -> Dict[str, Any]:
        if stage == 'refresh':
            return hashes.refresh_hashes(self.db)
        if stage == 'entities':
            processed = entities.extract_stale(self.db, self.extractor, force=force)
            return {'processed': processed, **entities.rebuild_canonical_index(self.db)}
        if stage == 'embed':
            return {'embedded': embed.embed_stale(self.db, self.generator, force=force)}
        if stage == 'index':
            return index.build_indexes(self.db, self.index_dir)
        if stage == 'snapshots':
            return {'captured': snapshots.capture(self.db)}
        if stage == 'funding':
            try:
                llm = self.llm
            except Exception as e:
                return {'skipped': f'no LLM ({e})'}
            return extract_funding(self.db, llm, getattr(llm, 'model', 'unknown'),
                                   limit=self.funding_limit, force=force)
        if stage == 'companies':
            return build_companies(self.db)
        if stage == 'trends':
            return compute_trends(self.db)
        if stage == 'neo4j':
            summary = sync_graph(self.db)
            return summary if summary is not None else {'skipped': 'neo4j unreachable'}
        raise ValueError(f"unknown stage {stage!r}; choose from {STAGES}")

    def run(self, stages: List[str] = DEFAULT_STAGES, force: bool = False,
            log: bool = True) -> Dict[str, Any]:
        started = datetime.now(timezone.utc)
        record: Dict[str, Any] = {
            'source': 'pipeline', 'stages': list(stages), 'force': force,
            'started_at': started, 'results': {}, 'status': 'running',
        }
        # The spaCy transformer must be loaded before faiss is imported (see
        # index.py), so make sure it is resident before any stage runs.
        if 'entities' in stages:
            self.extractor

        for stage in stages:
            stage_started = datetime.now(timezone.utc)
            try:
                result = self.run_stage(stage, force=force)
                result['seconds'] = round((datetime.now(timezone.utc) - stage_started).total_seconds(), 1)
                record['results'][stage] = result
                logger.info(f"stage {stage}: {result}")
            except Exception as e:
                record['status'] = 'failed'
                record['error'] = f"{stage}: {type(e).__name__}: {e}"
                record['traceback'] = traceback.format_exc()[-2000:]
                logger.error(record['error'])
                break
        else:
            record['status'] = 'ok'

        record['finished_at'] = datetime.now(timezone.utc)
        record['duration_s'] = round((record['finished_at'] - started).total_seconds(), 1)
        if log:
            self.db['runs'].insert_one(dict(record))
        record.pop('_id', None)
        return record

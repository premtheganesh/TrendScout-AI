"""
TrendScout AI REST API.

    python src/api/main.py
    http://localhost:8000/docs
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Dict, Optional, Any
import logging
import re

from src.config import get_settings
from src.corpus.types import COLLECTION, TYPE_NAMES
from src.search.document_text import document_title, document_url
from src.search.hybrid_search import HybridSearchEngine
from src.database.neo4j_client import Neo4jClient
from src.embeddings.embedding_generator import EmbeddingGenerator
from src.rag import RAGPipeline
from src.rag.pipeline import MAX_SINCE_DAYS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models and indexes once at boot; close connections on exit."""
    global search_engine, neo4j_client, embedding_generator, rag_pipeline

    logger.info("Starting TrendScout AI API...")

    try:
        logger.info("Loading hybrid search engine...")
        search_engine = HybridSearchEngine()

        # Reuse the loaded model rather than a second 440MB copy.
        embedding_generator = search_engine.generator

        logger.info("Search services initialized successfully!")

    except Exception as e:
        logger.error(f"Failed to initialize search services: {e}")
        raise

    # Neo4j is optional; graph endpoints return 503 when it is unreachable
    # but search endpoints still work fine.
    try:
        logger.info("Connecting to Neo4j...")
        neo4j_client = Neo4jClient()
        if neo4j_client.available:
            logger.info("Neo4j connected")
            search_engine.graph.neo4j = neo4j_client
        else:
            logger.warning("Neo4j unavailable — graph endpoints will return 503")
    except Exception as e:
        logger.warning(f"Neo4j init failed (graph endpoints disabled): {e}")

    try:
        logger.info("Initializing RAG pipeline...")
        rag_pipeline = RAGPipeline(search_engine)
        if rag_pipeline.llm_available:
            logger.info(f"RAG ready (model: {rag_pipeline.llm.model})")
        else:
            logger.warning("RAG running without an LLM — /chat returns sources only")
    except Exception as e:
        logger.warning(f"RAG init failed: {e}")
        rag_pipeline = None

    yield

    # ---- shutdown ----
    logger.info("Shutting down TrendScout AI API...")

    if search_engine:
        search_engine.close()

    if neo4j_client:
        neo4j_client.close()


# Create the FastAPI application instance
app = FastAPI(
    lifespan=lifespan,
    title="TrendScout AI API",
    description="API for AI startup discovery using hybrid search and knowledge graphs",
    version="1.0.0"
)

# - Your Streamlit UI (running on port 8501) wants to call this API (port 8000)
# - Browsers block this by default for security
# - CORS middleware tells browser "it's okay, allow it"
_origins = get_settings().cors_origin_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    # Browsers refuse credentials with a wildcard origin anyway; only allow
    # them when the origins are named.
    allow_credentials='*' not in _origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


class RateLimiter:
    """Sliding one-minute window per client. In-process: fine for one API
    replica, which is all the free tier runs."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits = defaultdict(deque)

    def check(self, key: str) -> bool:
        if self.per_minute <= 0:
            return True
        now = time.monotonic()
        window = self._hits[key]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.per_minute:
            return False
        window.append(now)
        return True


chat_limiter = RateLimiter(get_settings().chat_rate_limit_per_minute)


def require_chat_quota(request: Request):
    client = request.client.host if request.client else 'unknown'
    if not chat_limiter.check(client):
        raise HTTPException(status_code=429,
                            detail=f"rate limit: {chat_limiter.per_minute} chat requests per minute")


# --- Globals, populated at startup ---

# We initialize them inside the lifespan handler, which runs once at boot.
search_engine = None
neo4j_client = None
embedding_generator = None
rag_pipeline = None

# --- Request/response models ---

# Pydantic validates data automatically!
#
#   - User sends: {"top_k": "five"}  (string instead of int)
#   - Your code crashes when trying to use it as int
#
#   - FastAPI sees type: int
#   - Automatically rejects "five" and returns error
#   - Only valid data reaches your code

class SearchRequest(BaseModel):
    """
    Hybrid search. Filters are typed fields, never a raw database query:
    - type: one document type (startup, article, repo, launch, model, paper)
    - location: case-insensitive substring match on the location field
    - source: exact source tag (techcrunch, ycombinator, github, ...)
    - since_days: only documents whose event_at is within the last N days
    Unknown fields are rejected.
    """
    query: str = Field(max_length=500)
    type: Optional[str] = None
    location: Optional[str] = Field(default=None, max_length=100)
    source: Optional[str] = Field(default=None, max_length=50)
    since_days: Optional[int] = Field(default=None, ge=1, le=MAX_SINCE_DAYS)
    top_k: int = Field(default=10, ge=1, le=50)
    use_keyword: bool = True      # BM25 lexical channel
    use_semantic: bool = True     # E5 + FAISS dense channel
    use_graph: bool = True        # shared-entity graph expansion

    model_config = ConfigDict(extra='forbid', json_schema_extra={
        "example": {
            "query": "AI music generation startup",
            "type": "startup",
            "since_days": 30,
            "top_k": 5
        }
    })

    def mongo_filters(self) -> Optional[Dict]:
        filters: Dict = {}
        if self.location:
            filters['location'] = {'$regex': re.escape(self.location), '$options': 'i'}
        if self.source:
            filters['source'] = self.source
        if self.since_days:
            filters['event_at'] = {'$gte': datetime.now(timezone.utc) - timedelta(days=self.since_days)}
        return filters or None


class SearchResult(BaseModel):
    """
    Response model for search results

    `ranks` gives this document's position in each channel that found it.
    """
    doc_id: str
    type: str
    rrf_score: Optional[float] = None
    ranks: Optional[Dict] = None
    channel_scores: Optional[Dict] = None
    shared_entities: Optional[List[str]] = None
    title: Optional[str] = None
    url: Optional[str] = None
    document: Dict


class ChatRequest(BaseModel):
    """Request for the RAG /chat endpoint"""
    question: str = Field(max_length=2000)
    top_k: int = Field(default=8, ge=1, le=20)
    history: Optional[List[Dict[str, str]]] = Field(default=None, max_length=20)
    use_planner: bool = True

    model_config = ConfigDict(extra='forbid')

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "question": "Which AI startups in San Francisco raised a Series B?",
            "top_k": 8
        }
    })


class ChatSource(BaseModel):
    """One cited source backing an answer"""
    n: int
    doc_id: str
    type: str
    title: str
    url: str = ""
    snippet: str = ""
    rrf_score: float = 0.0
    ranks: Dict = Field(default_factory=dict)
    shared_entities: List[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """A grounded answer plus the sources it cites"""
    question: str
    answer: str
    sources: List[ChatSource]
    search_query: str
    plan: Dict
    used_llm_planner: bool


class SimilarDocRequest(BaseModel):
    """Request for finding similar documents"""
    doc_id: str = Field(max_length=24)
    top_k: int = Field(default=5, ge=1, le=20)

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "doc_id": "507f1f77bcf86cd799439011",
            "top_k": 5
        }
    })


def require_admin(authorization: Optional[str] = Header(default=None)):
    """Bearer ADMIN_TOKEN. 503 when no token is configured at all, so an
    unset token can never mean 'open'."""
    token = get_settings().admin_token
    if not token:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN is not configured")
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


def require_neo4j():
    """Raise 503 if Neo4j is not available."""
    if neo4j_client is None or not neo4j_client.available:
        raise HTTPException(
            status_code=503,
            detail="Neo4j is currently unavailable."
        )


class CypherQueryRequest(BaseModel):
    """Read-only Cypher, admin token required."""
    query: str = Field(max_length=4000)
    parameters: Optional[Dict] = None

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "query": "MATCH (s:Startup)-[:MENTIONS]->(e:Entity {entity_type: 'ORG'}) RETURN s.name, e.entity_text LIMIT 5"
        }
    })


_CYPHER_WRITE = re.compile(r'\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|CALL|LOAD\s+CSV|FOREACH)\b', re.IGNORECASE)


# --- Endpoints ---

@app.get("/")
def root():
    """
    Health check endpoint

    Returns basic info about the API
    Try: http://localhost:8000/
    """
    return {
        "message": "TrendScout AI API is running!",
        "version": "1.0.0",
        "endpoints": {
            "chat": "/chat",
            "search": "/search",
            "similar": "/similar",
            "graph_query": "/graph/query",
            "entities": "/graph/entities",
            "stats": "/stats",
            "documents": "/documents",
            "digests": "/digests",
            "funding": "/funding",
            "companies": "/companies",
            "trends": "/trends",
            "health": "/health",
            "meta": "/meta",
            "admin_reload": "/admin/reload",
            "docs": "/docs"
        }
    }


# --- Search ---

@app.post("/search", response_model=List[SearchResult])
def hybrid_search(request: SearchRequest):
    """
    MAIN ENDPOINT: Hybrid Search

    This wraps your HybridSearchEngine.search() method!

    How it works:
    1. User sends JSON: {"query": "AI", "top_k": 5}
    2. Pydantic validates it → creates SearchRequest object
    3. We call your existing search_engine.search()
    4. Return results → FastAPI converts to JSON automatically

    Try in docs: http://localhost:8000/docs → POST /search
    """

    try:
        if request.type is not None and request.type not in TYPE_NAMES:
            raise HTTPException(
                status_code=422,
                detail=f"type must be one of {list(TYPE_NAMES)}")

        logger.info(f"Search request: query='{request.query}', type={request.type}")

        results = search_engine.search(
            query=request.query,
            doc_type=request.type,
            filters=request.mongo_filters(),
            top_k=request.top_k,
            use_keyword=request.use_keyword,
            use_semantic=request.use_semantic,
            use_graph=request.use_graph
        )

        logger.info(f"Found {len(results)} results")

        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_chat_quota)])
def chat(request: ChatRequest):
    """
    Ask a question, get an answer cited against the retrieved documents.

    Pass `history` as [{"role": "user"|"assistant", "content": "..."}] for
    follow-up questions.
    """
    if rag_pipeline is None:
        raise HTTPException(
            status_code=503,
            detail="RAG pipeline failed to initialize. Check the server logs."
        )

    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")

    try:
        logger.info(f"Chat request: {request.question!r}")
        result = rag_pipeline.answer(
            question=request.question,
            top_k=request.top_k,
            history=request.history,
            use_planner=request.use_planner,
        )
        return result.to_dict()

    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/similar", response_model=List[SearchResult])
def find_similar_documents(request: SimilarDocRequest):
    """
    Find documents similar to a given document

    Uses vector embeddings to find semantically similar content
    Perfect for "More like this" features
    """

    try:
        if not ObjectId.is_valid(request.doc_id):
            raise HTTPException(status_code=404, detail="Document not found")
        doc = search_engine.documents.find_one({'_id': ObjectId(request.doc_id)})

        if not doc:
            # 404 error for "not found"
            raise HTTPException(status_code=404, detail="Document not found")

        # Get document text
        description = doc.get('description', '') or doc.get('name', '') or doc.get('title', '')

        if not description:
            raise HTTPException(status_code=400, detail="Document has no text content")

        # Same type as the source document, +1 because the first hit is itself
        hits = search_engine.semantic_search(
            query=description,
            doc_type=doc.get('type'),
            top_k=request.top_k + 1
        )
        hits = [h for h in hits if h['doc_id'] != request.doc_id][:request.top_k]

        # semantic_search returns bare hits; the response model wants the
        # hydrated shape /search returns.
        documents = search_engine._fetch_documents([h['doc_id'] for h in hits])
        results = []
        for hit in hits:
            hydrated = documents.get(hit['doc_id'])
            if hydrated is None:
                continue
            results.append({
                'doc_id': hit['doc_id'],
                'type': hit['type'],
                'rrf_score': None,
                'ranks': {'semantic': len(results) + 1},
                'channel_scores': {'semantic': hit['score']},
                'title': document_title(hydrated, hit['type']),
                'url': document_url(hydrated, hit['type']),
                'document': hydrated,
            })

        logger.info(f"Found {len(results)} similar documents")
        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Similar search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Knowledge graph ---

@app.post("/graph/query", dependencies=[Depends(require_admin)])
def execute_cypher_query(request: CypherQueryRequest):
    """
    Run a read-only Cypher query. Admin token required; write clauses are
    rejected before the query reaches Neo4j.

    Example queries to try:

    1. Find startups mentioning AI:
    {
        "query": "MATCH (s:Startup)-[:MENTIONS]->(e:Entity) WHERE e.entity_text CONTAINS 'AI' RETURN s.name, e.entity_text LIMIT 10"
    }

    2. Most mentioned entities:
    {
        "query": "MATCH (e:Entity) RETURN e.entity_text, e.mention_count ORDER BY e.mention_count DESC LIMIT 10"
    }
    """

    if _CYPHER_WRITE.search(request.query):
        raise HTTPException(status_code=400, detail="only read-only Cypher is allowed here")
    require_neo4j()
    try:
        logger.info(f"Executing Cypher query: {request.query[:100]}...")

        # Run query through your Neo4jClient
        results = neo4j_client.run_query(request.query, request.parameters)

        # Convert Neo4j records to dictionaries
        formatted_results = []
        for record in results:
            formatted_results.append(dict(record))

        logger.info(f"Query returned {len(formatted_results)} results")

        return {
            "query": request.query,
            "results": formatted_results,
            "count": len(formatted_results)
        }

    except Exception as e:
        logger.error(f"Cypher query error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graph/entities")
def get_top_entities(
    entity_type: Optional[str] = Query(default=None, max_length=20),
    limit: int = Query(default=10, ge=1, le=100),
):
    """
    Most-mentioned entities. Read from MongoDB's canonical_entities — the
    same links graph-expansion retrieval uses — so this works with Neo4j
    off, which is how the deployed site runs.

    Try: /graph/entities?entity_type=ORG&limit=5
    """
    query: Dict[str, Any] = {}
    if entity_type:
        query['entity_type'] = entity_type.upper()
    rows = search_engine.mongo.db.canonical_entities.find(
        query, {'entity_text': 1, 'entity_type': 1, 'mention_count': 1, 'document_count': 1}
    ).sort([('mention_count', -1), ('entity_text', 1)]).limit(limit)
    entities = [{'entity': r['entity_text'], 'type': r['entity_type'],
                 'mentions': r.get('mention_count', 0), 'documents': r.get('document_count', 0)}
                for r in rows]
    return {"entities": entities, "count": len(entities)}


@app.get("/graph/startup/{startup_name}")
def get_startup_entities(startup_name: str):
    """
    Entities mentioned by one startup, and the other documents that share
    them (the graph neighbourhood). Exact name match, case-insensitive.

    Try: /graph/startup/Suno
    """
    db = search_engine.mongo.db
    doc = db.documents.find_one(
        {'type': 'startup', 'name': {'$regex': f'^{re.escape(startup_name)}$', '$options': 'i'}},
        {'embedding': 0})
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Startup '{startup_name}' not found")

    entities = sorted(
        ({'entity': e.get('entity_text'), 'type': e.get('entity_type'), 'count': e.get('count', 1)}
         for e in (doc.get('entities') or []) if e.get('entity_text')),
        key=lambda e: (e['type'] or '', e['entity']))

    neighbours = search_engine.graph.expand([str(doc['_id'])], top_k=10)
    hydrated = search_engine._fetch_documents([n['doc_id'] for n in neighbours])
    for n in neighbours:
        d = hydrated.get(n['doc_id'])
        n['title'] = document_title(d, n['type']) if d else ''
        n['url'] = document_url(d, n['type']) if d else ''

    return {
        "startup": doc.get('name'),
        "doc_id": str(doc['_id']),
        "entities": entities,
        "count": len(entities),
        "neighbours": neighbours,
    }


# --- Documents ---

def _public(doc: Dict) -> Dict:
    """A document as the API shows it: no vectors, no NER payload."""
    out = {k: v for k, v in doc.items() if k not in ('embedding', 'entities')}
    out['_id'] = str(doc['_id'])
    out['title'] = document_title(doc, doc.get('type'))
    out['url'] = document_url(doc, doc.get('type'))
    return out


@app.get("/documents")
def list_documents(
    type: Optional[List[str]] = Query(default=None),
    source: Optional[str] = Query(default=None, max_length=50),
    since_days: Optional[int] = Query(default=None, ge=1, le=MAX_SINCE_DAYS),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
):
    """Newest documents first by event_at. `type` may repeat."""
    query: Dict[str, Any] = {}
    if type:
        bad = [t for t in type if t not in TYPE_NAMES]
        if bad:
            raise HTTPException(status_code=422, detail=f"unknown type(s) {bad}; choose from {list(TYPE_NAMES)}")
        query['type'] = {'$in': type}
    if source:
        query['source'] = source
    if since_days:
        query['event_at'] = {'$gte': datetime.now(timezone.utc) - timedelta(days=since_days)}
    else:
        query['event_at'] = {'$ne': None}

    cursor = (search_engine.documents.find(query, {'embedding': 0, 'entities': 0})
              .sort([('event_at', -1), ('first_seen_at', -1)])
              .skip(offset).limit(limit))
    items = [_public(d) for d in cursor]
    return {
        'items': items,
        'count': len(items),
        'total': search_engine.documents.count_documents(query),
        'offset': offset,
        'limit': limit,
    }


@app.get("/documents/{doc_id}")
def get_document(doc_id: str):
    if not ObjectId.is_valid(doc_id):
        raise HTTPException(status_code=404, detail="Document not found")
    doc = search_engine.documents.find_one({'_id': ObjectId(doc_id)}, {'embedding': 0})
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    public = _public(doc)
    public['entities'] = doc.get('entities') or []
    return public


# --- Companies and funding ---

@app.get("/funding")
def list_funding(
    since_days: Optional[int] = Query(default=None, ge=1, le=MAX_SINCE_DAYS),
    min_amount_usd: Optional[float] = Query(default=None, ge=0),
    round: Optional[str] = Query(default=None, max_length=20),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Extracted funding rounds, largest first."""
    query: Dict[str, Any] = {'confidence': {'$in': ['high', 'medium']}}
    if since_days:
        query['announced_at'] = {'$gte': datetime.now(timezone.utc) - timedelta(days=since_days)}
    if min_amount_usd is not None:
        query['amount_usd'] = {'$gte': min_amount_usd}
    if round:
        query['round'] = round.lower()
    rows = list(search_engine.mongo.db.funding_rounds.find(query)
                .sort([('amount_usd', -1), ('announced_at', -1)]).limit(limit))
    return {'items': rows, 'count': len(rows),
            'total': search_engine.mongo.db.funding_rounds.count_documents(query)}


@app.get("/companies")
def list_companies(
    q: Optional[str] = Query(default=None, max_length=100),
    sort: str = Query(default='funding', pattern='^(funding|documents|name)$'),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
):
    query: Dict[str, Any] = {}
    if q:
        query['name'] = {'$regex': re.escape(q), '$options': 'i'}
    order = {'funding': [('funding_total_usd', -1), ('document_count', -1)],
             'documents': [('document_count', -1)], 'name': [('name', 1)]}[sort]
    rows = list(search_engine.mongo.db.companies.find(query).sort(order).skip(offset).limit(limit))
    return {'items': rows, 'count': len(rows),
            'total': search_engine.mongo.db.companies.count_documents(query),
            'offset': offset, 'limit': limit}


@app.get("/companies/{slug}")
def get_company(slug: str):
    db = search_engine.mongo.db
    company = db.companies.find_one({'_id': slug})
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    company['rounds'] = list(db.funding_rounds.find({'_id': {'$in': company.get('rounds', [])}})
                             .sort([('announced_at', -1)]))
    linked = []
    for doc_type, ids in (company.get('doc_ids') or {}).items():
        for doc in db.documents.find({'_id': {'$in': [ObjectId(i) for i in ids if ObjectId.is_valid(i)]}},
                                     {'embedding': 0, 'entities': 0}):
            linked.append(_public(doc))
    linked.sort(key=lambda d: (d.get('event_at') or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    company['documents'] = linked
    return company


# --- Trends ---

@app.get("/trends")
def trends(week: Optional[str] = Query(default=None, pattern=r'^\d{4}-W\d{2}$'),
           limit: int = Query(default=20, ge=1, le=100)):
    """Rising and most-mentioned topics for an ISO week (default: current)."""
    from src.digest.weeks import week_id
    from src.trends.compute import rising_topics
    week = week or week_id(datetime.now(timezone.utc).date())
    return rising_topics(search_engine.mongo.db, week, limit=limit)


@app.get("/trends/velocity")
def trends_velocity(type: str = Query(default='repo', pattern='^(repo|model|paper|launch)$'),
                    days: int = Query(default=14, ge=2, le=90),
                    limit: int = Query(default=20, ge=1, le=100)):
    """Documents that gained the most stars / likes / upvotes / points in the window."""
    from src.trends.compute import velocity
    result = velocity(search_engine.mongo.db, type, days=days, limit=limit)
    ids = [ObjectId(r['doc_id']) for r in result['items'] if ObjectId.is_valid(r['doc_id'])]
    docs = {str(d['_id']): _public(d) for d in
            search_engine.documents.find({'_id': {'$in': ids}}, {'embedding': 0, 'entities': 0})}
    for row in result['items']:
        doc = docs.get(row['doc_id'])
        if doc:
            row['title'] = doc['title']
            row['url'] = doc['url']
    return result


# --- Digests ---

def _digest_summary(d: Dict) -> Dict:
    return {
        'week': d['week'], 'week_start': d.get('week_start'), 'week_end': d.get('week_end'),
        'generated_at': d.get('generated_at'), 'counts': d.get('counts', {}),
        'bullets': sum(sec.get('bullets', 0) for sec in d.get('sections', [])),
    }


@app.get("/digests")
def list_digests(limit: int = Query(default=12, ge=1, le=52)):
    rows = search_engine.mongo.db.digests.find({}, {'sections': 0, 'input_doc_ids': 0}) \
        .sort('week_start', -1).limit(limit)
    items = [_digest_summary(d) for d in rows]
    return {'items': items, 'count': len(items)}


@app.get("/digests/latest")
def latest_digest():
    d = search_engine.mongo.db.digests.find_one({}, sort=[('week_start', -1)])
    if d is None:
        raise HTTPException(status_code=404, detail="no digest has been generated yet")
    return d


@app.get("/digests/{week}")
def get_digest(week: str):
    d = search_engine.mongo.db.digests.find_one({'_id': week})
    if d is None:
        raise HTTPException(status_code=404, detail=f"no digest for {week}")
    return d


# --- Operations ---

@app.get("/health")
def health():
    """Liveness plus the two numbers that say whether search can work."""
    return {
        "status": "ok",
        "documents": search_engine.documents.count_documents({}),
        "vectors": search_engine.faiss_index.ntotal,
        "index_built_at": search_engine.built_at,
    }


@app.get("/meta")
def meta():
    """Freshness: what is indexed, when, and what each source last did."""
    db = search_engine.mongo.db
    by_type = {name: 0 for name in TYPE_NAMES}
    for row in search_engine.documents.aggregate(
            [{'$group': {'_id': '$type', 'n': {'$sum': 1}}}]):
        by_type[row['_id'] or 'unknown'] = row['n']

    newest = search_engine.documents.find_one(
        {'event_at': {'$ne': None}}, {'event_at': 1}, sort=[('event_at', -1)])
    last_seen = search_engine.documents.find_one({}, {'last_seen_at': 1},
                                                 sort=[('last_seen_at', -1)])

    sources = []
    for row in db.runs.aggregate([
        {'$match': {'source': {'$ne': 'pipeline'}, 'dry_run': {'$ne': True}}},
        {'$sort': {'started_at': -1}},
        {'$group': {'_id': '$source', 'last': {'$first': '$$ROOT'}}},
        {'$sort': {'_id': 1}},
    ]):
        last = row['last']
        sources.append({
            'source': row['_id'],
            'type': last.get('type'),
            'last_run_at': last.get('started_at'),
            'status': last.get('status'),
            'new': last.get('new', 0),
            'changed': last.get('changed', 0),
            'error': last.get('error'),
        })
    last_pipeline = db.runs.find_one({'source': 'pipeline'}, sort=[('started_at', -1)])

    return {
        "documents": {"total": sum(by_type.values()), "by_type": by_type},
        "entities": db.canonical_entities.count_documents({}),
        "index": {
            "built_at": search_engine.built_at,
            "vectors": search_engine.faiss_index.ntotal,
            "dimension": search_engine.faiss_index.d,
        },
        "newest_event_at": newest['event_at'] if newest else None,
        "last_ingested_at": last_seen.get('last_seen_at') if last_seen else None,
        "sources": sources,
        "last_pipeline": {
            "started_at": last_pipeline.get('started_at'),
            "status": last_pipeline.get('status'),
            "stages": list((last_pipeline.get('results') or {}).keys()),
        } if last_pipeline else None,
    }


@app.post("/admin/reload", dependencies=[Depends(require_admin)])
def admin_reload():
    """Re-read the index files after a pipeline run — no restart needed."""
    try:
        search_engine.reload()
    except Exception as e:
        logger.error(f"Reload failed: {e}")
        raise HTTPException(status_code=500, detail=f"reload failed: {e}")
    return {
        "reloaded": True,
        "vectors": search_engine.faiss_index.ntotal,
        "bm25_documents": len(search_engine.bm25),
        "index_built_at": search_engine.built_at,
    }


# --- Statistics ---

@app.get("/stats")
def get_statistics():
    """
    Get overall system statistics

    Shows what data you have in MongoDB, Neo4j, and FAISS
    """

    try:
        by_type = {name: 0 for name in TYPE_NAMES}
        for row in search_engine.documents.aggregate(
                [{'$group': {'_id': '$type', 'n': {'$sum': 1}}}]):
            by_type[row['_id'] or 'unknown'] = row['n']

        # FAISS index size
        faiss_count = search_engine.faiss_index.ntotal

        # Neo4j counts, absent when it is unreachable
        neo4j_stats = {"status": "unavailable", "total_nodes": 0, "entities": 0, "relationships": 0}
        if neo4j_client and neo4j_client.available:
            try:
                node_count = neo4j_client.get_node_count()
                rel_result = neo4j_client.run_query("MATCH ()-[r]->() RETURN count(r) as count")
                relationship_count = rel_result[0]['count'] if rel_result else 0
                entity_result = neo4j_client.run_query("MATCH (e:Entity) RETURN count(e) as count")
                entity_count = entity_result[0]['count'] if entity_result else 0
                neo4j_stats = {
                    "status": "connected",
                    "total_nodes": node_count,
                    "entities": entity_count,
                    "relationships": relationship_count,
                }
            except Exception as neo4j_err:
                logger.warning(f"Neo4j stats failed: {neo4j_err}")

        return {
            "documents": {
                "total": sum(by_type.values()),
                "by_type": by_type,
            },
            "neo4j": neo4j_stats,
            "embeddings": {
                "vectors": faiss_count,
                "dimension": search_engine.faiss_index.d
            }
        }

    except Exception as e:
        logger.error(f"Statistics error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Entry point ---

if __name__ == "__main__":
    import uvicorn

    print("=" * 70)
    print("STARTING TRENDSCOUT AI API")
    print("=" * 70)
    print("\n API will be available at:")
    print("  - Main API: http://localhost:8000")
    print("  - Interactive docs: http://localhost:8000/docs")
    print("  - Alternative docs: http://localhost:8000/redoc")
    print("\n Learning Guide:")
    print("  1. Open the docs URL in your browser")
    print("  2. Click on each endpoint to see what it does")
    print("  3. Click 'Try it out' to test with real data")
    print("4. Check this file's comments (marked with )")
    print("\n Press CTRL+C to stop the server")
    print("=" * 70)

    uvicorn.run(
        "main:app", # "main"= this filename, "app"= FastAPI instance
        host="0.0.0.0", # Accessible from anywhere (localhost, other computers)
        port=8000, # Port number
        reload=True # Auto-restart when code changes (dev only!)
    )

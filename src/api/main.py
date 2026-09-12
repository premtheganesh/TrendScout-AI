"""
TrendScout AI REST API.

    python src/api/main.py
    http://localhost:8000/docs
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Dict, Optional, Any
import logging

from src.config import get_settings
from src.corpus.types import COLLECTION, TYPE_NAMES
from src.search.document_text import document_title, document_url
from src.search.hybrid_search import HybridSearchEngine
from src.database.neo4j_client import Neo4jClient
from src.embeddings.embedding_generator import EmbeddingGenerator
from src.rag import RAGPipeline

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, specify exact origins like ["http://localhost:8501"]
    allow_credentials=True,
    allow_methods=["*"],  # Allow GET, POST, etc.
    allow_headers=["*"],  # Allow all headers
)


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
    Request model for /search endpoint

    - query: required string
    - type: optional document type (startup, article, repo)
    - filters: optional MongoDB filter on document fields
    - top_k: optional int with default value 10
    """
    query: str
    type: Optional[str] = None
    filters: Optional[Dict] = None
    top_k: int = 10
    use_keyword: bool = True      # BM25 lexical channel
    use_semantic: bool = True     # E5 + FAISS dense channel
    use_graph: bool = True        # shared-entity graph expansion

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "query": "AI music generation startup",
            "type": "startup",
            "top_k": 5
        }
    })


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
    question: str
    top_k: int = 8
    history: Optional[List[Dict[str, str]]] = None
    use_planner: bool = True

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
    doc_id: str
    top_k: int = 5

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
    """Request for executing Neo4j Cypher queries"""
    query: str
    parameters: Optional[Dict] = None

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "query": "MATCH (s:Startup)-[:MENTIONS]->(e:Entity {entity_type: 'ORG'}) RETURN s.name, e.entity_text LIMIT 5"
        }
    })


# --- Endpoints ---

@app.get("/")
async def root():
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
            "health": "/health",
            "meta": "/meta",
            "admin_reload": "/admin/reload",
            "docs": "/docs"
        }
    }


# --- Search ---

@app.post("/search", response_model=List[SearchResult])
async def hybrid_search(request: SearchRequest):
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
            filters=request.filters,
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


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
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
async def find_similar_documents(request: SimilarDocRequest):
    """
    Find documents similar to a given document

    Uses vector embeddings to find semantically similar content
    Perfect for "More like this" features
    """

    try:
        from bson import ObjectId

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

@app.post("/graph/query")
async def execute_cypher_query(request: CypherQueryRequest):
    """
    Execute custom Neo4j Cypher queries

    This exposes direct access to your knowledge graph!

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
async def get_top_entities(
    entity_type: Optional[str] = None,
    limit: int = Query(default=10, le=100) # Max 100 results
):
    """
    Get most mentioned entities from knowledge graph

    Parameters:
    - entity_type: Filter by type (ORG, PERSON, PRODUCT, etc.)
    - limit: Number of results (max 100)

    Try: http://localhost:8000/graph/entities?entity_type=ORG&limit=5
    """

    require_neo4j()
    try:
        # Build Cypher query
        if entity_type:
            query = """
            MATCH (e:Entity {entity_type: $entity_type})
            RETURN e.entity_text AS entity, e.entity_type AS type, e.mention_count AS mentions
            ORDER BY e.mention_count DESC
            LIMIT $limit
            """
            parameters = {"entity_type": entity_type, "limit": limit}
        else:
            query = """
            MATCH (e:Entity)
            RETURN e.entity_text AS entity, e.entity_type AS type, e.mention_count AS mentions
            ORDER BY e.mention_count DESC
            LIMIT $limit
            """
            parameters = {"limit": limit}

        results = neo4j_client.run_query(query, parameters)
        entities = [dict(record) for record in results]

        return {
            "entities": entities,
            "count": len(entities)
        }

    except Exception as e:
        logger.error(f"Entity query error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graph/startup/{startup_name}")
async def get_startup_entities(startup_name: str):
    """
    Get all entities mentioned by a specific startup

    Try: http://localhost:8000/graph/startup/Suno
    """

    require_neo4j()
    try:
        query = """
        MATCH (s:Startup {name: $startup_name})-[:MENTIONS]->(e:Entity)
        RETURN e.entity_text AS entity, e.entity_type AS type
        ORDER BY e.entity_type, e.entity_text
        """

        results = neo4j_client.run_query(query, {"startup_name": startup_name})
        entities = [dict(record) for record in results]

        if not entities:
            raise HTTPException(
                status_code=404,
                detail=f"Startup '{startup_name}' not found or has no entities"
            )

        return {
            "startup": startup_name,
            "entities": entities,
            "count": len(entities)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Startup entities error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
async def get_statistics():
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

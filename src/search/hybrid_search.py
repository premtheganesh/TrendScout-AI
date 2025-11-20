"""
Hybrid Search Engine

Combines keyword search (MongoDB) + semantic search (FAISS) for best results.

What it does:
- Keyword search: Find exact matches, filter by fields (location, funding, etc.)
- Semantic search: Find similar content by meaning
- Combine results: Use Reciprocal Rank Fusion (RRF) to merge rankings

Why hybrid is better:
- Keyword alone: Misses similar meanings
- Semantic alone: Can miss exact matches
- Hybrid: Gets best of both worlds!

Example:
    Query: "AI music startup in Cambridge"

    Keyword finds: Startups in Cambridge
    Semantic finds: AI music related startups
    Combined result: AI music startups in Cambridge (best match!)
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.database.mongo_client import MongoDBClient
from src.embeddings.embedding_generator import EmbeddingGenerator
import faiss
import numpy as np
import pickle
from typing import List, Dict, Optional
import logging
from bson import ObjectId

logger = logging.getLogger(__name__)


class HybridSearchEngine:
    """
    Hybrid search engine combining keyword + semantic search

    Features:
    - Keyword search via MongoDB
    - Semantic search via FAISS
    - Reciprocal Rank Fusion (RRF) for combining results
    - Support for filters (location, collection, etc.)
    """

    def __init__(self):
        """
        Initialize hybrid search engine

        Loads:
        1. MongoDB client (for keyword search)
        2. Embedding generator (for query encoding)
        3. FAISS index (for semantic search)
        4. Metadata (for result lookup)
        """
        logger.info("Initializing Hybrid Search Engine...")

        # MongoDB client
        self.mongo = MongoDBClient()

        # Embedding generator
        self.generator = EmbeddingGenerator()

        # Load FAISS index
        data_dir = os.path.join(os.path.dirname(__file__), '../../data')
        index_path = os.path.join(data_dir, 'faiss_index.bin')
        metadata_path = os.path.join(data_dir, 'faiss_metadata.pkl')

        if not os.path.exists(index_path):
            raise FileNotFoundError(
                f"FAISS index not found at {index_path}. "
                "Run scripts/generate_embeddings.py first!"
            )

        self.faiss_index = faiss.read_index(index_path)

        with open(metadata_path, 'rb') as f:
            self.faiss_metadata = pickle.load(f)

        logger.info(f"✅ Loaded FAISS index with {self.faiss_index.ntotal} vectors")

    def _clean_document(self, doc: Dict) -> Dict:
        """
        Convert MongoDB document to JSON-serializable format
        
        Converts ObjectId to string and handles other MongoDB types
        """
        if doc is None:
            return None
        
        # Create a copy to avoid modifying original
        cleaned = doc.copy()
        
        # Convert _id from ObjectId to string
        if '_id' in cleaned:
            cleaned['_id'] = str(cleaned['_id'])
        
        return cleaned

    def keyword_search(
        self,
        query: str,
        collection: str = None,
        filters: Dict = None,
        top_k: int = 20
    ) -> List[Dict]:
        """
        Perform keyword search using MongoDB

        Args:
            query: Search query text
            collection: Which collection to search ('startups', 'articles', 'github_repos')
                       If None, searches all collections
            filters: Additional MongoDB filters
                    Example: {'location': 'Cambridge', 'funding_amount': {'$exists': True}}
            top_k: Number of results to return

        Returns:
            List of documents with scores

        How it works:
            1. Build MongoDB query with text search + filters
            2. Execute search
            3. Return ranked results
        """

        results = []

        # Determine which collections to search
        collections_to_search = [collection] if collection else ['startups', 'articles', 'github_repos']

        for coll_name in collections_to_search:
            # Build MongoDB query
            mongo_query = {}

            # Add text search if query provided
            if query and query.strip():
                mongo_query['$text'] = {'$search': query}

            # Add additional filters
            if filters:
                mongo_query.update(filters)

            # Execute search
            cursor = self.mongo.db[coll_name].find(
                mongo_query,
                {'score': {'$meta': 'textScore'}} if query and query.strip() else {}
            )

            # Sort by text score if we have a query
            if query and query.strip():
                cursor = cursor.sort([('score', {'$meta': 'textScore'})]).limit(top_k)
            else:
                cursor = cursor.limit(top_k)

            # Collect results
            for doc in cursor:
                results.append({
                    'doc_id': str(doc['_id']),
                    'collection': coll_name,
                    'score': doc.get('score', 0),
                    'document': self._clean_document(doc)
                })

        # Sort by score (highest first)
        results.sort(key=lambda x: x['score'], reverse=True)

        return results[:top_k]

    def semantic_search(
        self,
        query: str,
        collection: str = None,
        top_k: int = 20
    ) -> List[Dict]:
        """
        Perform semantic search using FAISS

        Args:
            query: Search query text
            collection: Filter by collection (optional)
            top_k: Number of results to return

        Returns:
            List of documents with similarity scores

        How it works:
            1. Convert query to embedding vector
            2. Search FAISS index for similar vectors
            3. Return ranked results
        """

        # Step 1: Convert query to embedding
        query_embedding = self.generator.generate_embedding(query)
        query_embedding = query_embedding.reshape(1, -1)  # Shape: (1, 384)

        # Step 2: Search FAISS index
        # Search for more candidates if filtering by collection
        search_k = top_k * 3 if collection else top_k
        similarities, indices = self.faiss_index.search(query_embedding, search_k)

        # Step 3: Build results
        results = []

        for idx, score in zip(indices[0], similarities[0]):
            doc_id = self.faiss_metadata['ids'][idx]
            meta = self.faiss_metadata['metadata'][idx]
            doc_collection = meta['collection']

            # Filter by collection if specified
            if collection and doc_collection != collection:
                continue

            # Get full document from MongoDB
            doc = self.mongo.db[doc_collection].find_one({'_id': ObjectId(doc_id)})

            if doc:
                results.append({
                    'doc_id': str(doc['_id']),
                    'collection': doc_collection,
                    'score': float(score),
                    'document': self._clean_document(doc)
                })

            # Stop if we have enough results
            if len(results) >= top_k:
                break

        return results

    def reciprocal_rank_fusion(
        self,
        keyword_results: List[Dict],
        semantic_results: List[Dict],
        k: int = 60
    ) -> List[Dict]:
        """
        Combine keyword and semantic results using Reciprocal Rank Fusion (RRF)

        RRF Formula:
            score = 1 / (k + rank)

        Why RRF:
        - Simple and effective
        - Doesn't require score normalization
        - Documents appearing in both lists get higher scores
        - Used by search engines like Elasticsearch

        Args:
            keyword_results: Results from keyword search
            semantic_results: Results from semantic search
            k: RRF constant (typically 60)

        Returns:
            Combined results sorted by RRF score
        """

        # Dictionary to accumulate scores
        # Key: doc_id, Value: {'score': rrf_score, 'doc': document, 'ranks': {...}}
        combined_scores = {}

        # Process keyword results
        for rank, result in enumerate(keyword_results, 1):
            doc_id = result['doc_id']

            if doc_id not in combined_scores:
                combined_scores[doc_id] = {
                    'score': 0,
                    'document': result['document'],
                    'collection': result['collection'],
                    'ranks': {}
                }

            # RRF score for this result
            rrf_score = 1 / (k + rank)
            combined_scores[doc_id]['score'] += rrf_score
            combined_scores[doc_id]['ranks']['keyword'] = rank

        # Process semantic results
        for rank, result in enumerate(semantic_results, 1):
            doc_id = result['doc_id']

            if doc_id not in combined_scores:
                combined_scores[doc_id] = {
                    'score': 0,
                    'document': result['document'],
                    'collection': result['collection'],
                    'ranks': {}
                }

            # RRF score for this result
            rrf_score = 1 / (k + rank)
            combined_scores[doc_id]['score'] += rrf_score
            combined_scores[doc_id]['ranks']['semantic'] = rank

        # Convert to list and sort by score
        final_results = []
        for doc_id, data in combined_scores.items():
            final_results.append({
                'doc_id': doc_id,
                'collection': data['collection'],
                'rrf_score': data['score'],
                'ranks': data['ranks'],
                'document': data['document']
            })

        # Sort by RRF score (highest first)
        final_results.sort(key=lambda x: x['rrf_score'], reverse=True)

        return final_results

    def search(
        self,
        query: str,
        collection: str = None,
        filters: Dict = None,
        top_k: int = 10,
        use_keyword: bool = True,
        use_semantic: bool = True
    ) -> List[Dict]:
        """
        Main hybrid search function

        Args:
            query: Search query
            collection: Filter by collection ('startups', 'articles', 'github_repos')
            filters: Additional MongoDB filters
            top_k: Number of results to return
            use_keyword: Enable keyword search
            use_semantic: Enable semantic search

        Returns:
            List of ranked results

        Example:
            engine.search(
                query="AI music generation",
                collection="startups",
                filters={'location': {'$regex': 'Cambridge'}},
                top_k=5
            )
        """

        logger.info(f"Searching for: '{query}'")

        # Perform keyword search
        keyword_results = []
        if use_keyword:
            keyword_results = self.keyword_search(query, collection, filters, top_k=20)
            logger.info(f"Keyword search found {len(keyword_results)} results")

        # Perform semantic search
        semantic_results = []
        if use_semantic:
            semantic_results = self.semantic_search(query, collection, top_k=20)
            logger.info(f"Semantic search found {len(semantic_results)} results")

        # Combine results using RRF
        if use_keyword and use_semantic:
            combined_results = self.reciprocal_rank_fusion(keyword_results, semantic_results)
            logger.info(f"Combined results: {len(combined_results)}")
        elif use_keyword:
            combined_results = keyword_results
        elif use_semantic:
            combined_results = semantic_results
        else:
            combined_results = []

        return combined_results[:top_k]

    def format_result(self, result: Dict) -> str:
        """
        Format search result for display

        Args:
            result: Search result dictionary

        Returns:
            Formatted string for printing
        """

        doc = result['document']
        collection = result['collection']

        output = []
        output.append(f"Collection: {collection.upper()}")
        output.append(f"RRF Score: {result.get('rrf_score', 0):.4f}")

        if 'ranks' in result:
            ranks = result['ranks']
            if 'keyword' in ranks:
                output.append(f"Keyword Rank: {ranks['keyword']}")
            if 'semantic' in ranks:
                output.append(f"Semantic Rank: {ranks['semantic']}")

        if collection == 'startups':
            output.append(f"Name: {doc.get('name', 'N/A')}")
            output.append(f"Location: {doc.get('location', 'N/A')}")
            output.append(f"Description: {doc.get('description', 'N/A')[:100]}...")

        elif collection == 'articles':
            output.append(f"Title: {doc.get('title', 'N/A')[:80]}")
            output.append(f"URL: {doc.get('url', 'N/A')}")

        elif collection == 'github_repos':
            output.append(f"Repo: {doc.get('full_name', 'N/A')}")
            output.append(f"Stars: {doc.get('stars', 0)}")
            output.append(f"Description: {doc.get('description', 'N/A')[:100]}...")

        return '\n'.join(output)

    def close(self):
        """Close MongoDB connection"""
        self.mongo.close()


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    """
    Test hybrid search with example queries

    Run: python src/search/hybrid_search.py
    """

    logging.basicConfig(level=logging.INFO)

    print("=" * 70)
    print("HYBRID SEARCH ENGINE - DEMO")
    print("=" * 70)

    # Create search engine
    print("\n[1] Initializing search engine...")
    engine = HybridSearchEngine()
    print("SUCCESS Search engine ready\n")

    # Test queries
    test_queries = [
        {
            'query': 'AI music generation startup',
            'collection': 'startups',
            'top_k': 3
        },
        {
            'query': 'machine learning artificial intelligence',
            'collection': None,
            'top_k': 5
        },
        {
            'query': 'Cambridge',
            'collection': 'startups',
            'filters': {'location': {'$regex': 'Cambridge', '$options': 'i'}},
            'top_k': 3
        }
    ]

    for i, test in enumerate(test_queries, 1):
        print("=" * 70)
        print(f"QUERY {i}: '{test['query']}'")
        if test.get('filters'):
            print(f"Filters: {test['filters']}")
        print("=" * 70)

        results = engine.search(**test)

        print(f"\nTop {len(results)} results:\n")

        for j, result in enumerate(results, 1):
            print(f"{j}. " + "─" * 66)
            print(engine.format_result(result))
            print()

    # Cleanup
    engine.close()

    print("=" * 70)
    print("✅ HYBRID SEARCH DEMO COMPLETE")
    print("=" * 70)

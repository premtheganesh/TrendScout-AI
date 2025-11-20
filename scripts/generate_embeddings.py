"""
Generate Vector Embeddings for All Documents

This script:
1. Reads all documents from MongoDB (startups, articles, github_repos)
2. Generates vector embeddings for their descriptions
3. Saves embeddings back to MongoDB
4. Builds a FAISS index for fast semantic search

Why we're doing this:
- Enable semantic search (find by meaning, not just keywords)
- Power recommendation systems ("find similar startups")
- Enable hybrid search (combine keyword + semantic search)
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database.mongo_client import MongoDBClient
from src.embeddings.embedding_generator import EmbeddingGenerator
import faiss
import numpy as np
import pickle
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def generate_embeddings_for_startups(mongo, generator):
    """
    Generate embeddings for all startup descriptions

    Process:
    1. Read all startups from MongoDB
    2. Extract description text
    3. Generate embeddings using batch processing (fast!)
    4. Save embeddings back to MongoDB

    Why we save to MongoDB:
    - Persistence (don't lose embeddings if script crashes)
    - Can rebuild FAISS index anytime from MongoDB
    - Keep all data in one place
    """

    print("\n" + "=" * 70)
    print("GENERATING EMBEDDINGS FOR STARTUPS")
    print("=" * 70)

    # Step 1: Read all startups
    print("\n[1] Reading startups from MongoDB...")
    startups = list(mongo.db.startups.find())
    print(f"Found {len(startups)} startups")

    if len(startups) == 0:
        print("WARNING: No startups found!")
        return []

    # Step 2: Prepare texts for embedding
    print("\n[2] Preparing texts for embedding...")

    texts = []
    startup_ids = []

    for startup in startups:
        # Get description (the text we want to convert to embedding)
        description = startup.get('description', '')

        # Some startups might not have descriptions
        if not description or description.strip() == '':
            description = startup.get('name', '')  # Use name as fallback

        texts.append(description)
        startup_ids.append(str(startup['_id']))

    print(f"Prepared {len(texts)} texts")

    # Step 3: Generate embeddings (batch processing - super fast!)
    print("\n[3] Generating embeddings...")
    print("This will take ~10-20 seconds...")

    embeddings = generator.generate_embeddings_batch(texts, show_progress=True)

    print(f"Generated {len(embeddings)} embeddings")
    print(f"Embedding shape: {embeddings.shape}")  # Should be (140, 384)

    # Step 4: Save embeddings back to MongoDB
    print("\n[4] Saving embeddings to MongoDB...")

    for i, startup_id in enumerate(startup_ids):
        # Convert numpy array to list (MongoDB can store lists)
        embedding_list = embeddings[i].tolist()

        # Update the startup document with embedding
        mongo.db.startups.update_one(
            {'_id': startups[i]['_id']},
            {'$set': {
                'embedding': embedding_list,
                'embedding_generated_at': datetime.utcnow().isoformat()
            }}
        )

    print(f"Saved {len(startup_ids)} embeddings to MongoDB")

    # Return for FAISS index building
    return {
        'embeddings': embeddings,
        'ids': startup_ids,
        'collection': 'startups',
        'metadata': [{'name': s.get('name', ''), 'description': s.get('description', '')}
                     for s in startups]
    }


def generate_embeddings_for_articles(mongo, generator):
    """
    Generate embeddings for all article descriptions

    Same process as startups, but for articles
    """

    print("\n" + "=" * 70)
    print("GENERATING EMBEDDINGS FOR ARTICLES")
    print("=" * 70)

    # Step 1: Read articles
    print("\n[1] Reading articles from MongoDB...")
    articles = list(mongo.db.articles.find())
    print(f"Found {len(articles)} articles")

    if len(articles) == 0:
        print("WARNING: No articles found!")
        return []

    # Step 2: Prepare texts
    print("\n[2] Preparing texts for embedding...")

    texts = []
    article_ids = []

    for article in articles:
        # Use description or title
        description = article.get('description', '') or article.get('title', '')
        texts.append(description)
        article_ids.append(str(article['_id']))

    print(f"Prepared {len(texts)} texts")

    # Step 3: Generate embeddings
    print("\n[3] Generating embeddings...")
    embeddings = generator.generate_embeddings_batch(texts, show_progress=True)
    print(f"Generated {len(embeddings)} embeddings")

    # Step 4: Save to MongoDB
    print("\n[4] Saving embeddings to MongoDB...")

    for i, article_id in enumerate(article_ids):
        embedding_list = embeddings[i].tolist()

        mongo.db.articles.update_one(
            {'_id': articles[i]['_id']},
            {'$set': {
                'embedding': embedding_list,
                'embedding_generated_at': datetime.utcnow().isoformat()
            }}
        )

    print(f"Saved {len(article_ids)} embeddings to MongoDB")

    return {
        'embeddings': embeddings,
        'ids': article_ids,
        'collection': 'articles',
        'metadata': [{'title': a.get('title', ''), 'description': a.get('description', '')}
                     for a in articles]
    }


def generate_embeddings_for_repos(mongo, generator):
    """
    Generate embeddings for all GitHub repo descriptions
    """

    print("\n" + "=" * 70)
    print("GENERATING EMBEDDINGS FOR GITHUB REPOS")
    print("=" * 70)

    # Step 1: Read repos
    print("\n[1] Reading repos from MongoDB...")
    repos = list(mongo.db.github_repos.find())
    print(f"Found {len(repos)} repos")

    if len(repos) == 0:
        print("WARNING: No repos found!")
        return []

    # Step 2: Prepare texts
    print("\n[2] Preparing texts for embedding...")

    texts = []
    repo_ids = []

    for repo in repos:
        # Use description or full_name
        description = repo.get('description', '') or repo.get('full_name', '')
        if description == 'No description':
            description = repo.get('full_name', '')
        texts.append(description)
        repo_ids.append(str(repo['_id']))

    print(f"Prepared {len(texts)} texts")

    # Step 3: Generate embeddings
    print("\n[3] Generating embeddings...")
    embeddings = generator.generate_embeddings_batch(texts, show_progress=True)
    print(f"Generated {len(embeddings)} embeddings")

    # Step 4: Save to MongoDB
    print("\n[4] Saving embeddings to MongoDB...")

    for i, repo_id in enumerate(repo_ids):
        embedding_list = embeddings[i].tolist()

        mongo.db.github_repos.update_one(
            {'_id': repos[i]['_id']},
            {'$set': {
                'embedding': embedding_list,
                'embedding_generated_at': datetime.utcnow().isoformat()
            }}
        )

    print(f"Saved {len(repo_ids)} embeddings to MongoDB")

    return {
        'embeddings': embeddings,
        'ids': repo_ids,
        'collection': 'github_repos',
        'metadata': [{'full_name': r.get('full_name', ''), 'description': r.get('description', '')}
                     for r in repos]
    }


def build_faiss_index(all_embeddings_data):
    """
    Build FAISS index for fast semantic search

    What is FAISS index:
    - Data structure optimized for similarity search
    - Can search through millions of vectors in milliseconds
    - Used by Google, Facebook, etc.

    How it works:
    1. Combine all embeddings (startups + articles + repos)
    2. Create FAISS index
    3. Add all vectors to index
    4. Save index to disk

    Why we need this:
    - MongoDB is slow for vector similarity search
    - FAISS is 1000x faster
    - Can handle massive datasets
    """

    print("\n" + "=" * 70)
    print("BUILDING FAISS INDEX")
    print("=" * 70)

    # Step 1: Combine all embeddings
    print("\n[1] Combining all embeddings...")

    all_embeddings = []
    all_ids = []
    all_metadata = []

    for data in all_embeddings_data:
        if data:  # Skip empty results
            all_embeddings.append(data['embeddings'])
            all_ids.extend(data['ids'])
            all_metadata.extend([{
                'collection': data['collection'],
                **meta
            } for meta in data['metadata']])

    # Stack all embeddings into single matrix
    combined_embeddings = np.vstack(all_embeddings)

    print(f"Total embeddings: {len(combined_embeddings)}")
    print(f"Embedding dimension: {combined_embeddings.shape[1]}")

    # Step 2: Create FAISS index
    print("\n[2] Creating FAISS index...")

    dimension = combined_embeddings.shape[1]  # 384

    # IndexFlatIP = Index using Flat (exact) search with Inner Product
    # Inner Product = Cosine similarity (since vectors are normalized)
    index = faiss.IndexFlatIP(dimension)

    # Add vectors to index
    index.add(combined_embeddings)

    print(f"FAISS index created with {index.ntotal} vectors")

    # Step 3: Save index to disk
    print("\n[3] Saving FAISS index to disk...")

    # Create data directory if it doesn't exist
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    os.makedirs(data_dir, exist_ok=True)

    # Save FAISS index
    index_path = os.path.join(data_dir, 'faiss_index.bin')
    faiss.write_index(index, index_path)
    print(f"Saved FAISS index to: {index_path}")

    # Save metadata (for looking up results)
    metadata_path = os.path.join(data_dir, 'faiss_metadata.pkl')
    metadata = {
        'ids': all_ids,
        'metadata': all_metadata
    }
    with open(metadata_path, 'wb') as f:
        pickle.dump(metadata, f)
    print(f"Saved metadata to: {metadata_path}")

    return index, metadata


def test_semantic_search(generator, index, metadata):
    """
    Test the semantic search with example queries

    This demonstrates the power of vector embeddings!
    """

    print("\n" + "=" * 70)
    print("TESTING SEMANTIC SEARCH")
    print("=" * 70)

    # Test queries
    test_queries = [
        "AI music generation startup",
        "machine learning and artificial intelligence",
        "food delivery service"
    ]

    for query in test_queries:
        print(f"\n{'=' * 70}")
        print(f"Query: '{query}'")
        print('=' * 70)

        # Step 1: Convert query to embedding
        query_embedding = generator.generate_embedding(query)
        query_embedding = query_embedding.reshape(1, -1)  # Shape: (1, 384)

        # Step 2: Search FAISS index
        k = 5  # Top 5 results
        similarities, indices = index.search(query_embedding, k)

        # Step 3: Display results
        print("\nTop 5 results:")
        for i, (idx, score) in enumerate(zip(indices[0], similarities[0]), 1):
            result_meta = metadata['metadata'][idx]
            collection = result_meta['collection']

            if collection == 'startups':
                name = result_meta['name']
                desc = result_meta['description'][:80]
                print(f"  {i}. [{collection.upper()}] {name}")
            elif collection == 'articles':
                title = result_meta['title'][:80]
                print(f"  {i}. [{collection.upper()}] {title}")
            else:  # github_repos
                name = result_meta['full_name']
                print(f"  {i}. [{collection.upper()}] {name}")

            print(f"      Similarity: {score:.3f}")


def main():
    """Main function to generate embeddings and build FAISS index"""

    print("=" * 70)
    print("GENERATE EMBEDDINGS & BUILD FAISS INDEX")
    print("=" * 70)

    start_time = datetime.now()

    # Step 1: Connect to MongoDB
    print("\n[1] Connecting to MongoDB...")
    mongo = MongoDBClient()
    print("SUCCESS Connected\n")

    # Step 2: Create embedding generator
    print("[2] Loading embedding model...")
    generator = EmbeddingGenerator()
    print("SUCCESS Model loaded\n")

    # Step 3: Generate embeddings for all collections
    print("[3] Generating embeddings for all documents...")

    startup_data = generate_embeddings_for_startups(mongo, generator)
    article_data = generate_embeddings_for_articles(mongo, generator)
    repo_data = generate_embeddings_for_repos(mongo, generator)

    # Step 4: Build FAISS index
    print("\n[4] Building FAISS index...")
    all_data = [startup_data, article_data, repo_data]
    index, metadata = build_faiss_index(all_data)

    # Step 5: Test semantic search
    print("\n[5] Testing semantic search...")
    test_semantic_search(generator, index, metadata)

    # Summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    print("\n" + "=" * 70)
    print("SUCCESS EMBEDDINGS GENERATED")
    print("=" * 70)
    print(f"\nCompleted in {duration:.2f} seconds")
    print(f"\nWhat we created:")
    print(f"  ✅ Embeddings for {len(startup_data['ids'])} startups")
    print(f"  ✅ Embeddings for {len(article_data['ids'])} articles")
    print(f"  ✅ Embeddings for {len(repo_data['ids'])} repos")
    print(f"  ✅ FAISS index with {index.ntotal} vectors")
    print(f"  ✅ Saved to data/faiss_index.bin and data/faiss_metadata.pkl")

    print("\nNext steps:")
    print("  1. Embeddings are saved in MongoDB (check 'embedding' field)")
    print("  2. FAISS index is saved for fast search")
    print("  3. Ready for Sub-Phase 2.6 (Hybrid Retrieval)")
    print("  4. You can now do semantic search!")

    # Cleanup
    mongo.close()


if __name__ == "__main__":
    main()

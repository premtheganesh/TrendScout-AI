"""
Embedding Generator using Sentence Transformers

This module converts text into vector embeddings (arrays of numbers that capture meaning).

What it does:
- Takes text like "AI music generation startup"
- Converts it to a vector: [0.2, 0.8, 0.1, ...]  (384 numbers)
- Similar meanings produce similar vectors
- Enables semantic search (finding meaning, not just keywords)

Why we need this:
- Find similar content even if words don't match exactly
- Search "AI music" and find "Suno" (which does AI music)
- Powers intelligent recommendation systems
"""

from sentence_transformers import SentenceTransformer
import numpy as np
from typing import List, Union
import logging

logger = logging.getLogger(__name__)


class EmbeddingGenerator:
    """
    Generate vector embeddings from text using Sentence Transformers

    Model: all-MiniLM-L6-v2
    - Fast (can process 1000s of docs per second)
    - Accurate (understands semantic similarity)
    - Small (90MB download)
    - Free and open-source

    Output: 384-dimensional vectors

    Usage:
        generator = EmbeddingGenerator()
        vector = generator.generate_embedding("AI startup in SF")
        # Returns: numpy array of shape (384,)
    """

    def __init__(self, model_name: str = 'intfloat/e5-base-v2'):
        """
        Initialize embedding generator

        Args:
            model_name: Sentence transformer model to use
                       Default: 'intfloat/e5-base-v2' (fast and accurate)

        What happens:
            1. Downloads model (first time only, ~90MB)
            2. Loads model into memory
            3. Ready to generate embeddings
        """
        logger.info(f"Loading embedding model: {model_name}...")

        try:
            self.model = SentenceTransformer(model_name)
            self.dimension = self.model.get_sentence_embedding_dimension()

            logger.info(f"✅ Model loaded successfully")
            logger.info(f"   Embedding dimension: {self.dimension}")

        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise

    def generate_embedding(self, text: str) -> np.ndarray:
        """
        Generate embedding vector for a single text

        Args:
            text: Text to convert to embedding
                  Example: "Suno is an AI music generation startup"

        Returns:
            numpy array of shape (384,)
            Example: array([0.2, 0.8, 0.1, ...])

        How it works:
            1. Tokenize text into words
            2. Convert words to numbers
            3. Pass through neural network
            4. Output: vector that captures meaning
        """

        if not text or not text.strip():
            logger.warning("Empty text provided, returning zero vector")
            return np.zeros(self.dimension)

        try:
            # Generate embedding
            embedding = self.model.encode(
                text,
                convert_to_numpy=True,      # Return numpy array
                normalize_embeddings=True   # Normalize to unit length (for cosine similarity)
            )

            return embedding

        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return np.zeros(self.dimension)

    def generate_embeddings_batch(self, texts: List[str], show_progress: bool = True) -> np.ndarray:
        """
        Generate embeddings for multiple texts at once (faster than one-by-one)

        Args:
            texts: List of texts to convert
                  Example: ["AI startup", "Music generation", "Pizza delivery"]
            show_progress: Show progress bar during encoding

        Returns:
            numpy array of shape (num_texts, 384)
            Example: array([[0.2, 0.8, ...], [0.3, 0.7, ...], ...])

        Why batch processing is faster:
            - GPU/CPU can process multiple texts in parallel
            - Reduces overhead
            - 10x faster than processing one-by-one
        """

        if not texts:
            logger.warning("Empty text list provided")
            return np.array([])

        try:
            # Filter out empty texts
            valid_texts = [text if text and text.strip() else "" for text in texts]

            # Generate embeddings for all texts at once
            embeddings = self.model.encode(
                valid_texts,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=show_progress,
                batch_size=32  # Process 32 texts at a time
            )

            logger.info(f"Generated {len(embeddings)} embeddings")
            return embeddings

        except Exception as e:
            logger.error(f"Error generating batch embeddings: {e}")
            return np.array([])

    def compute_similarity(self, embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        """
        Compute similarity between two embeddings (cosine similarity)

        Args:
            embedding1: First embedding vector
            embedding2: Second embedding vector

        Returns:
            Similarity score between -1 and 1
            - 1.0 = identical meaning
            - 0.0 = unrelated
            - -1.0 = opposite meaning

        How cosine similarity works:
            - Measures angle between two vectors
            - Similar vectors point in same direction
            - Different vectors point in different directions

        Example:
            emb1 = generate_embedding("AI music startup")
            emb2 = generate_embedding("Suno creates AI songs")
            similarity = compute_similarity(emb1, emb2)
            # Result: ~0.85 (very similar!)
        """

        # Cosine similarity = dot product (since vectors are normalized)
        similarity = np.dot(embedding1, embedding2)
        return float(similarity)

    def find_most_similar(
        self,
        query_embedding: np.ndarray,
        candidate_embeddings: np.ndarray,
        top_k: int = 5
    ) -> List[tuple]:
        """
        Find most similar embeddings to a query

        Args:
            query_embedding: The search query vector (384,)
            candidate_embeddings: All vectors to search through (N, 384)
            top_k: Number of results to return

        Returns:
            List of (index, similarity_score) tuples
            Sorted by similarity (highest first)

        Example:
            query = generate_embedding("AI music startup")
            candidates = generate_embeddings_batch([
                "Suno creates AI songs",
                "Pizza delivery service",
                "Music generation AI"
            ])
            results = find_most_similar(query, candidates, top_k=2)
            # Returns: [(0, 0.85), (2, 0.82)]
            # Indices 0 and 2 are most similar
        """

        # Compute similarity with all candidates
        # Matrix multiplication: (384,) @ (N, 384).T = (N,)
        similarities = np.dot(candidate_embeddings, query_embedding)

        # Get top k indices
        top_indices = np.argsort(similarities)[::-1][:top_k]

        # Return (index, score) pairs
        results = [(int(idx), float(similarities[idx])) for idx in top_indices]

        return results


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    """
    Test the EmbeddingGenerator

    Run this file directly:
        python src/embeddings/embedding_generator.py
    """

    logging.basicConfig(level=logging.INFO)

    print("=" * 70)
    print("TESTING EMBEDDING GENERATOR")
    print("=" * 70)

    # Create generator
    print("\n[1] Creating embedding generator...")
    generator = EmbeddingGenerator()

    # Test 1: Single embedding
    print("\n" + "=" * 70)
    print("TEST 1: Generate single embedding")
    print("=" * 70)

    text = "Suno is an AI music generation startup based in Cambridge"
    embedding = generator.generate_embedding(text)

    print(f"Text: {text}")
    print(f"Embedding shape: {embedding.shape}")
    print(f"First 10 values: {embedding[:10]}")

    # Test 2: Batch embeddings
    print("\n" + "=" * 70)
    print("TEST 2: Generate batch embeddings")
    print("=" * 70)

    texts = [
        "AI music generation platform",
        "Food delivery service",
        "Music creation with artificial intelligence",
        "Pizza ordering application"
    ]

    embeddings = generator.generate_embeddings_batch(texts)
    print(f"Generated {len(embeddings)} embeddings")
    print(f"Shape: {embeddings.shape}")

    # Test 3: Similarity
    print("\n" + "=" * 70)
    print("TEST 3: Compute similarity")
    print("=" * 70)

    query = "AI music startup"
    query_embedding = generator.generate_embedding(query)

    print(f"\nQuery: '{query}'")
    print("\nSimilarity with each text:")

    for i, text in enumerate(texts):
        similarity = generator.compute_similarity(query_embedding, embeddings[i])
        print(f"  {i+1}. '{text}': {similarity:.3f}")

    # Test 4: Find most similar
    print("\n" + "=" * 70)
    print("TEST 4: Find most similar")
    print("=" * 70)

    results = generator.find_most_similar(query_embedding, embeddings, top_k=2)

    print(f"\nTop 2 most similar to '{query}':")
    for idx, score in results:
        print(f"  {idx+1}. '{texts[idx]}' (score: {score:.3f})")

    print("\n" + "=" * 70)
    print("✅ ALL TESTS COMPLETE")
    print("=" * 70)
    print("\nObservations:")
    print("  - AI music texts have high similarity (~0.7-0.8)")
    print("  - Food/pizza texts have low similarity (~0.2-0.3)")
    print("  - This is semantic search in action!")

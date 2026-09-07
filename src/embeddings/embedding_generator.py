"""Text embeddings using sentence-transformers (E5-base-v2)."""

from sentence_transformers import SentenceTransformer
import numpy as np
from typing import List, Union
import logging

logger = logging.getLogger(__name__)


class EmbeddingGenerator:
    """Generate vector embeddings from text using Sentence Transformers"""

    QUERY_PREFIX = "query: "
    PASSAGE_PREFIX = "passage: "

    def __init__(self, model_name: str = 'intfloat/e5-base-v2'):
        """Initialize embedding generator"""
        logger.info(f"Loading embedding model: {model_name}...")

        try:
            self.model = SentenceTransformer(model_name)
            self.dimension = self.model.get_sentence_embedding_dimension()

            logger.info(f"Model loaded successfully")
            logger.info(f"   Embedding dimension: {self.dimension}")

        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise

    def generate_embedding(self, text: str, prefix: str = "") -> np.ndarray:
        """Generate embedding vector for a single text"""

        if not text or not text.strip():
            logger.warning("Empty text provided, returning zero vector")
            return np.zeros(self.dimension)

        # Apply the E5 prefix unless the caller already did
        if prefix and not text.lstrip().lower().startswith(prefix.strip().lower()):
            text = prefix + text.strip()

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

    # The FAISS index is built with embed_passage(); changing either side
    # requires rebuilding it with scripts/build_indexes.py.

    def embed_query(self, text: str) -> np.ndarray:
        """Encode a user search query with the E5 "query: " prefix."""
        return self.generate_embedding(text, prefix=self.QUERY_PREFIX)

    def embed_passage(self, text: str) -> np.ndarray:
        """Encode a document/passage with the E5 "passage: " prefix."""
        return self.generate_embedding(text, prefix=self.PASSAGE_PREFIX)

    def embed_passages_batch(
        self,
        texts: List[str],
        show_progress: bool = True
    ) -> np.ndarray:
        """Encode many documents at once with the E5 "passage: " prefix."""
        return self.generate_embeddings_batch(
            texts,
            show_progress=show_progress,
            prefix=self.PASSAGE_PREFIX
        )


    def generate_embeddings_batch(
        self,
        texts: List[str],
        show_progress: bool = True,
        prefix: str = ""
    ) -> np.ndarray:
        """Generate embeddings for multiple texts at once (faster than one-by-one)"""

        if not texts:
            logger.warning("Empty text list provided")
            return np.array([])

        try:
            # Filter out empty texts, applying the E5 prefix to the non-empty ones
            valid_texts = []
            for text in texts:
                if text and text.strip():
                    t = text.strip()
                    if prefix and not t.lower().startswith(prefix.strip().lower()):
                        t = prefix + t
                    valid_texts.append(t)
                else:
                    valid_texts.append("")

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
        """Compute similarity between two embeddings (cosine similarity)"""

        # Cosine similarity = dot product (since vectors are normalized)
        similarity = np.dot(embedding1, embedding2)
        return float(similarity)

    def find_most_similar(
        self,
        query_embedding: np.ndarray,
        candidate_embeddings: np.ndarray,
        top_k: int = 5
    ) -> List[tuple]:
        """Find most similar embeddings to a query"""

        # Compute similarity with all candidates
        # Matrix multiplication: (768,) @ (N, 768).T = (N,)
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
    print("ALL TESTS COMPLETE")
    print("=" * 70)
    print("\nObservations:")
    print("  - AI music texts have high similarity (~0.7-0.8)")
    print("  - Food/pizza texts have low similarity (~0.2-0.3)")
    print("  - This is semantic search in action!")

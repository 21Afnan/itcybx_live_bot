# src/knowledge_base/embedder.py

import time
from typing import List
from langchain_mistralai import MistralAIEmbeddings

from src.config.settings import MISTRAL_API_KEY, EMBEDDING_MODEL, EMBEDDING_DIMENSION
from src.utils.logger import get_logger

logger = get_logger("Embedder")


class MistralEmbedder:
    """
    Handles generation of 1024-dimensional bilingual embeddings
    using Mistral AI's official mistral-embed model.
    """

    def __init__(self, api_key: str = MISTRAL_API_KEY, model: str = EMBEDDING_MODEL):
        if not api_key:
            logger.error("Mistral API key is missing for Embedder initialization!")
            raise ValueError("MISTRAL_API_KEY is required.")

        self.model = model
        self.dimension = EMBEDDING_DIMENSION
        self.embeddings = MistralAIEmbeddings(
            api_key=api_key,
            model=self.model,
        )
        logger.info(f"Initialized MistralEmbedder (model: '{self.model}', dimension: {self.dimension})")

    def embed_query(self, query: str) -> List[float]:
        """
        Embeds a single query string for vector search.
        Returns a 1024-dimensional vector.
        """
        if not query or not query.strip():
            logger.warning("Empty query string received for embedding.")
            return []

        try:
            vector = self.embeddings.embed_query(query.strip())
            return vector
        except Exception as e:
            logger.error(f"Failed to generate query embedding: {e}")
            raise e

    def embed_documents(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """
        Generates vector embeddings for a list of text strings in batches.
        """
        if not texts:
            logger.warning("No texts provided for embedding.")
            return []

        total_texts = len(texts)
        logger.info(f"Generating embeddings for {total_texts} chunks (batch size: {batch_size})...")

        all_vectors: List[List[float]] = []
        start_time = time.time()

        for i in range(0, total_texts, batch_size):
            batch = texts[i : i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total_texts + batch_size - 1) // batch_size

            try:
                batch_vectors = self.embeddings.embed_documents(batch)
                all_vectors.extend(batch_vectors)
                logger.info(f"Processed batch {batch_num}/{total_batches} ({len(batch)} chunks)")
            except Exception as e:
                logger.error(f"Failed to embed batch {batch_num}: {e}")
                raise e

        elapsed = time.time() - start_time
        logger.info(f"Successfully embedded {len(all_vectors)} chunks in {elapsed:.2f} seconds.")
        return all_vectors


if __name__ == "__main__":
    embedder = MistralEmbedder()
    test_text = "IT Cybx Growth Audit helps e-commerce stores scale."
    vector = embedder.embed_query(test_text)
    
    print("\n=======================================================")
    print("               EMBEDDER TEST RESULTS                   ")
    print("=======================================================")
    print(f"Test Query: '{test_text}'")
    print(f"Embedding Dimensions: {len(vector)}")
    print(f"Sample Vector Values: {vector[:5]} ...")
    print("=======================================================\n")

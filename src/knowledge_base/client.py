# src/knowledge_base/client.py

import time
from typing import List, Dict, Any, Optional
from pinecone import Pinecone, ServerlessSpec

from src.config.settings import (
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    EMBEDDING_DIMENSION,
)
from src.knowledge_base.chunker import TextChunk
from src.utils.logger import get_logger

logger = get_logger("PineconeClient")


class PineconeVectorStore:
    """
    Manages Pinecone index creation, batch vector upserting,
    and threshold-based similarity retrieval for IT Cybx RAG.
    """

    def __init__(
        self,
        api_key: str = PINECONE_API_KEY,
        index_name: str = PINECONE_INDEX_NAME,
        dimension: int = EMBEDDING_DIMENSION,
        metric: str = "cosine",
    ):
        if not api_key:
            logger.error("Pinecone API key is missing!")
            raise ValueError("PINECONE_API_KEY is required.")

        self.api_key = api_key
        self.index_name = index_name
        self.dimension = dimension
        self.metric = metric

        logger.info("Initializing Pinecone client...")
        self.pc = Pinecone(api_key=self.api_key)
        self.ensure_index_exists()
        self.index = self.pc.Index(self.index_name)
        logger.info(f"Connected to Pinecone index: '{self.index_name}'")

    def ensure_index_exists(self):
        """
        Verifies that the target Pinecone index exists.
        Creates a serverless index if it does not already exist.
        """
        existing_indexes = [idx.name for idx in self.pc.list_indexes()]
        
        if self.index_name not in existing_indexes:
            logger.info(
                f"Index '{self.index_name}' not found. Creating Serverless Pinecone index "
                f"(dim: {self.dimension}, metric: '{self.metric}')..."
            )
            self.pc.create_index(
                name=self.index_name,
                dimension=self.dimension,
                metric=self.metric,
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )
            
            # Wait until index is ready for requests
            logger.info("Waiting for Pinecone index to become ready...")
            while not self.pc.describe_index(self.index_name).status["ready"]:
                time.sleep(2)
            logger.info(f"Pinecone index '{self.index_name}' is now active and ready!")
        else:
            logger.info(f"Pinecone index '{self.index_name}' already exists.")

    def clear_namespace(self, namespace: str):
        """Deletes all existing vectors in a namespace before re-indexing."""
        try:
            self.index.delete(delete_all=True, namespace=namespace)
            logger.info(f"Cleared namespace '{namespace}' successfully.")
        except Exception as e:
            logger.warning(f"Namespace '{namespace}' might already be empty or clean: {e}")

    def upsert_chunks(
        self,
        chunks: List[TextChunk],
        vectors: List[List[float]],
        namespace: str,
        batch_size: int = 50,
    ) -> int:
        """
        Upserts chunk vectors and metadata into the specified Pinecone namespace.
        (e.g., 'kb_en' for English, 'kb_ar' for Arabic)
        """
        if len(chunks) != len(vectors):
            err = f"Mismatch: {len(chunks)} chunks vs {len(vectors)} vectors."
            logger.error(err)
            raise ValueError(err)

        total_records = len(chunks)
        logger.info(f"Upserting {total_records} vectors into namespace '{namespace}' (batch size: {batch_size})...")

        for i in range(0, total_records, batch_size):
            batch_chunks = chunks[i : i + batch_size]
            batch_vectors = vectors[i : i + batch_size]

            records_to_upsert = []
            for chunk, vec in zip(batch_chunks, batch_vectors):
                records_to_upsert.append({
                    "id": chunk.id,
                    "values": vec,
                    "metadata": chunk.to_metadata(),
                })

            self.index.upsert(vectors=records_to_upsert, namespace=namespace)
            batch_num = (i // batch_size) + 1
            total_batches = (total_records + batch_size - 1) // batch_size
            logger.info(f"  • Upserted batch {batch_num}/{total_batches} ({len(records_to_upsert)} records)")

        logger.info(f"Successfully upserted all {total_records} records to namespace '{namespace}'.")
        return total_records

    def query(
        self,
        query_vector: List[float],
        namespace: str = "kb_en",
        top_k: int = 4,
        score_threshold: float = 0.60,
    ) -> List[Dict[str, Any]]:
        """
        Searches Pinecone for the most relevant document chunks.
        Applies similarity score threshold to flag low-confidence results.
        """
        if not query_vector:
            logger.warning("Empty query vector provided to Pinecone query.")
            return []

        response = self.index.query(
            vector=query_vector,
            namespace=namespace,
            top_k=top_k,
            include_metadata=True,
        )

        matches = response.get("matches", [])
        results: List[Dict[str, Any]] = []

        for match in matches:
            score = match.get("score", 0.0)
            meta = match.get("metadata", {})
            
            results.append({
                "id": match.get("id"),
                "score": round(score, 4),
                "is_confident": score >= score_threshold,
                "text": meta.get("text", ""),
                "source_url": meta.get("source_url", ""),
                "slug": meta.get("slug", ""),
                "language": meta.get("language", ""),
                "chunk_index": meta.get("chunk_index", 0),
            })

        logger.info(
            f"Query in '{namespace}' returned {len(results)} matches. "
            f"Top score: {results[0]['score'] if results else 'N/A'}"
        )
        return results

    def get_index_stats(self) -> Dict[str, Any]:
        """Returns stats about the index, including total vector count per namespace."""
        return self.index.describe_index_stats().to_dict()


if __name__ == "__main__":
    store = PineconeVectorStore()
    stats = store.get_index_stats()
    
    print("\n=======================================================")
    print("             PINECONE INDEX STATUS                     ")
    print("=======================================================")
    print(f"Index Name   : {store.index_name}")
    print(f"Dimension    : {store.dimension}")
    print(f"Index Stats  : {stats}")
    print("=======================================================\n")

# scripts/build_knowledge_base.py

import time
from src.knowledge_base.chunker import DocumentChunker
from src.knowledge_base.embedder import MistralEmbedder
from src.knowledge_base.client import PineconeVectorStore
from src.utils.logger import get_logger

logger = get_logger("BuildKB")


def build_knowledge_base():
    """
    Main ingestion pipeline:
    1. Reads and chunks all processed English and Arabic documents.
    2. Generates 1024-dim embeddings via Mistral AI (mistral-embed).
    3. Indexes vectors into Pinecone under 'kb_en' and 'kb_ar' namespaces.
    """
    start_total = time.time()
    logger.info("=======================================================")
    logger.info("       STARTING IT CYBX KNOWLEDGE BASE BUILD           ")
    logger.info("=======================================================")

    # 1. Initialize components
    chunker = DocumentChunker(chunk_size=650, chunk_overlap=100)
    embedder = MistralEmbedder()
    vector_store = PineconeVectorStore()

    # 2. Chunk English & Arabic documents
    logger.info("\n--- [Step 1/3] Chunking Processed Documents ---")
    chunks_by_lang = chunker.get_all_chunks()
    en_chunks = chunks_by_lang["en"]
    ar_chunks = chunks_by_lang["ar"]

    logger.info(f"Loaded {len(en_chunks)} English chunks and {len(ar_chunks)} Arabic chunks.")

    # 3. Process English Chunks
    if en_chunks:
        logger.info("\n--- [Step 2/3] Embedding & Indexing English (kb_en) ---")
        vector_store.clear_namespace("kb_en")
        en_texts = [c.text for c in en_chunks]
        en_vectors = embedder.embed_documents(en_texts, batch_size=32)
        vector_store.upsert_chunks(en_chunks, en_vectors, namespace="kb_en", batch_size=50)

    # 4. Process Arabic Chunks
    if ar_chunks:
        logger.info("\n--- [Step 3/3] Embedding & Indexing Arabic (kb_ar) ---")
        vector_store.clear_namespace("kb_ar")
        ar_texts = [c.text for c in ar_chunks]
        ar_vectors = embedder.embed_documents(ar_texts, batch_size=32)
        vector_store.upsert_chunks(ar_chunks, ar_vectors, namespace="kb_ar", batch_size=50)

    # 5. Fetch updated stats
    time.sleep(2)  # Allow Pinecone stats to refresh
    stats = vector_store.get_index_stats()
    total_time = time.time() - start_total

    print("\n=======================================================")
    print("      KNOWLEDGE BASE BUILD COMPLETED SUCCESSFULLY!     ")
    print("=======================================================")
    print(f"Total English Chunks Indexed : {len(en_chunks)}")
    print(f"Total Arabic Chunks Indexed  : {len(ar_chunks)}")
    print(f"Total Elapsed Time           : {total_time:.2f} seconds")
    print(f"Pinecone Namespaces & Stats  : {stats.get('namespaces', {})}")
    print("=======================================================\n")


if __name__ == "__main__":
    build_knowledge_base()

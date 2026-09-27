# scripts/build_knowledge_base.py

import time
from src.knowledge_base.chunker import DocumentChunker
from src.knowledge_base.embedder import MistralEmbedder
from src.knowledge_base.client import PineconeVectorStore
from src.utils.logger import get_logger

logger = get_logger("BuildKB")


def _verify_namespace_count(vector_store: PineconeVectorStore, namespace: str, expected: int):
    """Confirms the namespace actually holds the expected number of vectors
    after an upsert, rather than silently trusting that upsert succeeded."""
    time.sleep(2)  # Pinecone stats can lag briefly after a write
    stats = vector_store.get_index_stats()
    actual = stats.get("namespaces", {}).get(namespace, {}).get("vector_count", 0)
    if actual != expected:
        error_msg = (
            f"Namespace '{namespace}' has {actual} vectors after upsert, "
            f"expected {expected}. The rebuild may be incomplete."
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    logger.info(f"Verified namespace '{namespace}': {actual}/{expected} vectors present.")


def _build_and_swap_namespace(vector_store: PineconeVectorStore, namespace: str, chunks, vectors):
    """
    Upserts into a staging namespace first and verifies it fully succeeded
    BEFORE touching the live namespace, then repeats the same proven-good
    upsert into the live namespace. Pinecone's API has no atomic
    rename/alias primitive, so this can't be made fully atomic — but
    proving the upsert works against staging first (network reachable,
    batches all landing, count matches) makes a subsequent failure on the
    identical live upsert far less likely. If the live swap DOES fail
    partway, the staging namespace is deliberately left in place (not
    cleaned up) as a recovery copy, and the error says so.
    """
    staging_ns = f"{namespace}_staging"

    logger.info(f"Validating upsert against staging namespace '{staging_ns}' before touching '{namespace}'...")
    vector_store.clear_namespace(staging_ns)
    vector_store.upsert_chunks(chunks, vectors, namespace=staging_ns, batch_size=50)
    _verify_namespace_count(vector_store, staging_ns, expected=len(chunks))

    try:
        vector_store.clear_namespace(namespace)
        vector_store.upsert_chunks(chunks, vectors, namespace=namespace, batch_size=50)
        _verify_namespace_count(vector_store, namespace, expected=len(chunks))
    except Exception:
        logger.error(
            f"Live swap into '{namespace}' failed after staging validation succeeded. "
            f"'{staging_ns}' has been LEFT IN PLACE as a verified-good recovery copy — "
            f"it is not queried by the live bot, but its vectors match what should be "
            f"in '{namespace}'. Investigate before re-running."
        )
        raise

    # Both namespaces now hold identical data; drop the temporary copy.
    vector_store.clear_namespace(staging_ns)
    logger.info(f"Swap into '{namespace}' verified successfully; staging namespace cleaned up.")


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

    # 3. Generate embeddings for BOTH languages FIRST, before touching the
    #    live namespaces. If Mistral's embedding API fails partway (network
    #    error, rate limit, etc.), the live kb_en/kb_ar data is untouched and
    #    the bot keeps serving the previous, still-valid knowledge base. Only
    #    once embeddings for a language are fully computed do we clear and
    #    replace that namespace.
    logger.info("\n--- [Step 2/3] Generating Embeddings (before touching live data) ---")
    en_texts = [c.text for c in en_chunks]
    ar_texts = [c.text for c in ar_chunks]
    en_vectors = embedder.embed_documents(en_texts, batch_size=32) if en_chunks else []
    ar_vectors = embedder.embed_documents(ar_texts, batch_size=32) if ar_chunks else []

    logger.info("\n--- [Step 3/3] Validating via Staging, Then Replacing Live Namespaces ---")
    if en_chunks:
        _build_and_swap_namespace(vector_store, "kb_en", en_chunks, en_vectors)

    if ar_chunks:
        _build_and_swap_namespace(vector_store, "kb_ar", ar_chunks, ar_vectors)

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

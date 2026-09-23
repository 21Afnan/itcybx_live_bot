# src/tools/faq_tool.py

from langchain_core.tools import tool
from typing import Optional

from src.knowledge_base.embedder import MistralEmbedder
from src.knowledge_base.client import PineconeVectorStore
from src.utils.logger import get_logger

logger = get_logger("FAQTool")

# Reusable singletons for embedding and vector search
_embedder: Optional[MistralEmbedder] = None
_vector_store: Optional[PineconeVectorStore] = None


def get_embedder() -> MistralEmbedder:
    """Returns or initializes the MistralEmbedder instance."""
    global _embedder
    if _embedder is None:
        _embedder = MistralEmbedder()
    return _embedder


def get_vector_store() -> PineconeVectorStore:
    """Returns or initializes the PineconeVectorStore instance."""
    global _vector_store
    if _vector_store is None:
        _vector_store = PineconeVectorStore()
    return _vector_store


@tool
def search_knowledge_base(query: str, language: str = "en") -> str:
    """
    Searches the official verified IT Cybx knowledge base for accurate facts about:
    - E-commerce services, Shopify/Salla/Zid development, and growth marketing.
    - Growth Audit ($150 / SAR 550) details, deliverables, timeline, and scope.
    - Growth Sprint, Growth Retainer, and pricing models.
    - Case studies (e.g. Amira Essence, KSA mobile accessories, jewelry brand).
    - Company policies (Refund & Cancellation, Terms, Privacy, Cookies).

    Args:
        query: The specific search question or topic.
        language: 'en' for English content (default), 'ar' for Arabic content.

    Returns:
        A formatted string of verified facts and source URLs, or a notice if not found.
    """
    logger.info(f"Tool search_knowledge_base called: query='{query}', lang='{language}'")

    try:
        embedder = get_embedder()
        vector_store = get_vector_store()

        # 1. Generate query vector
        query_vector = embedder.embed_query(query)
        if not query_vector:
            logger.warning("Empty query vector generated in search_knowledge_base tool.")
            return "NO_RESULTS_FOUND: Empty query."

        # 2. Select appropriate Pinecone namespace
        namespace = "kb_ar" if language.lower() == "ar" else "kb_en"

        # 3. Query Pinecone with confidence threshold
        results = vector_store.query(
            query_vector=query_vector,
            namespace=namespace,
            top_k=3,
            score_threshold=0.65,
        )

        if not results:
            logger.info("No matching chunks returned from vector store.")
            return (
                "NO_RELEVANT_INFORMATION_FOUND: The knowledge base has no information on this topic. "
                "Do NOT guess. Provide the official fallback contact info."
            )

        # 4. Check if top result has acceptable confidence
        top_result = results[0]
        if not top_result["is_confident"]:
            logger.warning(f"Top result confidence ({top_result['score']}) is below threshold 0.65.")
            return (
                "NO_RELEVANT_INFORMATION_FOUND: Confidence score is too low. The knowledge base does not "
                "contain verified facts to answer this accurately. Do NOT guess. "
                "Provide the official fallback contact info."
            )

        # 5. Format confident results
        formatted_chunks = []
        for idx, res in enumerate(results, 1):
            if res["is_confident"]:
                chunk_str = f"[Source: {res['source_url']}]\n{res['text']}"
                formatted_chunks.append(chunk_str)

        response_text = "VERIFIED_KNOWLEDGE_BASE_CONTEXT:\n\n" + "\n\n---\n\n".join(formatted_chunks)
        logger.info(f"Tool returning {len(formatted_chunks)} verified context chunk(s).")
        return response_text

    except Exception as e:
        logger.error(f"Error executing search_knowledge_base: {e}")
        return f"ERROR_SEARCHING_KNOWLEDGE_BASE: Unable to retrieve information at this time."


if __name__ == "__main__":
    test_res = search_knowledge_base.invoke({"query": "What is the Growth Audit?", "language": "en"})
    print("\n=======================================================")
    print("           FAQ TOOL DIRECT INVOCATION TEST             ")
    print("=======================================================")
    print(test_res[:350] + "...\n")

# scripts/test_rag.py

import sys
from pathlib import Path
from typing import Optional

# Fix Python path to resolve src modules from any working directory
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.knowledge_base.embedder import MistralEmbedder
from src.knowledge_base.client import PineconeVectorStore
from src.utils.logger import get_logger

logger = get_logger("TestRAG")


# Set standard output to UTF-8 to support Arabic and emojis on Windows
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


class RAGTester:
    """
    Harness to test retrieval accuracy, similarity scores,
    and anti-hallucination thresholds on Pinecone knowledge base.
    """

    def __init__(self, score_threshold: float = 0.60):
        self.embedder = MistralEmbedder()
        self.vector_store = PineconeVectorStore()
        self.score_threshold = score_threshold

    def query(self, question: str, language: str = "en", top_k: int = 3):
        """
        Executes a test query against Pinecone and displays formatted results.
        """
        namespace = "kb_en" if language.lower() == "en" else "kb_ar"
        print(f"\n=======================================================")
        print(f"QUERY [{language.upper()}]: '{question}'")
        print(f"Namespace: {namespace} | Threshold: {self.score_threshold}")
        print("=======================================================")

        # 1. Embed user query
        query_vector = self.embedder.embed_query(question)
        if not query_vector:
            print("[ERROR] Failed to generate query embedding.")
            return

        # 2. Search Pinecone
        results = self.vector_store.query(
            query_vector=query_vector,
            namespace=namespace,
            top_k=top_k,
            score_threshold=self.score_threshold,
        )

        if not results:
            print("[ERROR] No matching results found.")
            return

        top_match = results[0]
        if not top_match["is_confident"]:
            print(f"\n[FALLBACK TRIGGERED] Top similarity score ({top_match['score']}) is below threshold ({self.score_threshold})!")
            print("Bot will safely return static 'I don't know' response without hallucinating.")
        else:
            print(f"\n[CONFIDENT MATCH] Top similarity score: {top_match['score']}")

        print("\n--- Retrieved Chunks ---")
        for idx, match in enumerate(results, 1):
            confident_tag = "[PASS]" if match["is_confident"] else "[LOW]"
            print(f"\n[{idx}] {confident_tag} (Score: {match['score']}) | Source: {match['source_url']} (Slug: {match['slug']})")
            print(f"Text Preview:\n{match['text']}\n" + "-" * 50)


def run_benchmark_tests():
    """Runs standard automated test queries across EN, AR, and Out-of-Domain."""
    tester = RAGTester(score_threshold=0.60)

    test_queries = [
        # 1. English Specific FAQ
        ("How much does the Growth Audit cost and what do I get?", "en"),
        # 2. English Service / Case Study
        ("What ecommerce platforms and services does IT Cybx support?", "en"),
        # 3. Arabic FAQ
        ("ما هي تكلفة تقييم النمو وماذا يشمل؟", "ar"),
        # 4. Out-of-Domain (Should trigger fallback)
        ("Do you provide car repair and dental insurance?", "en"),
    ]

    print("\n=======================================================")
    print("           RUNNING RAG BENCHMARK TESTS                 ")
    print("=======================================================")

    for query_text, lang in test_queries:
        tester.query(query_text, language=lang, top_k=2)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Custom user query from CLI arguments with auto language detection
        user_query = " ".join(sys.argv[1:])
        has_arabic = any('\u0600' <= char <= '\u06FF' or '\u0750' <= char <= '\u077F' for char in user_query)
        detected_lang = "ar" if has_arabic else "en"
        tester = RAGTester()
        tester.query(user_query, language=detected_lang, top_k=3)
    else:
        # Default benchmark suite
        run_benchmark_tests()

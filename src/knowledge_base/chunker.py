# src/knowledge_base/chunker.py

import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config.settings import PROCESSED_EN_DIR, PROCESSED_AR_DIR
from src.utils.logger import get_logger

logger = get_logger("Chunker")

# Matches unfinished template placeholders like "[e.g. 14 / 30]", "[email]",
# "[city, Pakistan]", or "[الهاتف/واتساب]" that are still sitting in the
# source policy documents. Any chunk containing one of these is excluded
# from the knowledge base entirely (see parse_file below) so the bot can
# never surface literal placeholder text to a customer as if it were a
# real answer, e.g. quoting "[e.g. 14 / 30] days" as an actual notice
# period. This is a safety net, not a substitute for the business owner
# filling in the real values — excluded content just means the bot will
# say it doesn't have that specific detail instead of making something up
# or repeating the placeholder verbatim.
_PLACEHOLDER_RE = re.compile(r"\[[^\[\]]{2,60}\]")


@dataclass
class TextChunk:
    """Represents a single chunk of text with metadata for vector storage."""
    id: str
    text: str
    source_url: str
    language: str
    slug: str
    chunk_index: int
    total_chunks: int

    def to_metadata(self) -> Dict[str, Any]:
        """Returns metadata dictionary for Pinecone upsert (excluding id)."""
        return {
            "text": self.text,
            "source_url": self.source_url,
            "language": self.language,
            "slug": self.slug,
            "chunk_index": self.chunk_index,
            "total_chunks": self.total_chunks,
        }


class DocumentChunker:
    """
    Reads processed text files and splits them into clean, structured
    chunks with metadata preservation for English and Arabic content.
    """

    def __init__(self, chunk_size: int = 650, chunk_overlap: int = 100):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
        # Recursive text splitter respecting paragraph and sentence boundaries
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", " · ", " - ", ". ", "، ", " ", ""],
            length_function=len,
        )

    def parse_file(self, file_path: Path, language: str) -> List[TextChunk]:
        """
        Parses a single processed text file, extracts header metadata,
        and splits the remaining body into TextChunk objects.
        """
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read file {file_path}: {e}")
            raise e

        # Extract metadata from header
        source_url = ""
        body_text = content
        slug = file_path.stem

        lines = content.splitlines()
        header_end_idx = 0

        for idx, line in enumerate(lines[:5]):
            if line.startswith("SOURCE_URL:"):
                source_url = line.replace("SOURCE_URL:", "").strip()
                header_end_idx = idx + 1
            elif line.startswith("LANGUAGE:"):
                header_end_idx = idx + 1

        if header_end_idx > 0:
            body_text = "\n".join(lines[header_end_idx:]).strip()

        # Split text into raw string chunks
        raw_chunks = self.splitter.split_text(body_text)
        total_chunks = len(raw_chunks)

        text_chunks: List[TextChunk] = []
        excluded_count = 0
        for idx, text in enumerate(raw_chunks):
            cleaned_chunk_text = text.strip()
            if not cleaned_chunk_text:
                continue

            placeholder_match = _PLACEHOLDER_RE.search(cleaned_chunk_text)
            if placeholder_match:
                excluded_count += 1
                logger.warning(
                    f"[{language.upper()}] Excluding chunk {idx} of '{slug}.txt' from the knowledge "
                    f"base: contains an unfilled placeholder {placeholder_match.group(0)!r}. "
                    f"This content needs a real, approved value before it can be published."
                )
                continue

            chunk_id = f"{language}_{slug}_{idx}"
            text_chunks.append(
                TextChunk(
                    id=chunk_id,
                    text=cleaned_chunk_text,
                    source_url=source_url,
                    language=language,
                    slug=slug,
                    chunk_index=idx,
                    total_chunks=total_chunks,
                )
            )

        if excluded_count:
            logger.warning(
                f"[{language.upper()}] '{slug}.txt': excluded {excluded_count} chunk(s) with "
                f"unfilled placeholders — those facts are NOT in the knowledge base until fixed."
            )
        logger.info(f"[{language.upper()}] Chunked '{slug}.txt' -> {len(text_chunks)} chunks")
        return text_chunks

    def chunk_directory(self, dir_path: Path, language: str) -> List[TextChunk]:
        """Chunks all .txt files in a specific directory."""
        if not dir_path.exists():
            logger.error(f"Directory does not exist: {dir_path}")
            raise FileNotFoundError(f"Directory not found: {dir_path}")

        files = sorted(list(dir_path.glob("*.txt")))
        logger.info(f"Chunking {len(files)} files from {dir_path} ({language})...")

        all_chunks: List[TextChunk] = []
        for file_path in files:
            chunks = self.parse_file(file_path, language=language)
            all_chunks.extend(chunks)

        logger.info(f"Finished chunking {language.upper()}: Total {len(all_chunks)} chunks from {len(files)} files.")
        return all_chunks

    def get_all_chunks(self) -> Dict[str, List[TextChunk]]:
        """
        Loads and chunks all English and Arabic documents.
        Returns a dict: {'en': [...], 'ar': [...]}
        """
        en_chunks = self.chunk_directory(PROCESSED_EN_DIR, language="en")
        ar_chunks = self.chunk_directory(PROCESSED_AR_DIR, language="ar")
        return {
            "en": en_chunks,
            "ar": ar_chunks,
        }


if __name__ == "__main__":
    chunker = DocumentChunker()
    all_chunks = chunker.get_all_chunks()
    
    print("\n=======================================================")
    print("               CHUNKING SUMMARY RESULTS                ")
    print("=======================================================")
    print(f"English Chunks: {len(all_chunks['en'])}")
    print(f"Arabic Chunks : {len(all_chunks['ar'])}")
    print("=======================================================\n")
    
    if all_chunks['en']:
        sample = all_chunks['en'][0]
        print(f"Sample EN Chunk ID: {sample.id}")
        print(f"Source URL       : {sample.source_url}")
        print(f"Text Preview     :\n{sample.text[:200]}...")

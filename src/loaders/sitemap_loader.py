# src/loaders/sitemap_loader.py

import os
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv

# Load environment variables (such as USER_AGENT)
load_dotenv()

# Set fallback User-Agent if not set in .env to prevent LangChain warnings
if not os.getenv("USER_AGENT"):
    os.environ["USER_AGENT"] = "itcybx-live-bot/1.0"

from langchain_community.document_loaders.sitemap import SitemapLoader
from src.config.settings import RAW_EN_DIR, RAW_AR_DIR
from src.utils.logger import get_logger

logger = get_logger("SitemapLoader")


class ItCybxSitemapLoader:
    """
    Fetches pages from IT Cybx sitemaps (both English and Arabic)
    and saves the raw text files to data/raw/en/ and data/raw/ar/.
    """

    # Sitemaps for IT Cybx
    EN_SITEMAP_URL = "https://itcybx.co.uk/sitemap_index.xml"
    AR_SITEMAP_URL = "https://itcybx.co.uk/ar/sitemap_index.xml"

    # URL filter patterns to exclude theme demo content, taxonomy archives, and 404 pages
    EN_EXCLUDE_REGEX = r"^(?!.*(our-team|team|tag|category|author)).*$"
    AR_EXCLUDE_REGEX = r"^(?!.*(team|tag|category|author|page-404|furniture-company|design-nation|reshaped-leadership|standart-post|image-post|link-post|post-with-quote|best-domain|cloud-hosting|twice-profit|post-02|how-to-increase|how-to-shoot|amazing-natural|share-your-images)).*$"

    def __init__(self, en_dir: Path = RAW_EN_DIR, ar_dir: Path = RAW_AR_DIR):
        self.en_raw_dir = Path(en_dir)
        self.ar_raw_dir = Path(ar_dir)

    def url_to_filename(self, url: str, is_arabic: bool = False) -> str:
        """
        Converts a URL into a clean filename slug.
        Examples:
          - https://itcybx.co.uk/ -> home.txt
          - https://itcybx.co.uk/the-growth-audit/ -> the-growth-audit.txt
          - https://itcybx.co.uk/ar/ -> home.txt
          - https://itcybx.co.uk/ar/the-growth-audit/ -> the-growth-audit.txt
        """
        path = urlparse(url).path.strip("/")
        
        # If it's an Arabic URL, strip the leading 'ar/' or 'ar' prefix
        if is_arabic:
            if path == "ar":
                path = ""
            elif path.startswith("ar/"):
                path = path[3:]

        # If path is empty, it is the home page
        if not path:
            return "home.txt"

        # Replace slashes with dashes (e.g. portfolio/case-study -> portfolio-case-study.txt)
        slug = path.replace("/", "-")
        return f"{slug}.txt"

    def fetch_pages(self, sitemap_url: str, filter_regex: str):
        """Fetches documents from a given sitemap URL using LangChain's SitemapLoader."""
        logger.info(f"Fetching sitemap: {sitemap_url} ...")
        loader = SitemapLoader(
            web_path=sitemap_url,
            filter_urls=[filter_regex]
        )
        # Suppress noisy parsing logs
        loader.show_progress_bar = False
        documents = loader.load()
        return documents

    def save_documents(self, documents, output_dir: Path, is_arabic: bool = False):
        """Saves loaded documents as .txt files into the target output directory."""
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Saving {len(documents)} raw files to '{output_dir}/' ...")

        for doc in documents:
            url = doc.metadata.get("source", "unknown")
            filename = self.url_to_filename(url, is_arabic=is_arabic)
            filepath = output_dir / filename

            # Write header and page content with UTF-8 encoding
            header = f"SOURCE_URL: {url}\nLANGUAGE: {'ar' if is_arabic else 'en'}\n\n"
            filepath.write_text(header + doc.page_content, encoding="utf-8")

            logger.info(f"  • Saved [{filename}] <- {url}")

    def load_english(self):
        """Fetches and saves English pages to data/raw/en/."""
        logger.info("\n--- [1/2] Loading English Pages ---")
        en_docs = self.fetch_pages(self.EN_SITEMAP_URL, self.EN_EXCLUDE_REGEX)
        self.save_documents(en_docs, self.en_raw_dir, is_arabic=False)
        logger.info(f"Done! Saved {len(en_docs)} English files.")
        return en_docs

    def load_arabic(self):
        """Fetches and saves Arabic pages to data/raw/ar/."""
        logger.info("\n--- [2/2] Loading Arabic Pages ---")
        ar_docs = self.fetch_pages(self.AR_SITEMAP_URL, self.AR_EXCLUDE_REGEX)
        self.save_documents(ar_docs, self.ar_raw_dir, is_arabic=True)
        logger.info(f"Done! Saved {len(ar_docs)} Arabic files.")
        return ar_docs

    def load_all(self):
        """Fetches and saves both English and Arabic pages."""
        logger.info("Starting IT Cybx Bilingual Sitemap Loader...")
        en_docs = self.load_english()
        ar_docs = self.load_arabic()
        logger.info(f"SUCCESS: Total {len(en_docs)} English + {len(ar_docs)} Arabic pages saved.")


if __name__ == "__main__":
    loader = ItCybxSitemapLoader()
    loader.load_all()
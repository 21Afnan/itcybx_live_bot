# src/loaders/sitemap_loader.py

import os
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()  # load .env values (like USER_AGENT) before anything else

from langchain_community.document_loaders.sitemap import SitemapLoader


class ItCybxSitemapLoader:
    """
    Loads pages from IT Cybx's sitemap and saves the raw
    content into data/raw/ for inspection.
    """

    def __init__(self, sitemap_url, raw_output_dir="data/raw"):
        # Stores the sitemap URL and output directory
        self.sitemap_url = sitemap_url
        self.raw_output_dir = raw_output_dir
        self.documents = []  # will hold the loaded pages once fetched

    def load(self):
        """Fetches all pages listed in the sitemap."""
        print(f"Fetching pages from {self.sitemap_url}...")
        loader = SitemapLoader(
            web_path=self.sitemap_url,
            filter_urls=[r"^(?!.*(team|tag|category)).*$"]  # filter out theme demo team/tag pages
        )
        self.documents = loader.load()
        return self.documents

    def save_raw(self):
        """Saves each loaded page as a .txt file inside the raw output directory."""
        os.makedirs(self.raw_output_dir, exist_ok=True)
        print(f"\nTotal pages loaded: {len(self.documents)}")
        print(f"Saving raw files to '{self.raw_output_dir}/'...\n")

        for doc in self.documents:
            url = doc.metadata.get("source", "unknown")
            
            # Convert URL to a clean filename (e.g. 'the-growth-audit.txt', 'home.txt')
            path_slug = urlparse(url).path.strip("/").replace("/", "-")
            filename = f"{path_slug if path_slug else 'home'}.txt"
            filepath = os.path.join(self.raw_output_dir, filename)

            # Write URL header and page content to file
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"SOURCE_URL: {url}\n\n" + doc.page_content)

            print(f"  • Saved [{filename}] <- {url}")

        print(f"\nDone! All {len(self.documents)} files successfully saved to '{self.raw_output_dir}/'")


# This part only runs when you execute this file directly
if __name__ == "__main__":
    SITEMAP_URL = "https://itcybx.co.uk/sitemap_index.xml"
    RAW_OUTPUT_DIR = "data/raw"

    sitemap = ItCybxSitemapLoader(SITEMAP_URL, RAW_OUTPUT_DIR)
    sitemap.load()
    sitemap.save_raw()
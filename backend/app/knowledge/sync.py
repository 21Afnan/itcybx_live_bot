"""Copy the website's text into knowledge files the bot reads.

    python -m app.knowledge.sync --run-now

1. Read the list of pages from the site's sitemap (wp-sitemap.xml).
2. Download each page as visitors see it. (WordPress's REST API is not
   used for the text: this theme builds pages in PHP templates, so the API
   text is mostly empty, and for the privacy policy it is WordPress's
   unused default text.)
3. Remove the site header, menu, footer, cookie banner, forms and scripts.
4. Save the rest as Markdown: knowledge/en/<page>.md or knowledge/ar/<page>.md.

knowledge/rules.md is never touched here.
"""

import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify

from app.config import settings

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"
# Hostinger's CDN blocks requests that look like a script, so ask like a browser.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ITCybxKnowledgeSync/1.0; +https://itcybx.co.uk)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# WordPress's default demo page, not real content.
SKIP_PAGES = {"sample-page"}

# Parts of every page that are site chrome, not page content.
CHROME_CLASSES = ["itcybx-header-root", "itcybx-footer-root", "itcybx-ck"]

# The "Let's grow your store" contact block repeats at the bottom of most
# pages; it is kept once, on the contact page.
CONTACT_BLOCK_CLASS = "itcbx-cta-root"

UNWANTED_TAGS = ["script", "style", "noscript", "svg", "iframe", "img",
                 "form", "button", "header", "nav", "footer"]


def page_language(url: str) -> str:
    """'ar' for pages under /arabic/, otherwise 'en'."""
    return "ar" if urlparse(url).path.startswith("/arabic") else "en"


def page_name(url: str) -> str:
    """File name for a page: /pricing/ -> 'pricing', / and /arabic/ -> 'home'."""
    path = urlparse(url).path.strip("/")
    path = re.sub(r"^arabic/?", "", path)
    return path.replace("/", "-") or "home"


def html_to_markdown(html: str, keep_contact_block: bool = False) -> str:
    """Turn a full web page into clean Markdown of just its main content."""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body or soup

    unwanted = list(CHROME_CLASSES)
    if not keep_contact_block:
        unwanted.append(CONTACT_BLOCK_CLASS)
    for css_class in unwanted:
        for element in body.find_all(class_=css_class):
            element.decompose()
    for element in body.find_all(class_=lambda c: c and "breadcrumb" in c):
        element.decompose()  # "Home / Pricing" trail
    for element in body.find_all(UNWANTED_TAGS):
        element.decompose()

    text = markdownify(str(body), heading_style="ATX", strip=["a"], bullets="-")
    return tidy(text)


def tidy(text: str) -> str:
    """Trim spaces and squeeze runs of blank lines into one."""
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def page_title(html: str) -> str:
    """The page's <title>, without the ' · IT Cybx' ending."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    return re.sub(r"\s*·\s*IT Cybx\s*$", "", title)


def sitemap_links(client: httpx.Client, url: str) -> list[str]:
    """All <loc> links in one sitemap file."""
    resp = client.get(url)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    return [loc.text.strip() for loc in root.iterfind(".//sm:loc", SITEMAP_NS)]


def list_pages(client: httpx.Client) -> list[str]:
    """Links of all pages, from the page sitemaps listed in wp-sitemap.xml.

    Only pages are read: blog posts belong to Phase 3.
    """
    links = []
    for sitemap in sitemap_links(client, f"{settings.site_base_url}/wp-sitemap.xml"):
        if "-posts-page-" in sitemap:
            links += sitemap_links(client, sitemap)
    return [url for url in links if page_name(url) not in SKIP_PAGES]


def fetch_page(client: httpx.Client, url: str) -> tuple[str, str]:
    """Download one page. Returns (language, markdown file content)."""
    resp = client.get(url)
    resp.raise_for_status()
    html = resp.text
    content = html_to_markdown(html, keep_contact_block=page_name(url) == "contact")
    return page_language(url), f"# {page_title(html)}\n\nSource: {url}\n\n{content}"


def run_now(knowledge_dir: Path = KNOWLEDGE_DIR, client: httpx.Client | None = None) -> list[Path]:
    """Download every page and write its knowledge file. Returns the files written."""
    client = client or httpx.Client(
        headers=HEADERS, timeout=30, follow_redirects=True
    )
    written = []
    with client:
        for url in list_pages(client):
            language, markdown = fetch_page(client, url)
            path = knowledge_dir / language / f"{page_name(url)}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(markdown, encoding="utf-8")
            written.append(path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Update knowledge files from the website.")
    parser.add_argument("--run-now", action="store_true", help="download all pages now")
    args = parser.parse_args()
    if not args.run_now:
        parser.print_help()
        return

    files = run_now()
    for path in files:
        size = len(path.read_text(encoding="utf-8"))
        print(f"  {path.relative_to(KNOWLEDGE_DIR)}  ({size} characters)")
    print(f"Done: {len(files)} pages saved to {KNOWLEDGE_DIR}")


if __name__ == "__main__":
    main()

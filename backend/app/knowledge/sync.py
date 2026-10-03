"""Keeps the bot's knowledge in step with the website.

    python -m app.knowledge.sync --run-now     check the site now
    python -m app.knowledge.sync --rollback    undo the last change

1. Read the list of pages from the site's sitemap (wp-sitemap.xml).
2. Download each page as visitors see it. (WordPress's REST API is not
   used for the text: this theme builds pages in PHP templates, so the API
   text is mostly empty, and for the privacy policy it is WordPress's
   unused default text.)
3. Remove the site header, menu, footer, cookie banner, forms and scripts.
4. Compare each page's fingerprint (hash) with the last one saved in
   kb_versions. Unchanged pages are left alone; changed, new and removed
   pages are updated, the old files are kept in knowledge/.history/ for
   rollback, and the team gets an email listing the changes.

The same check runs every week on SYNC_CRON (see start_scheduler).
knowledge/rules.md is never touched here.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify

from app.config import settings

log = logging.getLogger("chatbot.sync")

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"
LANGUAGES = ("en", "ar")

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


# ---- turning a page into Markdown --------------------------------------


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


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- reading the website ------------------------------------------------


def sitemap_links(client: httpx.Client, url: str) -> list[str]:
    """All <loc> links in one sitemap file."""
    resp = client.get(url)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    return [loc.text.strip() for loc in root.iterfind(".//sm:loc", SITEMAP_NS)]


# Page sitemaps from WordPress (wp-sitemap-posts-page-1.xml) or an SEO plugin
# such as Rank Math / Yoast (page-sitemap.xml, page-sitemap2.xml).
PAGE_SITEMAP = re.compile(r"(-posts-page-\d+|/page-sitemap\d*)\.xml$")


def list_pages(client: httpx.Client) -> list[str]:
    """Links of all pages, from the page sitemaps listed in the sitemap index.

    Only pages are read: blog posts belong to Phase 3.
    """
    links = []
    for sitemap in sitemap_links(client, f"{settings.site_base_url}/wp-sitemap.xml"):
        if PAGE_SITEMAP.search(sitemap):
            links += sitemap_links(client, sitemap)
    return [url for url in links if page_name(url) not in SKIP_PAGES]


class SiteLooksWrong(Exception):
    """The website answer looks broken, so nothing is changed."""


def fetch_page(client: httpx.Client, url: str) -> tuple[str, str]:
    """Download one page. Returns (language, markdown file content)."""
    resp = client.get(url)
    resp.raise_for_status()
    html = resp.text
    content = html_to_markdown(html, keep_contact_block=page_name(url) == "contact")
    return page_language(url), f"# {page_title(html)}\n\nSource: {url}\n\n{content}"


def download_site(client: httpx.Client | None = None) -> dict[str, str]:
    """Every page as {"en/pricing.md": markdown}."""
    client = client or httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True)
    pages = {}
    with client:
        for url in list_pages(client):
            language, markdown = fetch_page(client, url)
            pages[f"{language}/{page_name(url)}.md"] = markdown
    return pages


# ---- comparing and saving ----------------------------------------------


@dataclass
class SyncResult:
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    backup: Path | None = None

    @property
    def any(self) -> bool:
        return bool(self.added or self.changed or self.removed)


def local_files(knowledge_dir: Path) -> set[str]:
    return {f"{lang}/{p.name}" for lang in LANGUAGES for p in (knowledge_dir / lang).glob("*.md")}


def apply_changes(pages: dict[str, str], stored: dict[str, str], knowledge_dir: Path) -> SyncResult:
    """Write new/changed pages, delete removed ones, back up what is replaced.

    `stored` is the last fingerprint per file (from kb_versions). A page whose
    fingerprint matches, and whose file exists, is left alone.
    """
    result = SyncResult()
    existing = local_files(knowledge_dir)
    for name, markdown in sorted(pages.items()):
        if name not in existing:
            result.added.append(name)
        elif stored.get(name) != fingerprint(markdown):
            result.changed.append(name)
    result.removed = sorted(existing - set(pages))
    if not result.any:
        return result

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    result.backup = knowledge_dir / ".history" / stamp
    for name in result.changed + result.removed:
        target = result.backup / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(knowledge_dir / name, target)
    result.backup.mkdir(parents=True, exist_ok=True)
    (result.backup / "manifest.json").write_text(json.dumps(
        {"added": result.added, "changed": result.changed, "removed": result.removed}, indent=2))

    for name in result.added + result.changed:
        path = knowledge_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pages[name], encoding="utf-8")
    for name in result.removed:
        (knowledge_dir / name).unlink()
    return result


def rollback(knowledge_dir: Path = KNOWLEDGE_DIR) -> list[str]:
    """Undo the most recent sync that changed something. Returns the files restored."""
    history = sorted((knowledge_dir / ".history").glob("*/manifest.json"))
    if not history:
        return []
    backup = history[-1].parent
    manifest = json.loads(history[-1].read_text())
    for name in manifest["added"]:
        (knowledge_dir / name).unlink(missing_ok=True)
    for name in manifest["changed"] + manifest["removed"]:
        shutil.copy2(backup / name, knowledge_dir / name)
    shutil.rmtree(backup)
    return manifest["added"] + manifest["changed"] + manifest["removed"]


def change_email(result: SyncResult) -> tuple[str, str]:
    """Subject and body of the "website knowledge updated" email."""
    count = len(result.added) + len(result.changed) + len(result.removed)
    lines = ["The weekly website check updated the chatbot's knowledge.\n"]
    for label, names in (("New pages", result.added), ("Changed pages", result.changed),
                         ("Removed pages", result.removed)):
        if names:
            lines.append(f"{label}:\n" + "\n".join(f"  - {n}" for n in names) + "\n")
    lines.append("The bot is already using the new text. If something looks wrong, undo it with:\n"
                 "  docker compose exec api python -m app.knowledge.sync --rollback\n")
    return f"Chatbot knowledge updated: {count} page{'s' if count != 1 else ''}", "\n".join(lines)


def check_site(pages: dict[str, str], knowledge_dir: Path) -> None:
    """Refuse to sync if the site seems broken: no pages, or most pages gone.

    Protects the bot from losing its knowledge when the site is down, a
    plugin changes the sitemap, or the CDN blocks us.
    """
    existing = local_files(knowledge_dir)
    if not pages:
        raise SiteLooksWrong("the website returned no pages")
    if existing and len(existing - set(pages)) > len(existing) / 2:
        raise SiteLooksWrong(f"{len(existing - set(pages))} of {len(existing)} pages would be removed")


async def sync(knowledge_dir: Path = KNOWLEDGE_DIR, client: httpx.Client | None = None,
               notify: bool = True) -> SyncResult:
    """Check the website and update the knowledge files that changed."""
    from app.db import repo  # imported here so the extractor works without a database
    from app.leads.notify import send_text_email

    pages = await asyncio.to_thread(download_site, client)
    check_site(pages, knowledge_dir)
    stored = await repo.latest_kb_hashes()
    result = apply_changes(pages, stored, knowledge_dir)
    if result.any:
        await repo.record_kb_versions(
            {name: fingerprint(pages[name]) for name in result.added + result.changed}
        )
        if notify:
            try:
                await send_text_email(*change_email(result))
            except Exception as e:
                log.error("Sync email failed: %s", type(e).__name__)
    return result


# ---- weekly schedule ----------------------------------------------------


def cron_trigger(expression: str):
    """A trigger from a normal cron line like "0 3 * * 1" (Monday 03:00 UTC).

    APScheduler 3 counts weekdays from Monday=0, unlike cron (Sunday=0), so
    numeric weekdays are turned into names first.
    """
    from apscheduler.triggers.cron import CronTrigger

    minute, hour, day, month, weekday = expression.split()
    names = ["sun", "mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    weekday = re.sub(r"\d", lambda m: names[int(m.group())], weekday)
    return CronTrigger(minute=minute, hour=hour, day=day, month=month,
                       day_of_week=weekday, timezone="UTC")


def start_scheduler():
    """Run the website check on SYNC_CRON inside the API process."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    async def weekly():
        try:
            result = await sync()
        except SiteLooksWrong as e:
            log.error("Weekly sync stopped, nothing changed: %s", e)
            try:
                from app.leads.notify import send_text_email
                await send_text_email("Chatbot weekly website check stopped",
                                      f"Nothing was changed because {e}.\n"
                                      "Please check the website and its sitemap.")
            except Exception:
                pass
            return
        except Exception:
            log.exception("Weekly sync failed")
            return
        try:
            log.info("Weekly sync: %d added, %d changed, %d removed",
                     len(result.added), len(result.changed), len(result.removed))
        except Exception:
            log.exception("Weekly sync failed")

    scheduler = AsyncIOScheduler()
    scheduler.add_job(weekly, cron_trigger(settings.sync_cron), id="weekly-sync",
                      max_instances=1, coalesce=True)
    scheduler.start()
    return scheduler


# ---- command line -------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Update knowledge files from the website.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-now", action="store_true", help="check the website now")
    group.add_argument("--rollback", action="store_true", help="undo the last change")
    args = parser.parse_args()

    if args.rollback:
        restored = rollback()
        if not restored:
            print("Nothing to roll back.")
            return
        from app.db import repo

        asyncio.run(repo.record_kb_versions({
            name: fingerprint((KNOWLEDGE_DIR / name).read_text(encoding="utf-8"))
            for name in restored if (KNOWLEDGE_DIR / name).exists()
        }))
        print("Rolled back:\n" + "\n".join(f"  {n}" for n in restored))
        return

    try:
        result = asyncio.run(sync())
    except SiteLooksWrong as e:
        print(f"Stopped, nothing changed: {e}. Check the website and the sitemap.")
        return
    if not result.any:
        print("No changes: the knowledge already matches the website.")
        return
    for label, names in (("added", result.added), ("changed", result.changed),
                         ("removed", result.removed)):
        for name in names:
            print(f"  {label}: {name}")
    print(f"Done. Old versions saved in {result.backup}")


if __name__ == "__main__":
    main()

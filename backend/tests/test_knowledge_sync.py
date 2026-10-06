"""Tests for the website extractor. They use a fake website, no internet."""

import httpx
import pytest

from app.knowledge import sync
from app.knowledge.sync import KNOWLEDGE_DIR, html_to_markdown, page_language, page_name

PAGE = """
<html lang="en"><head><title>Pricing · IT Cybx</title><style>.x{}</style></head>
<body>
  <div class="itcybx-header-root"><nav>Home Pricing Contact</nav>+92 310 488 7999</div>
  <div class="itcbx-pricing-root">
    <div class="itcbx-pricing-breadcrumb">Home / Pricing</div>
    <h1>Clear Pricing</h1>
    <p>The <b>Growth Audit</b> is $150.</p>
    <ul><li>Store review</li><li>Funnel analysis</li></ul>
    <a href="/contact/">Book Your Growth Audit</a>
    <button>Get a Quote</button>
    <script>alert("x")</script>
  </div>
  <div class="itcbx-cta-root"><p>Let's Grow Your Store</p><form><label>Your Name</label></form></div>
  <div class="itcybx-footer-root">© 2026 IT Cybx</div>
  <div id="itcybx-cookie-banner" class="itcybx-ck">We use cookies</div>
</body></html>
"""


def test_keeps_page_content_as_markdown():
    md = html_to_markdown(PAGE)
    assert "# Clear Pricing" in md
    assert "The **Growth Audit** is $150." in md
    assert "- Store review" in md
    assert "Book Your Growth Audit" in md  # link text kept
    assert "/contact/" not in md  # link address dropped


def test_removes_site_chrome_scripts_forms_and_buttons():
    md = html_to_markdown(PAGE)
    for unwanted in ["Home Pricing Contact", "Home / Pricing", "+92 310", "© 2026", "We use cookies",
                     "alert", "Get a Quote", "Your Name"]:
        assert unwanted not in md


def test_contact_block_kept_only_when_asked():
    assert "Let's Grow Your Store" not in html_to_markdown(PAGE)
    assert "Let's Grow Your Store" in html_to_markdown(PAGE, keep_contact_block=True)


def test_language_and_file_name_from_url():
    assert page_language("https://itcybx.co.uk/pricing/") == "en"
    assert page_language("https://itcybx.co.uk/arabic/pricing/") == "ar"
    assert page_name("https://itcybx.co.uk/") == "home"
    assert page_name("https://itcybx.co.uk/arabic/") == "home"
    assert page_name("https://itcybx.co.uk/arabic/refund-cancellation-policy/") == "refund-cancellation-policy"


SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://itcybx.co.uk/wp-sitemap-posts-post-1.xml</loc></sitemap>
  <sitemap><loc>https://itcybx.co.uk/wp-sitemap-posts-page-1.xml</loc></sitemap>
</sitemapindex>"""

PAGE_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://itcybx.co.uk/sample-page/</loc></url>
  <url><loc>https://itcybx.co.uk/pricing/</loc></url>
  <url><loc>https://itcybx.co.uk/arabic/pricing/</loc></url>
</urlset>"""

POST_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://itcybx.co.uk/hello-world/</loc></url>
</urlset>"""


def fake_website(request: httpx.Request) -> httpx.Response:
    sitemaps = {
        "/wp-sitemap.xml": SITEMAP_INDEX,
        "/wp-sitemap-posts-page-1.xml": PAGE_SITEMAP,
        "/wp-sitemap-posts-post-1.xml": POST_SITEMAP,
    }
    if request.url.path in sitemaps:
        return httpx.Response(200, text=sitemaps[request.url.path])
    return httpx.Response(200, text=PAGE)


def test_pages_come_from_the_page_sitemap_only(monkeypatch):
    monkeypatch.setattr(sync.settings, "site_base_url", "https://itcybx.co.uk")
    client = httpx.Client(transport=httpx.MockTransport(fake_website))
    assert sync.list_pages(client) == [
        "https://itcybx.co.uk/pricing/",
        "https://itcybx.co.uk/arabic/pricing/",
    ]  # no sample page, no blog posts


def site_client(page=PAGE):
    def handler(request):
        resp = fake_website(request)
        return httpx.Response(200, text=page) if resp.text == PAGE else resp
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_download_site_names_one_file_per_page(monkeypatch):
    monkeypatch.setattr(sync.settings, "site_base_url", "https://itcybx.co.uk")
    pages = sync.download_site(site_client())
    assert sorted(pages) == ["ar/pricing.md", "en/pricing.md"]
    assert pages["en/pricing.md"].startswith("# Pricing\n\nSource: https://itcybx.co.uk/pricing/\n\n")


def first_sync(tmp_path):
    """Knowledge folder after a first sync of two pages; returns the pages."""
    (tmp_path / "rules.md").write_text("my rules", encoding="utf-8")
    pages = {"en/pricing.md": "price v1", "en/about.md": "about v1"}
    result = sync.apply_changes(pages, tmp_path)
    assert result.added == ["en/about.md", "en/pricing.md"]
    return pages


def test_second_sync_with_no_site_change_changes_nothing(tmp_path):
    pages = first_sync(tmp_path)
    result = sync.apply_changes(pages, tmp_path)
    assert not result.any
    assert result.backup is None


def test_changed_page_is_updated_and_old_version_kept(tmp_path):
    pages = first_sync(tmp_path)
    result = sync.apply_changes({**pages, "en/pricing.md": "price v2"}, tmp_path)
    assert result.changed == ["en/pricing.md"] and not result.added
    assert (tmp_path / "en/pricing.md").read_text(encoding="utf-8") == "price v2"
    assert (result.backup / "en/pricing.md").read_text(encoding="utf-8") == "price v1"


def test_older_file_on_disk_is_refreshed_even_if_the_site_did_not_change(tmp_path):
    # A redeploy brought back an older file than the last sync wrote.
    pages = first_sync(tmp_path)
    (tmp_path / "en/about.md").write_text("about v0 (from the old image)", encoding="utf-8")
    result = sync.apply_changes(pages, tmp_path)
    assert result.changed == ["en/about.md"]
    assert (tmp_path / "en/about.md").read_text(encoding="utf-8") == "about v1"


def test_removed_page_is_deleted_and_backed_up(tmp_path):
    pages = first_sync(tmp_path)
    result = sync.apply_changes({"en/pricing.md": "price v1"}, tmp_path)
    assert result.removed == ["en/about.md"]
    assert not (tmp_path / "en/about.md").exists()


def test_rollback_restores_previous_version(tmp_path):
    pages = first_sync(tmp_path)
    sync.apply_changes({"en/pricing.md": "price v2", "en/new.md": "new page"}, tmp_path)

    restored = sync.rollback(tmp_path)

    assert sorted(restored) == ["en/about.md", "en/new.md", "en/pricing.md"]
    assert (tmp_path / "en/pricing.md").read_text(encoding="utf-8") == "price v1"
    assert (tmp_path / "en/about.md").read_text(encoding="utf-8") == "about v1"
    assert not (tmp_path / "en/new.md").exists()


def test_sync_never_touches_rules(tmp_path):
    pages = first_sync(tmp_path)
    sync.apply_changes({"en/pricing.md": "price v2"}, tmp_path)
    sync.rollback(tmp_path)
    assert (tmp_path / "rules.md").read_text(encoding="utf-8") == "my rules"


def test_change_email_lists_pages_and_rollback_command():
    result = sync.SyncResult(changed=["en/pricing.md"], added=["ar/blog.md"])
    subject, body = sync.change_email(result)
    assert subject == "Chatbot knowledge updated: 2 pages"
    assert "en/pricing.md" in body and "ar/blog.md" in body
    assert "python -m app.knowledge.sync --rollback" in body


def test_weekly_schedule_runs_on_monday_3am_utc():
    from datetime import datetime, timezone
    trigger = sync.cron_trigger("0 3 * * 1")
    nxt = trigger.get_next_fire_time(None, datetime(2026, 10, 3, tzinfo=timezone.utc))  # a Saturday
    assert (nxt.strftime("%A"), nxt.hour, nxt.minute) == ("Monday", 3, 0)


def test_bot_rereads_knowledge_after_a_file_changes(tmp_path, monkeypatch):
    import os
    from app.knowledge import loader
    (tmp_path / "en").mkdir()
    (tmp_path / "rules.md").write_text("RULES", encoding="utf-8")
    page = tmp_path / "en" / "pricing.md"
    page.write_text("old price", encoding="utf-8")
    monkeypatch.setattr(loader, "KNOWLEDGE_DIR", tmp_path)
    loader.reload()
    assert "old price" in loader.get_context("q", "en")

    page.write_text("new price!", encoding="utf-8")
    os.utime(page, ns=(page.stat().st_atime_ns, page.stat().st_mtime_ns + 1_000_000))

    assert "new price!" in loader.get_context("q", "en")
    loader.reload()


def test_rules_file_has_the_key_rules():
    rules = (KNOWLEDGE_DIR / "rules.md").read_text(encoding="utf-8")
    assert rules.startswith("# IT Cybx Assistant Rules")
    assert 'Never call it an "agency".' in rules
    assert "Growth Sprint and Growth Retainer: never quote a price." in rules
    assert "Never pretend to be human" in rules


def test_rank_math_page_sitemap_is_read(monkeypatch):
    monkeypatch.setattr(sync.settings, "site_base_url", "https://itcybx.co.uk")
    index = SITEMAP_INDEX.replace("wp-sitemap-posts-page-1.xml", "page-sitemap.xml").replace(
        "wp-sitemap-posts-post-1.xml", "post-sitemap.xml")

    def handler(request):
        files = {"/wp-sitemap.xml": index, "/page-sitemap.xml": PAGE_SITEMAP, "/post-sitemap.xml": POST_SITEMAP}
        return httpx.Response(200, text=files.get(request.url.path, PAGE))

    pages = sync.list_pages(httpx.Client(transport=httpx.MockTransport(handler)))
    assert pages == ["https://itcybx.co.uk/pricing/", "https://itcybx.co.uk/arabic/pricing/"]


def test_broken_site_changes_nothing(tmp_path):
    first_sync(tmp_path)
    with pytest.raises(sync.SiteLooksWrong):
        sync.check_site({}, tmp_path)
    with pytest.raises(sync.SiteLooksWrong):
        sync.check_site({"en/x.md": "x"}, tmp_path)  # both real pages would vanish
    assert (tmp_path / "en/pricing.md").exists()


def test_only_the_newest_backups_are_kept(tmp_path):
    for i in range(25):
        (tmp_path / ".history" / f"20261006-0000{i:02d}").mkdir(parents=True)
    sync.prune_history(tmp_path, keep=20)
    left = sorted(p.name for p in (tmp_path / ".history").iterdir())
    assert len(left) == 20 and left[0] == "20261006-000005"

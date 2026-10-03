"""Tests for the website extractor. They use a fake website, no internet."""

import httpx

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


def test_run_now_writes_one_file_per_page(tmp_path, monkeypatch):
    monkeypatch.setattr(sync.settings, "site_base_url", "https://itcybx.co.uk")
    client = httpx.Client(transport=httpx.MockTransport(fake_website))

    written = sync.run_now(knowledge_dir=tmp_path, client=client)

    assert sorted(p.relative_to(tmp_path).as_posix() for p in written) == ["ar/pricing.md", "en/pricing.md"]
    text = (tmp_path / "en" / "pricing.md").read_text(encoding="utf-8")
    assert text.startswith("# Pricing\n\nSource: https://itcybx.co.uk/pricing/\n\n")
    assert "Growth Audit" in text


def test_run_now_never_touches_rules(tmp_path):
    rules = tmp_path / "rules.md"
    rules.write_text("my rules", encoding="utf-8")
    client = httpx.Client(transport=httpx.MockTransport(fake_website))

    sync.run_now(knowledge_dir=tmp_path, client=client)

    assert rules.read_text(encoding="utf-8") == "my rules"


def test_rules_file_has_the_key_rules():
    rules = (KNOWLEDGE_DIR / "rules.md").read_text(encoding="utf-8")
    assert rules.startswith("# IT Cybx Assistant Rules")
    assert 'Never call it an "agency".' in rules
    assert "Growth Sprint and Growth Retainer: never quote a price." in rules
    assert "Never pretend to be human" in rules

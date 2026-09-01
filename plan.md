# IT Cybx Live Bot

A production-grade, bilingual (English/Arabic) AI agent chatbot built for **itcybx.co.uk** — an e-commerce growth studio (Shopify/Salla/Zid builds + growth marketing for beauty/lifestyle brands in Saudi Arabia and the UK).

This is **not** a simple FAQ bot. It is a real conversational agent that:
- Answers visitor questions using only verified, human-reviewed content from the real website (no hallucinated/guessed answers)
- Follows the site's language automatically (English site → English bot, Arabic site → Arabic bot)
- Diagnoses visitor problems and connects them to the right service
- Checks meeting availability and books a Growth Audit call via Calendly
- Notifies the internal team when a meeting is booked or a hot lead appears
- Captures lead info even when a visitor doesn't book
- Returns a clear static "I don't know" message instead of guessing when information isn't in its knowledge base

---

## 1. Project Goals

| Goal | Why it matters |
|---|---|
| Accurate, source-grounded answers | The client is a real business — wrong info (pricing, policies, services) damages trust and could cause real problems |
| No hallucinated fallback answers | If the bot doesn't know something, it must say so with a static message and point to a human — never guess |
| Bilingual (EN/AR), not just translated | The real site has an English/Arabic switcher; the bot must feel native in both, not machine-translated |
| Real "agent" behavior, not static Q&A | The bot should hold context, ask clarifying questions, and proactively move qualified visitors toward booking |
| Real meeting booking, not a form redirect | Visitors should be able to check availability and book a call directly inside the chat conversation |
| Human-reviewed knowledge base | Website content (including sitemap-listed pages) is manually vetted before being fed to the bot — see Section 6 |

---

## 2. Final Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| Agent framework | **LangGraph** (built on LangChain) | Multi-step agent orchestration: state, branching, tool-calling — needed for the booking flow (qualify → check slots → book → confirm) |
| LLM | **Mistral AI** (swappable to Claude/OpenAI) | Generates responses; strong multilingual (Arabic) support |
| Vector database | **Pinecone** (free/Starter tier) | Stores embedded website content for retrieval (RAG) |
| Embeddings | **OpenAI `text-embedding-3-small`** or **Voyage AI** | Converts text chunks into vectors; multilingual-capable |
| Backend framework | **Python + FastAPI** | Serves the chat API, async-friendly, supports streaming |
| Session memory | **Redis** | Stores per-session conversation history so the agent has real context across turns |
| Structured data storage | **PostgreSQL** (or Supabase) | Stores leads, bookings, escalation logs, analytics |
| Meeting scheduling | **Calendly API** | Handles available slots, booking creation, calendar invites, reminder emails, and meeting links automatically |
| Team notifications | **Slack Incoming Webhook** (+ optional email via Resend/SendGrid) | Alerts the internal team on new bookings or high-intent/frustrated visitors |
| Frontend widget | **React + Tailwind CSS** | Chat UI embedded into the WordPress site via a script tag; detects page language and switches RTL/LTR |
| Hosting | **Railway** or **Render** | Backend + Redis + Postgres hosting |
| Source control | **GitHub** (private repo) | `itcybx_live_bot` |

---

## 3. High-Level Architecture

```
WordPress site (itcybx.co.uk)
   └── Embedded JS widget (React + Tailwind, detects EN/AR via page language)
          ↓ (fetch / streaming)
   FastAPI backend
          ├── LangGraph agent (Mistral LLM)
          │     ├── Tool: search_knowledge_base   → Pinecone (separate EN / AR collections)
          │     ├── Tool: check_availability       → Calendly API
          │     ├── Tool: book_meeting             → Calendly API
          │     ├── Tool: capture_lead             → PostgreSQL
          │     └── Tool: escalate_to_human        → Slack webhook
          ├── Redis (per-session conversation memory)
          └── PostgreSQL (leads, bookings, logs)
```

**Core mechanic — how the agent "does things":** the LLM itself cannot take actions. Each capability (search knowledge base, check calendar, book meeting, notify team) is implemented as a Python function ("tool") with a clear description. The LLM decides *when* and *with what arguments* to call a tool; the backend code actually executes it and returns the result to the LLM to continue the conversation.

---

## 4. Fallback / Anti-Hallucination Rules (critical, non-negotiable)

The bot must **never guess**. Two layers of protection:

1. **Retrieval confidence check** — before calling the LLM, check the vector similarity score of the top retrieved result. If it's below threshold (nothing relevant found), skip the LLM entirely and return the static fallback message.
2. **Strict prompt instruction** — even after retrieval passes, the system prompt instructs the LLM to answer *only* from provided context and respond with an exact sentinel string (e.g. `NOT_FOUND`) if the context doesn't fully answer the question. The backend swaps this for the static fallback message before showing it to the user.

Additionally: if the backend/API call fails outright (timeout, server error), return a static "I'm currently offline" message — never let an exception surface a broken or partial answer to the user.

Static fallback example (EN):
> "I'm not able to find this information right now. Please contact our team directly at info@itcybx.co.uk or +44 793 389 5500, and they'll help you out."

Static fallback example (AR):
> "لا يمكنني العثور على هذه المعلومة حالياً. يرجى التواصل مع فريقنا عبر info@itcybx.co.uk أو +44 793 389 5500."

---

## 5. Bilingual Strategy (English / Arabic)

- The website's language switcher was checked; the **English sitemap contains no Arabic URLs and no hreflang alternate tags**, meaning Arabic is likely a thin/incomplete layer on the live site (not fully mirrored content).
- **Decision:** rather than scraping unreliable/incomplete Arabic pages, the Arabic knowledge base will be built by carefully translating the verified English content (human-reviewed translation, not raw machine translation) to guarantee accuracy.
- Two **separate Pinecone collections** are maintained: `kb_en` and `kb_ar`. Keeping them separate (rather than one mixed-language index) avoids retrieval quality issues from mixed-language embeddings.
- The **frontend widget detects the page's current language** (via `document.documentElement.lang` or URL path `/ar/`) and passes it to the backend with every request — the backend then uses the matching language's system prompt, fallback messages, and knowledge base collection.
- UI text (placeholders, buttons) and layout direction (`dir="rtl"` for Arabic) also switch based on detected language.

---

## 6. Knowledge Base — Source Content & Review Process

Website content is pulled via **Yoast SEO's XML sitemap** (`https://itcybx.co.uk/page-sitemap.xml`, `portfolio-sitemap.xml`), using LangChain's `SitemapLoader` — not manual/custom scraping code.

**Important finding during vetting:** the sitemap includes a `/our-team/` page listing fake placeholder staff (e.g. "Ann Bridge, Senior Digital Strategist" with generic stock photos) — leftover demo content from the site's WordPress theme ("Ewebot"). This page is **not linked anywhere in the live site's navigation or footer**, confirming it's an orphaned page, not real content. **It is explicitly excluded from the knowledge base.**

**Review process (repeatable, not one-time):**
1. Run the sitemap loader script — it fetches and previews each page's content, saving nothing to the vector DB yet.
2. Manually review each preview: is it linked from real site navigation/footer? Is the content genuine and current?
3. Only URLs added to `data/approved/approved_urls_en.txt` (and the AR equivalent once translated) are embedded into Pinecone.
4. Re-run this review whenever site content changes (new pricing, new case studies, etc.).

**Approved English source pages (confirmed real, linked, current):**
- Home (`/`)
- The Growth Audit (`/the-growth-audit/`)
- What We Do (`/what-we-do/`)
- Our Work (`/our-work/`) + individual portfolio/case study pages
- About Us (`/about-us/`)
- Pricing (`/pricing-plans/`)
- Contact Us (`/contact-us/`)
- Privacy Policy, Terms & Conditions, Refund & Cancellation Policy, Cookie Policy (all footer-linked, legitimate)

**Excluded:**
- `/our-team/` (orphaned, fake placeholder content)
- `/team-sitemap.xml`, `/team_category-sitemap.xml`, `/portfolio_category-sitemap.xml`, `/portfolio_tag-sitemap.xml` (taxonomy archives, not real content)
- `/blog/` (pending a content-quality check — include only if it has real, substantive posts)

---

## 7. Agent Tools (capabilities)

| Tool | Function | Backing service |
|---|---|---|
| `search_knowledge_base` | RAG lookup against approved site content | Pinecone (`kb_en` / `kb_ar`) |
| `check_availability` | Checks open meeting slots | Calendly API |
| `book_meeting` | Creates a booking, triggers Calendly's automatic confirmation email + calendar invite + reminders | Calendly API |
| `capture_lead` | Saves partial lead info (name/email/interest) even if the visitor doesn't book | PostgreSQL |
| `escalate_to_human` | Sends an immediate alert for high-intent or frustrated visitors | Slack webhook |

Calendly is used specifically because it already handles slot availability, double-booking prevention, calendar invites, meeting links, and reminder emails automatically — the agent only needs to call its API, not build scheduling logic from scratch.

---

## 8. Project Folder Structure

```
itcybx_live_bot/
│
├── venv/                              (gitignored)
│
├── data/
│   ├── raw/                           # unprocessed scraped content (gitignored)
│   ├── approved/
│   │   ├── approved_urls_en.txt
│   │   └── approved_urls_ar.txt
│   └── processed/
│       ├── en/
│       └── ar/
│
├── src/
│   ├── config/
│   │   └── settings.py                # loads .env, central config
│   ├── loaders/
│   │   ├── sitemap_loader.py          # pulls URLs from sitemap via LangChain SitemapLoader
│   │   └── content_cleaner.py         # strips nav/footer junk, cleans text
│   ├── knowledge_base/
│   │   ├── embedder.py                # text -> embeddings
│   │   └── vectorstore.py             # Pinecone connection + upsert/query logic
│   ├── agent/
│   │   ├── graph.py                   # LangGraph agent (states/nodes/edges)
│   │   ├── prompts_en.py
│   │   └── prompts_ar.py
│   ├── tools/
│   │   ├── faq_tool.py
│   │   ├── booking_tool.py
│   │   ├── lead_tool.py
│   │   └── escalation_tool.py
│   ├── memory/
│   │   └── session_store.py           # Redis conversation history
│   └── api/
│       ├── main.py                    # FastAPI entrypoint
│       └── routes/
│           └── chat.py                # /chat endpoint
│
├── frontend/                          # React widget (separate sub-project, built later)
│
├── tests/
│   └── test_sitemap_loader.py
│
├── scripts/
│   └── build_knowledge_base.py        # one-off: re-index knowledge base
│
├── requirements.txt
├── .env                               # real API keys (gitignored, never committed)
├── .env.example                       # template of required keys, no real values
├── .gitignore
└── README.md
```

---

## 9. Environment Variables (`.env.example`)

```
MISTRAL_API_KEY=
PINECONE_API_KEY=
CALENDLY_API_KEY=
REDIS_URL=
SLACK_WEBHOOK_URL=
DATABASE_URL=
```

---

## 10. Build Phases (current plan, in order)

1. **Phase 1 — Sitemap loading + content review**
   Load approved sitemap URLs, extract clean text, preview for manual review. No vector DB writes yet.
2. **Phase 2 — Knowledge base (RAG)**
   Embed approved content into Pinecone (`kb_en`), build retrieval + similarity-threshold fallback logic. Prove plain FAQ answering works via terminal before adding agent behavior.
3. **Phase 3 — Agent + first tool**
   Wrap the RAG lookup as a LangGraph agent tool. Introduce basic multi-turn memory.
4. **Phase 4 — Booking tool**
   Add `check_availability` and `book_meeting` via Calendly API.
5. **Phase 5 — Lead capture + escalation tools**
   Add `capture_lead` and `escalate_to_human`.
6. **Phase 6 — Bilingual**
   Build/translate the Arabic knowledge base (`kb_ar`), add language-aware prompts and fallback messages.
7. **Phase 7 — Backend API + session memory**
   Wrap the agent in FastAPI, add Redis-backed conversation history.
8. **Phase 8 — Frontend widget**
   Build the React + Tailwind chat widget, detect page language, embed into WordPress via script tag.
9. **Phase 9 — Hosting + deployment**
   Deploy backend (Railway/Render), connect Redis/Postgres, go live.

---

## 11. Notes for Future Contributors / AI Coding Assistants

- This project prioritizes **accuracy over completeness** — it is better for the bot to say "I don't know" than to guess, especially on pricing, policies, or business facts.
- Do **not** treat every sitemap-listed URL as trustworthy content — some pages (e.g. `/our-team/`) are orphaned leftover theme content not linked anywhere on the live site. Always cross-check against real site navigation/footer before adding a page to the approved list.
- English and Arabic content/knowledge bases are kept **separate**, not mixed in one index.
- Booking/scheduling logic should **not** be built from scratch — always delegate to the Calendly API.
- The project owner is new to LangChain/LangGraph and is learning by building this incrementally, phase by phase (see Section 10) — code should be introduced piece by piece with explanations, not delivered as one large finished system.

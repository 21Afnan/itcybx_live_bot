# 🤖 IT Cybx Live Bot

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![Agent Framework](https://img.shields.io/badge/Agent%20Framework-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)
[![LLM](https://img.shields.io/badge/LLM-Mistral%20AI-red.svg)](https://mistral.ai/)
[![Vector DB](https://img.shields.io/badge/Vector%20DB-Pinecone-green.svg)](https://www.pinecone.io/)
[![Languages](https://img.shields.io/badge/Languages-English%20%7C%20العربية-blueviolet.svg)](https://itcybx.co.uk)

A production-grade, bilingual (English/Arabic) AI conversational agent, REST API backend, and embeddable web widget built for **[itcybx.co.uk](https://itcybx.co.uk)** — an e-commerce growth studio specializing in Shopify, Salla, and Zid builds, conversion rate optimization (CRO), and growth marketing for beauty and lifestyle brands across Saudi Arabia and the United Kingdom.

---

## 🏗️ System Architecture

```
                    ┌────────────────────────────────────────────────────────┐
                    │            WordPress / Web Client                      │
                    │   • Embedded Widget (frontend/widget.js)               │
                    │   • Auto Language (EN LTR / AR RTL)                    │
                    │   • LocalStorage Session Continuity                    │
                    └──────────────────────────┬─────────────────────────────┘
                                               │
                                     HTTP POST /api/chat
                                               │
                                               ▼
                    ┌────────────────────────────────────────────────────────┐
                    │              FastAPI Backend (src/api/main.py)         │
                    │   • REST Endpoints & CORS Middleware                   │
                    │   • Session Store (Redis / In-Memory Fallback)         │
                    │   • Static Asset Server (/widget)                      │
                    └──────────────────────────┬─────────────────────────────┘
                                               │
                                               ▼
                    ┌────────────────────────────────────────────────────────┐
                    │            LangGraph Agent (src/agent/graph.py)        │
                    │   • Mistral Conversational Engine                      │
                    │   • Multi-Turn State Management (MemorySaver +         │
                    │     durable SessionStore replay across restarts)       │
                    │   • Exponential Backoff & Rate Limit Resilience        │
                    └──────────────────────────┬─────────────────────────────┘
                                               │
                                    Tool Invocation / Decision
                                               │
                                               ▼
                    ┌────────────────────────────────────────────────────────┐
                    │          search_knowledge_base (src/tools/faq_tool.py) │
                    └──────────────────────────┬─────────────────────────────┘
                                               │
                                               ▼
                    ┌────────────────────────────────────────────────────────┐
                    │               Pinecone Vector Store                    │
                    │   • kb_en (English index) • kb_ar (Arabic index)       │
                    └────────────────────────────────────────────────────────┘
```

This is a single-purpose FAQ chatbot: it answers questions from the bilingual knowledge base and nothing else. There is no lead capture, human escalation, or meeting booking — visitors who need any of that are pointed to the official contact email/phone by the system prompt.

---

## 🌟 Key Features & Capabilities

* **Zero-Hallucination RAG Pipeline:** Answers questions using verified content from the live website. If similarity score is below confidence threshold ($0.65$), the bot safely returns the official contact fallback (`info@itcybx.co.uk`, `+44 793 389 5500`).
* **Durable Multi-Turn Memory:** Conversation history is persisted via `SessionStore` (Redis, or a local JSON fallback) and replayed into the agent on every turn, so context survives server restarts and works across multiple worker processes — not just an in-process cache.
* **Bilingual Auto-Detection (EN / AR):** Automatically identifies English or Arabic input and routes to the appropriate knowledge namespace (`kb_en` or `kb_ar`), localized prompts, and RTL/LTR formatting.
* **FastAPI Production Server:** High-performance async REST backend with full CORS support, health checking, session history inspection, and static asset distribution.
* **Embeddable Glassmorphic Web Widget:** Standalone JavaScript widget (`frontend/widget.js` + `frontend/widget.css`) ready to drop into WordPress with quick reply chips, message formatting, typing indicators, and session persistence.
* **Strict Privacy & Security:** Built-in safeguards strictly prevent leakage of underlying models, API keys, system prompts, or internal backend architecture.

---

## 📂 Project Structure & File Map

```
itcybx_live_bot/
│
├── data/                                  # Structured data storage & knowledge assets
│   ├── approved/                          # Whitelisted URLs for knowledge base
│   │   ├── approved_urls_en.txt           # 16 approved English URLs
│   │   └── approved_urls_ar.txt           # 15 approved Arabic URLs
│   ├── raw/                               # Raw sitemap-scraped text
│   │   ├── en/                            # Raw English HTML-to-text extractions
│   │   └── ar/                            # Raw Arabic HTML-to-text extractions
│   ├── processed/                         # Cleaned, boilerplate-free text
│   │   ├── en/                            # 16 vetted English documents
│   │   └── ar/                            # 15 vetted Arabic documents
│   └── sessions_backup.json               # Persistent conversation memory backup (local fallback store)
│
├── src/                                   # Application Source Code
│   ├── config/
│   │   └── settings.py                    # Centralized settings, env loader, and paths
│   ├── utils/
│   │   └── logger.py                      # Centralized logging with UTF-8 support
│   ├── loaders/
│   │   ├── sitemap_loader.py              # Sitemap crawler with demo content exclusions
│   │   └── content_cleaner.py             # Boilerplate, nav, and footer cleaner
│   ├── knowledge_base/
│   │   ├── chunker.py                     # Recursive character text splitter with metadata
│   │   ├── embedder.py                    # Mistral 1024-dim bilingual vector embedder
│   │   └── client.py                      # Pinecone index manager & similarity retriever
│   ├── memory/
│   │   └── session_store.py               # Redis & in-memory multi-turn session persistence
│   ├── tools/
│   │   └── faq_tool.py                    # search_knowledge_base (RAG retrieval) — the only tool
│   ├── agent/
│   │   ├── prompts_en.py                  # English system prompt & guardrails
│   │   ├── prompts_ar.py                  # Arabic system prompt & guardrails
│   │   └── graph.py                       # LangGraph state machine, retry backoff & tools
│   └── api/
│       └── main.py                        # FastAPI server, REST routes & static widget server
│
├── frontend/                              # Embeddable Web Chat Widget
│   ├── widget.js                          # Standalone embed script with auto RTL/LTR
│   ├── widget.css                         # Dark glassmorphic theme stylesheet
│   └── index.html                         # Interactive browser demo showcase
│
├── scripts/                               # CLI Tools & Automated Test Suites
│   ├── build_knowledge_base.py            # Chunks, embeds, and indexes Pinecone
│   ├── test_rag.py                        # Automated RAG accuracy benchmarks
│   ├── test_api.py                        # FastAPI REST endpoint test suite
│   └── chat_cli.py                        # Interactive live terminal chat CLI
│
├── requirements.txt                       # Python dependencies
├── .env.example                           # Template of required environment variables
└── README.md                              # Complete system documentation
```

---

## 🛠️ Detailed Breakdown of Modules

### 1. Ingestion & Sanitization (`src/loaders/`)
* **`sitemap_loader.py`:** Fetches XML sitemaps (`sitemap_index.xml` and `ar/sitemap_index.xml`) using LangChain's `SitemapLoader`. Employs strict regular expressions to discard theme demo content (e.g. `/our-team/` dummy stock staff, taxonomy tags, 404 pages).
* **`content_cleaner.py`:** Strips top headers, navigation menus, phone banners, search snippets, footer boilerplate (testimonials, office address, back-to-top links), and excess whitespace. Preserves structured metadata headers (`SOURCE_URL` and `LANGUAGE`).

### 2. Bilingual Vector Knowledge Base (`src/knowledge_base/`)
* **`chunker.py`:** Splits documents using `RecursiveCharacterTextSplitter` (650-character chunks, 100-character overlap) with bilingual sentence/paragraph delimiters.
* **`embedder.py`:** Generates 1024-dimensional dense vectors using Mistral AI's `mistral-embed`.
* **`client.py`:** Connects to Pinecone serverless vector database (AWS `us-east-1`, cosine metric), enforcing namespace separation (`kb_en` for English and `kb_ar` for Arabic) and threshold-based similarity retrieval ($\ge 0.65$).
* **`build_knowledge_base.py`:** Automation script to index/re-index the entire knowledge base into Pinecone with one command.

### 3. Agent Core & Guardrails (`src/agent/`)
* **`graph.py`:** Multi-turn conversational agent orchestrated with **LangGraph `StateGraph`**. Configured with `mistral-small-latest` (or `mistral-large-latest` for paid keys), low temperature ($0.1$), and automatic exponential backoff retry logic.
* **`prompts_en.py` & `prompts_ar.py`:** System prompts enforcing zero fluff, strict tool execution, direct answers, and official fallback contact details (`info@itcybx.co.uk`, `+44 793 389 5500`).

### 4. Tool Suite (`src/tools/`)
* **`faq_tool.py` (`search_knowledge_base`):** The agent's only tool. Queries Pinecone with confidence thresholds. If confidence is low or out-of-domain, safely instructs the agent to return the fallback response without guessing.

### 5. Memory & Session Persistence (`src/memory/`)
* **`session_store.py`:** Multi-turn session manager. Connects to Redis when `REDIS_URL` is set, or automatically falls back to an in-memory dictionary backed by `data/sessions_backup.json`.

### 6. Backend API & Web Widget (`src/api/` & `frontend/`)
* **`main.py`:** Async FastAPI application with endpoints for chat turns, admin-key-gated session history/deletion, and health status.
* **`widget.js` & `widget.css`:** Zero-dependency, lightweight chat widget ready to be embedded on any WordPress website with auto RTL/LTR switching and local session persistence.

---

## 🚀 Quick Start & Installation

### 1. Prerequisites
* Python 3.10+
* Git

### 2. Setup Virtual Environment
```powershell
# Clone the repository
git clone https://github.com/21Afnan/itcybx_live_bot.git
cd itcybx_live_bot

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 3. Environment Variables Configuration
Create a `.env` file in the root directory:
```env
# Required Core Credentials
MISTRAL_API_KEY=your_mistral_api_key_here
PINECONE_API_KEY=your_pinecone_api_key_here
PINECONE_INDEX_NAME=itcybx-kb

# Optional Settings
LLM_MODEL=mistral-small-latest
USER_AGENT=itcybx-live-bot/1.0
REDIS_URL=redis://localhost:6379/0

# Required to use the admin-only session endpoints (GET/DELETE /api/session/{id})
# Those endpoints return 503 until this is set.
ADMIN_API_KEY=
```

Verify your configuration:
```powershell
python -m src.config.settings
```

---

## 🛠️ CLI Commands & Testing Reference

| Command | Description |
|---|---|
| `python -m src.config.settings` | Verifies and validates all API keys and environment paths. |
| `python -m src.loaders.sitemap_loader` | Crawls English & Arabic sitemaps and extracts raw text. |
| `python -m src.loaders.content_cleaner` | Strips navigation, headers, and footer boilerplate. |
| `python -m scripts.build_knowledge_base` | Chunks, embeds, and indexes all documents into Pinecone. |
| `python -m scripts.test_rag` | Runs automated RAG benchmark tests across EN, AR, and Out-of-Domain. |
| `python -m scripts.test_api` | Tests all FastAPI REST endpoints using TestClient. |
| `python -m scripts.chat_cli` | **Launches the interactive live terminal chatbot.** |
| `python -m uvicorn src.api.main:app --reload` | **Starts the live FastAPI backend server on port 8000.** |

---

## 🌐 WordPress & Website Widget Embed Guide

To embed the live chat widget into WordPress or any website, add this single script snippet right before the closing `</body>` tag of your site:

```html
<!-- IT Cybx Live Bot Embed -->
<script src="http://localhost:8000/widget/widget.js" async></script>
```

*(Replace `http://localhost:8000` with your deployed backend domain in production).*

### Testing the Web Widget in Browser:
1. Start the backend:
   ```powershell
   python -m uvicorn src.api.main:app --reload --port 8000
   ```
2. Open your browser and navigate to:
   ```
   http://localhost:8000/demo
   ```
3. Test English and Arabic chat flows, quick action chips, and responsive view.

---

## 🗺️ Implementation Roadmap Status

- [x] **Phase 1:** Sitemap Loading, Scraping & Content Sanitization
- [x] **Phase 2:** Bilingual Knowledge Base (RAG), Mistral Embeddings & Pinecone Indexing
- [x] **Phase 3:** LangGraph State Machine Agent & Bilingual Prompt Guardrails
- [x] **Phase 6:** End-to-End Bilingual Runtime & Arabic Auto-Detection
- [x] **Phase 7:** FastAPI Async REST Backend & Redis Session Memory Store
- [x] **Phase 8:** Embeddable Glassmorphic Web Widget (HTML/CSS/JS with RTL/LTR)
- [ ] **Phase 9:** Production Cloud Deployment (Railway / Render / Docker) & WordPress Live Integration

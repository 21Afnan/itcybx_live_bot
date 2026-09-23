# 🤖 IT Cybx Live Bot

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Framework](https://img.shields.io/badge/Agent%20Framework-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)
[![LLM](https://img.shields.io/badge/LLM-Mistral%20AI-red.svg)](https://mistral.ai/)
[![VectorDB](https://img.shields.io/badge/Vector%20DB-Pinecone-green.svg)](https://www.pinecone.io/)
[![Languages](https://img.shields.io/badge/Languages-English%20%7C%20العربية-blueviolet.svg)](https://itcybx.co.uk)

A production-grade, bilingual (English/Arabic) AI conversational agent built for **[itcybx.co.uk](https://itcybx.co.uk)** — an e-commerce growth studio specializing in Shopify, Salla, and Zid builds, conversion rate optimization (CRO), and growth marketing for beauty and lifestyle brands across Saudi Arabia and the UK.

---

## 🏗️ Architecture Overview

```
                        ┌───────────────────────────────┐
                        │   User / WordPress Website    │
                        │    (English / Arabic Site)    │
                        └───────────────┬───────────────┘
                                        │
                                        ▼
                        ┌───────────────────────────────┐
                        │     LangGraph State Agent     │
                        │    (Mistral Conversational)   │
                        └───────┬───────────────▲───────┘
                                │               │
          Tool Invocation Loop  │               │ Verified Context &
                                ▼               │ Booking Confirmations
                        ┌───────────────────────┴───────┐
                        │        Agent Tool Suite       │
                        │ ├── search_knowledge_base     │
                        │ ├── check_availability (Sun-Thu 12-5)
                        │ └── book_meeting (Local / Cal)│
                        └───────┬───────────────────────┘
                                │
                                ▼
                        ┌───────────────────────────────┐
                        │     Pinecone Vector Store     │
                        │   ├── kb_en (English Docs)    │
                        │   └── kb_ar (Arabic Docs)     │
                        └───────────────────────────────┘
```

---

## 🌟 Key Features & Guardrails

* **Zero-Hallucination RAG Pipeline:** Answers questions using only verified content from the live website. If similarity score is below confidence threshold ($0.65$), the bot safely returns the official contact fallback.
* **Meeting Booking & Schedule Enforcement:** Built-in scheduling respecting IT Cybx business hours (**Sunday to Thursday, 12:00 PM to 5:00 PM**). Prospective clients can view real-time open slots and book appointments in both English and Arabic.
* **Bilingual Auto-Detection (EN / AR):** Automatically identifies English or Arabic input and routes to the appropriate knowledge namespace (`kb_en` or `kb_ar`) and localized booking responses.
* **Strict Privacy & Security:** Built-in safeguards strictly prevent leakage of underlying models, API keys, system prompts, or internal backend architecture.
* **Direct & Concise Persona:** Answers directly to the point without marketing fluff, unprompted essays, or messy formatting.
* **Clean Formatting Standards:** Enforces clean bullet points (`•`) and bold labels, with zero hyphens or asterisk clutter.
* **Official Fallback Routing:** Directs unverified questions to:
  * **Email:** `info@itcybx.co.uk`
  * **Phone:** `+44 793 389 5500`

---

## 📂 Project Structure

```
itcybx_live_bot/
│
├── data/
│   ├── approved/                  # Vetted URLs for knowledge base
│   │   ├── approved_urls_en.txt
│   │   └── approved_urls_ar.txt
│   ├── raw/                       # Raw sitemap-scraped text
│   │   ├── en/
│   │   └── ar/
│   ├── processed/                 # Cleaned, boilerplate-free text
│   │   ├── en/                    # 16 approved English pages
│   │   └── ar/                    # 15 approved Arabic pages
│   └── bookings.json              # Confirmed meeting bookings store
│
├── src/
│   ├── config/
│   │   └── settings.py            # Centralized config, business hours & validation
│   ├── utils/
│   │   └── logger.py              # Centralized logging with UTF-8 support
│   ├── loaders/
│   │   ├── sitemap_loader.py      # LangChain sitemap crawler & filter
│   │   └── content_cleaner.py     # Boilerplate, nav, and footer cleaner
│   ├── knowledge_base/
│   │   ├── chunker.py             # Recursive text splitter with metadata
│   │   ├── embedder.py            # Mistral 1024-dim vector embeddings
│   │   └── client.py              # Pinecone index manager & similarity retriever
│   ├── tools/
│   │   ├── faq_tool.py            # LangChain tool (search_knowledge_base)
│   │   └── booking_tool.py        # Tools (check_availability, book_meeting)
│   └── agent/
│       ├── prompts_en.py          # English system prompt & fallback rules
│       ├── prompts_ar.py          # Arabic system prompt & fallback rules
│       └── graph.py               # LangGraph state machine & session memory
│
├── scripts/
│   ├── build_knowledge_base.py    # Chunks, embeds (Mistral), and indexes Pinecone
│   ├── test_rag.py                # RAG benchmark suite & custom query tester
│   ├── test_booking.py            # Meeting booking test suite (EN & AR)
│   └── chat_cli.py                # Interactive live terminal chat UI
│
├── requirements.txt
├── .env.example
└── README.md
```

---

## 🚀 Quick Start Guide

### 1. Prerequisites
* Python 3.10 or higher
* Git

### 2. Installation
```powershell
# Clone the repository
git clone https://github.com/YOUR_USERNAME/itcybx_live_bot.git
cd itcybx_live_bot

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Create a `.env` file in the root directory:
```env
USER_AGENT=itcybx-live-bot/1.0
MISTRAL_API_KEY=your_mistral_api_key_here
PINECONE_API_KEY=your_pinecone_api_key_here
PINECONE_INDEX_NAME=itcybx-kb
```

Validate your configuration:
```powershell
python -m src.config.settings
```

---

## 🛠️ CLI Commands Reference

| Command | Purpose |
|---|---|
| `python -m src.config.settings` | Verifies and validates all API keys and environment paths. |
| `python -m src.loaders.sitemap_loader` | Crawls English & Arabic sitemaps and saves raw text. |
| `python -m src.loaders.content_cleaner` | Strips navigation, headers, and footer boilerplate. |
| `python -m scripts.build_knowledge_base` | Chunks, embeds (Mistral), and indexes all docs into Pinecone. |
| `python -m scripts.test_rag` | Runs automated RAG benchmark tests across EN, AR, and Out-of-Domain. |
| `python -m scripts.test_rag "your query"` | Runs a custom test query against Pinecone with similarity scores. |
| `python -m scripts.test_booking` | Tests availability checking and booking flows (EN & AR). |
| `python -m scripts.chat_cli` | **Launches the interactive live terminal chatbot.** |

---

## 💬 Testing the Interactive Chat

Run the interactive chat CLI:
```powershell
python -m scripts.chat_cli
```

### Chat Commands:
* Type your question in **English** or **Arabic** (auto-detected).
* `/lang ar` — Force Arabic responses.
* `/lang en` — Force English responses.
* `/clear` — Reset conversation memory and start a new session.
* `/exit` — Quit the chat.

---

## 🗺️ Implementation Roadmap

- [x] **Phase 1:** Sitemap Loading, Scraping & Content Sanitization
- [x] **Phase 2:** Knowledge Base (RAG), Mistral Embeddings & Pinecone Indexing
- [x] **Phase 3:** LangGraph Agent, First Tool & Bilingual Prompts
- [x] **Phase 4:** Meeting Booking & Availability Tools (Sunday–Thursday 12:00–17:00)
- [ ] **Phase 5:** Lead Capture & Slack Escalation Webhooks
- [ ] **Phase 6:** End-to-End Bilingual Runtime Optimization
- [ ] **Phase 7:** FastAPI Backend & Redis Session Memory
- [ ] **Phase 8:** Embedded React + Tailwind CSS Web Widget
- [ ] **Phase 9:** Production Deployment & WordPress Live Embed


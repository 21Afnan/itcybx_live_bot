# IT Cybx Live Bot

A production-grade, bilingual (English/Arabic) AI agent chatbot built for [itcybx.co.uk](https://itcybx.co.uk) — an e-commerce growth studio (Shopify/Salla/Zid builds + growth marketing for beauty/lifestyle brands in Saudi Arabia and the UK).

## 🚀 Features

- **Source-Grounded Answers (RAG)**: Answers visitor questions using only verified content from the live website without hallucinating.
- **Strict Fallback Rules**: Clear static "I don't know" fallback pointing to direct human contact info when knowledge is missing.
- **Bilingual (English / Arabic)**: Native Arabic and English support with separate vector collections (`kb_en` / `kb_ar`).
- **Autonomous Agent**: Powered by LangGraph for multi-step reasoning, lead qualification, and booking flows.
- **Meeting Scheduling**: Real-time availability checks and Growth Audit booking via the Calendly API.
- **Lead Capture & Escalation**: Automatic lead collection and real-time Slack team notifications.

## 🛠️ Tech Stack

- **Agent Framework**: [LangGraph](https://github.com/langchain-ai/langgraph) / LangChain
- **LLM**: Mistral AI
- **Vector Database**: Pinecone
- **Backend API**: Python + FastAPI
- **Session Memory**: Redis
- **Database**: PostgreSQL
- **Integrations**: Calendly API, Slack Webhooks
- **Frontend Widget**: React + Tailwind CSS

## 📋 Getting Started

### Prerequisites
- Python 3.10+
- Git

### Setup
1. Clone the repository:
   ```bash
   git clone https://github.com/YOUR_USERNAME/itcybx_live_bot.git
   cd itcybx_live_bot
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   # On Windows (PowerShell):
   .\venv\Scripts\Activate.ps1
   ```
3. Copy the environment file and set your keys:
   ```bash
   cp .env.example .env
   ```

## 📄 License
Private repository for IT Cybx.

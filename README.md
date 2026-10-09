<div align="center">

<p align="center">
  <img
    src="docs/header.png"
    alt="Sangam Universal AI Chat Platform"
    width="100%"
  />
</p>

**One interface. Every model. Your workflow.**

A privacy-first AI workspace for chatting with cloud and local LLMs from a single modern interface.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active%20Development-orange)]()
[![Version](https://img.shields.io/badge/Version-v1.1-3A342B)]()

</div>

---

## ✨ Meet Sangam

Sangam is an open-source, privacy-first AI chat platform that brings multiple Large Language Models into one unified workspace.

Connect cloud providers such as **OpenAI, Anthropic, Gemini, NVIDIA NIM, Groq, Mistral, DeepSeek, OpenRouter** and more — or run models locally through **Ollama**,**omniroute**.

Switch models, upload documents, use RAG, search the web, manage provider keys, and keep your conversations in one place.

> **Sangam v1.1 is under active development.** Features and APIs may evolve as the project grows.

---

## 🖥️ Interface

<p align="center">
  <img
    src="docs/interface.png"
    alt="Sangam Universal AI Chat Platform"
    width="100%"
  />
</p>

<p align="center">
  <sub>One box, every model — switch providers without leaving your workspace.</sub>
</p>

---

## 🚀 Key Features

### 🤖 Multi-Provider AI

Connect multiple cloud and local AI providers from one interface and switch between models without changing applications.

### ⚡ Streaming Chat

Responses are streamed token-by-token for a fast and responsive conversational experience.

### 🦙 Local AI with Ollama

Use locally installed Ollama models directly inside Sangam while keeping inference on your machine.

### 📚 Document Chat + RAG

Upload documents and ask questions about their contents.

Sangam chunks documents, generates embeddings, retrieves relevant sections, and sends only the most useful context to the model.

### 🌐 Web Search

Augment conversations with live web results using the built-in search integration.

### 🧩 Skills

Reusable AI workflows for tasks such as debugging, API design, coding review, and web-assisted research.

### 💬 Persistent Conversations

Conversation history is stored locally and organized in a date-based sidebar.

### 🎨 Customizable Interface

A **Paper / Ink** design system — warm paper whites (PAPER) or deep charcoal (INK), with a restrained monochrome palette. Adjust font size, chat width, code theme, and animations from Settings.

### 🔐 Privacy Focused

Local authentication, encrypted provider keys, secure password hashing, and local conversation storage.

### 🧠 Memory++

Typed long-term memory (episodic, semantic, procedural) with importance-ranked recall, automatic extraction from conversations, and consolidation — managed from Settings.

### 🎙️ Voice

Local-first text-to-speech and speech-to-text with pluggable engines (Kokoro, faster-whisper, OpenAI-compatible APIs). Mic dictation in the composer, per-message Speak, auto-speak setting.

### 🎨 Image Generation

Fooocus-inspired style presets with pluggable engines (OpenAI-compatible image APIs, experimental local Fooocus). Generate images from the composer and attach them to chats.

### 📦 Skill Packs

Curated skill bundles — spec-driven development workflows, Mermaid architecture diagramming, science research essentials, and agent-loop discipline. Enable/disable packs from the Skills browser.

### 👥 Multi-Agent Teams

Research, Code, and Writing teams: specialist agents work in parallel while a coordinator synthesizes the final answer. Watch each specialist's output unfold.

### 🎓 Learning Mode

Interactive classroom: a teacher agent delivers structured, research-first lessons and a tutor gives Socratic feedback on your answers.

### ✨ Response Quality

Optional AI-slop cleanup and ADHD-friendly formatting (answer-first, scannable) applied safely at persistence time.

### 📊 Usage Analytics

Opt-in, local-first analytics dashboard — your usage stays on your server, never shared.

### ⌨️ Command Palette

Press Ctrl+P for a quick launcher: new chat, skills, teams, export, theme, and more. Export any chat as Markdown.

### � studio AI Studio Shell

Intent-grouped navigation (Home, Chat, Agents, Knowledge, Create, Code, Learn, Library, Insights, Settings). Browser-style tabs for side-by-side work — main chat stays pinned. Right Inspector panel (Ctrl+Shift+I), Activity Tray for background jobs, typed settings with search.

### 🧠 Knowledge Graph

Unified graph of memories, documents, code symbols, and chats. SVG visualization with zoom, click-to-inspect, provenance labels (EXTRACTED/INFERRED/AMBIGUOUS), memory wings by type, and "used in this answer" tracking.

### 🤖 Agent Hub

Build custom agents with system prompts, tools, and approval policies. Built-in Researcher, Coder, Writer, Analyst. Run with streaming, approve/deny tool calls, set cost budgets.

### 🎨 Create Hub

Typed artifacts: markdown docs, diagrams (custom SVG renderer), code files, HTML previews. Version history with restore, six starter templates, image/voice studio shortcuts.

### ⏰ Automations

Schedule agent tasks or chat messages: hourly, daily, weekly, or cron. Enable/disable, run now, humanized next-run times.

### 🔀 Routes & Combos

Keyword-based model routing (e.g. "python" → code model). Chain models into combos (fast draft → smart refine). Per-provider quota display.

### ⚖️ Model Compare & Arena

Run the same prompt against 2-4 models in parallel. Vote for the winner; leaderboard tracks win rates by model.

### 💻 Code Agent

OpenHands-style agentic coding: write_file, edit_file, run_bash tools, SSE streaming, TDD mode, learned instincts, code map (AST graph of your codebase).

### 🎨 Design Studio

Generate UI prototypes from prompts. Sandboxed iframe preview, refine iteratively, download as HTML.

---

## 🤖 Supported AI Providers

| Provider | Type | API Key |
|---|:---:|:---:|
| Anthropic | ☁️ Cloud | Required |
| OpenAI | ☁️ Cloud | Required |
| NVIDIA NIM | ☁️ Cloud | Required |
| Together AI | ☁️ Cloud | Required |
| Groq | ☁️ Cloud | Required |
| OpenRouter | ☁️ Cloud | Required |
| DeepSeek | ☁️ Cloud | Required |
| Mistral AI | ☁️ Cloud | Required |
| Google Gemini | ☁️ Cloud | Required |
| Ollama | 🖥️ Local | Not required |
| OmniRoute | 🖥️ Local | Not required |

**NOTE - USE OMNIROUTE TO ACCESS ALL PROVIDERS**

The provider registry is extensible, making it possible to add additional providers as Sangam evolves.

---

## ⚡ Quick Start

### Requirements

Before starting, make sure you have:

- Python **3.11+**
- Git
- Ollama *(optional — only required for local models)*

### 1. Clone Sangam

```bash
git clone https://github.com/keshria-hacker/sangam.git
cd sangam
```

### 2. Configure Environment

On first run, `start.py` automatically creates `.env` from `.env.example` and generates a valid `MASTER_KEY` (used to encrypt provider API keys at rest). You can also create it manually:

```bash
cp .env.example .env
```

Add the API keys for the providers you want to use.

```env
OPENAI_API_KEY=your_key
ANTHROPIC_API_KEY=your_key
NVIDIA_NIM_API_KEY=your_key
GEMINI_API_KEY=your_key
OPENROUTER_API_KEY=your_key
GROQ_API_KEY=your_key
```

You don't need to configure every provider.

API keys can also be managed later from:

**Settings → Provider API Keys**

### 3. Start Sangam

#### Windows

Simply run:

```bash
start.bat
```

Or:

```bash
python start.py
```

#### Linux / macOS

```bash
./start.sh
```

### 4. Open Sangam

Once the servers are running:

| Service | Address |
|---|---|
| Sangam | `http://127.0.0.1:5500` |
| Backend API | `http://127.0.0.1:8001` |
| Swagger API Docs | `http://127.0.0.1:8001/docs` |

---

## 🐳 Docker

Sangam can also run using Docker.

### Build

```bash
docker build -f Dockerfile.all -t sangam-all .
```

### Configure

```bash
cp .env.example .env
```

Add your required API keys to `.env`.

### Run

```bash
docker run -d \
  -p 8001:8001 \
  -p 5500:5500 \
  --env-file .env \
  sangam-all
```

### Docker Compose

```bash
docker compose -f docker-compose.all.yml up -d
```

---

## 🦙 Using Ollama

Sangam automatically detects available Ollama models.

Install or pull a model:

```bash
ollama pull llama3.2
```

Start Ollama:

```bash
ollama serve
```

Downloaded models will automatically appear inside the Sangam model selector.

To use another Ollama server:

```env
OLLAMA_BASE_URL=http://your-ollama-host:11434
```

> If Ollama is installed but not running, Sangam will attempt to start `ollama serve` automatically in the background the first time it needs a local model.

---

## 📂 Document Support

Sangam can extract and work with multiple document and source-code formats.

| Format | Support |
|---|:---:|
| PDF | ✅ |
| DOCX | ✅ |
| XLSX | ✅ |
| PPTX | ✅ |
| CSV | ✅ |
| TXT / Markdown | ✅ |
| JSON | ✅ |
| HTML / XML | ✅ |
| Source Code | ✅ |

### RAG Pipeline

Large documents are automatically:

**Extracted → Chunked → Embedded → Retrieved → Added to Context**

Only the most relevant document sections are sent to the selected model, helping reduce unnecessary context usage.

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python + FastAPI |
| Frontend | Vanilla JavaScript SPA |
| Database | SQLite + SQLAlchemy |
| LLM Integration | LiteLLM |
| RAG / Vector Search | ChromaDB |
| Authentication | Local Auth |
| API | REST + SSE Streaming |
| Deployment | Docker / Docker Compose |

---

## 🔐 Security & Privacy

Sangam is currently designed as a **local, single-user application**.

Security features include:

- 🔒 Provider API keys encrypted at rest
- 🔑 scrypt password hashing
- 🍪 HTTP-only authentication cookies
- 🛡️ CSRF protection
- 🚫 Debug mode disabled by default
- 💾 Local conversation storage

> **Important:** Sangam is not currently intended to be exposed directly to the public internet without additional production security configuration.

See [`SECURITY.md`](SECURITY.md) for security and vulnerability reporting information.

---

## 🧪 Testing

Run the test suite from the project root:

```bash
# pytest (the runner — see pyproject.toml for options)
venv\Scripts\python.exe -m pytest tests -v
```

The test suite lives in a single unified tree at `tests/` (unit, `integration/`, `e2e/`, `manual/`), consolidated by the module-split refactor.

Tests cover core functionality including authentication, document processing, model discovery, streaming, response intelligence, Skills, web search, voice, image generation, skill packs, multi-agent teams, learning mode, response quality, and analytics.

---

## ⭐ Star Sangam

If Sangam is useful to you, [star it on GitHub](https://github.com/keshria-hacker/sangam) — it helps others discover the project.

---

## 🤝 Contributing

Contributions, bug reports, feature requests, and improvements are welcome.

### Development Setup

```bash
git clone https://github.com/keshria-hacker/sangam.git
cd sangam
cp .env.example .env
python start.py
```

When contributing, please keep changes focused and follow the existing project structure and coding conventions.

---

## 📄 License

Sangam is released under the **MIT License**.

See [`LICENSE`](LICENSE) for details.

---

<div align="center">

### Sangam

**One interface. Every model. Your workflow.**

Built with ❤️ for the open-source AI community.

⭐ **If you find Sangam useful, consider giving the project a star.**

</div>

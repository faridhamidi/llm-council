# LLM Council

![llmcouncil](header.jpg)

The idea of this repo is that instead of asking a question to your favorite LLM provider (e.g. OpenAI GPT 5.1, Google Gemini 3.0 Pro, Anthropic Claude Sonnet 4.5, xAI Grok 4, eg.c), you can group them into your "LLM Council". This repo is a simple, local web app that essentially looks like ChatGPT except it uses Amazon Bedrock Runtime to send your query to multiple LLMs, it then asks them to review and rank each other's work, and finally a Chairman LLM produces the final response.

## Credits

This project is a fork/evolution of **[Andrej Karpathy's LLM Council](https://github.com/karpathy/llm-council)** idea (originally "99% vibe coded" as a fun hack). The original repository served as the inspiration and foundation.

## Codebase Evolution

While the core concept remains, the codebase has evolved significantly to support enterprise-grade features and flexibility. Here is a timeline of the major architectural shifts:

### Phase 1: Bedrock & Session Management
* **Commits**: `f6cbbfb` (Token Config), `9374792` (Region Support), `95da13d` (Streaming)
* **Change**: Replaced the original direct API calls with **AWS Bedrock Runtime**. Added region awareness (to support cross-region inference profiles) and improved SSE streaming stability.

### Phase 2: Configuration UI
* **Commits**: `3c850a5` (Settings UI), `19e0a18` (System Prompts)
* **Change**: Moved hardcoded configurations (members, specialized system prompts, aliases) into a runtime UI. This allowed users to tweak their council without restarting the backend.

### Phase 3: Robust Persistence (SQLite)
* **Commit**: `410d78e`
* **Change**: Migrated from flat JSON files to **SQLite** (`data/council.db`).
* **Why**: The original file-based system struggled with concurrent writes and complex queries. The SQLite migration (with auto-import of legacy JSON) enabled reliable session storage, search, and settings persistence.

### Phase 4: Security
* **Commit**: `665a5ed`
* **Change**: Introduced **PIN Authentication** (PBKDF2 hashed) to protect the interface when running in shared environments.

### Phase 5: Dynamic Council Flow
* **Commit**: `76a173e`
* **Change**: Replaced the fixed "3-Stage" waterfall model with a **Dynamic Stage Builder**.
* **Impact**: The backend can now execute arbitrary pipelines (e.g., N parallel stages, sequential debates, critique loops). This required a major refactor of `council.py` to handle generic stage definitions rather than hardcoded functions.

### Phase 6: Speaker Mode
* **Commit**: `29d9429`
* **Change**: Added multi-turn capabilities. Users can now "chat" with the council findings (Speaker Mode) rather than just receiving a static report.

## Core Flow (Default)

The default preset still follows the classic 3-stage council flow, but you can now customize it:

1. **Stage 1: First opinions**. The user query is given to all LLMs individually.
2. **Stage 2: Review**. Each individual LLM reviews anonymized responses from peers and ranks them.
3. **Stage 3: Final response**. The designated Chairman synthesizes the final answer based on the peer reviews.

## Features

- **Dynamic Stage Builder**: Configure your own deliberation pipeline (infinite stages, parallel/sequential).
- **Multi-turn Conversation**: Chat with the results using "Speaker" mode.
- **Streaming updates**: Server-sent events (SSE) for real-time progress.
- **Secure Storage**: Local SQLite database for conversations, settings, and presets.
- **Access Control**: Optional PIN protection for the web interface.
- **Council Settings UI**: Manage members, aliases, customized system prompts, and stage configurations.
- **Bedrock Integration**: Native support for AWS Bedrock Converse API (cross-region inference profiles supported).
- **Session Management**: Soft-delete, trash/restore, and search history.

## Setup

### 1. Install Dependencies

The project uses [uv](https://docs.astral.sh/uv/) for project management.

**Backend:**
```bash
uv sync
```

**Frontend:**
```bash
cd frontend
npm install
cd ..
```

### 2. Configure API Key

Create a `.env` file in the project root:

```bash
BEDROCK_API_KEY=bedrock-api-key-...
AWS_REGION=ap-southeast-1
```

You can also use `AWS_BEARER_TOKEN_BEDROCK` instead of `BEDROCK_API_KEY` if you prefer the AWS env var name.
Note: Ensure your `AWS_REGION` supports the Bedrock Inference Profiles you intend to use.

### 3. Run the Application

**Option 1: Use the start script (Recommended)**
```bash
./start.sh
```

**Option 2: Run manually**

Terminal 1 (Backend):
```bash
uv run python -m backend.main
```

Terminal 2 (Frontend):
```bash
cd frontend
npm run dev
```

Then open http://localhost:5173.

## Tech Stack

- **Backend:** FastAPI (Python 3.10+), async httpx, Bedrock Runtime API, SQLite
- **Frontend:** React + Vite, react-markdown, TailwindCSS
- **Storage:** SQLite (`data/council.db`)
- **Package Management:** uv (Python), npm (JS)

## API Highlights

- `POST /api/conversations/{id}/message/stream`: SSE streaming for dynamic stages.
- `POST /api/settings/council`: Configure members and the stage pipeline.
- `GET /api/settings/bedrock-models`: Fetch available Bedrock models.
- `POST /api/auth/verify`: PIN verification endpoint.

## Vibe Code Alert (Original)

> This project was 99% vibe coded as a fun Saturday hack because I wanted to explore and evaluate a number of LLMs side by side in the process of [reading books together with LLMs](https://x.com/karpathy/status/1990577951671509438). It's nice and useful to see multiple responses side by side, and also the cross-opinions of all LLMs on each other's outputs. I'm not going to support it in any way, it's provided here as is for other people's inspiration and I don't intend to improve it. Code is ephemeral now and libraries are over, ask your LLM to change it in whatever way you like. - *Andrej Karpathy*

# LLM Council

![llmcouncil](header.jpg)

The idea of this repo is that instead of asking a question to your favorite LLM provider (e.g. OpenAI GPT 5.1, Google Gemini 3.0 Pro, Anthropic Claude Sonnet 4.5, xAI Grok 4, eg.c), you can group them into your "LLM Council". This repo is a simple, local web app that essentially looks like ChatGPT except it uses Amazon Bedrock Runtime to send your query to multiple LLMs, it then asks them to review and rank each other's work, and finally a Chairman LLM produces the final response.

In a bit more detail, here is what happens when you submit a query:

1. **Stage 1: First opinions**. The user query is given to all LLMs individually, and the responses are collected. The individual responses are shown in a "tab view", so that the user can inspect them all one by one.
2. **Stage 2: Review**. Each individual LLM is given the responses of the other LLMs. Under the hood, the LLM identities are anonymized so that the LLM can't play favorites when judging their outputs. The LLM is asked to rank them in accuracy and insight.
3. **Stage 3: Final response**. The designated Chairman of the LLM Council takes all of the model's responses and compiles them into a single final answer that is presented to the user.

## Features (Current)

- **3-stage council flow**: parallel responses → anonymous peer ranking → chairman synthesis
- **Streaming updates**: server-sent events (SSE) for stage-by-stage progress
- **Cancelable requests**: stop in-flight streams from the UI
- **Council Settings UI**: manage members, aliases, chairman, title model, and per-member system prompts
- **Presets**: save/apply/delete council configurations
- **Bedrock region switcher**: change region and list region-compatible Converse models
- **Conversation storage**: JSON on disk with soft-delete + restore (trash)
- **Readable UX**: tabbed Stage 1/2/3 views, parsed rankings, and aggregate ranking table

## Vibe Code Alert

This project was 99% vibe coded as a fun Saturday hack because I wanted to explore and evaluate a number of LLMs side by side in the process of [reading books together with LLMs](https://x.com/karpathy/status/1990577951671509438). It's nice and useful to see multiple responses side by side, and also the cross-opinions of all LLMs on each other's outputs. I'm not going to support it in any way, it's provided here as is for other people's inspiration and I don't intend to improve it. Code is ephemeral now and libraries are over, ask your LLM to change it in whatever way you like.

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
Note: Bedrock inference profiles are source-region scoped. If a model's inference profile doesn't list your `AWS_REGION` as a supported source region, you'll need to change `AWS_REGION` to one of the supported source regions for that profile.

### 3. Configure Models (Optional)

You can customize defaults in `backend/config.py`, but most users should do it from the UI (see below):

```python
COUNCIL_MODELS = [
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-opus-4-5-20251101-v1:0",
    "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
]

COUNCIL_ALIASES = [
    "Councilor A",
    "Councilor B",
    "Councilor C",
    "Councilor D",
]

CHAIRMAN_MODEL = "us.anthropic.claude-opus-4-5-20251101-v1:0"
CHAIRMAN_ALIAS = "Chairman"
TITLE_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
```

### Council Settings (UI)

You can now manage council members, aliases, chairman, and title model from the UI:

1. Click **Council Settings** in the sidebar.
2. Add/remove members (max 7) and drag to reorder.
3. Pick models from the Converse‑compatible list for the current region.
4. Set chairman + title model.
5. Optional: add per‑member system prompts.
6. Optional: disable system prompts in Stage 2 & 3.
7. Save/apply/delete presets.
8. Click **Save Settings** to apply instantly (no restart).

Notes:
- Region and API key updates are in‑memory and reset on backend restart.
- If a model is not available in the selected region, it will be rejected.
- Settings are persisted in `data/council_settings.json`. Presets are stored in `data/council_presets.json`.

## Running the Application

**Option 1: Use the start script**
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

Then open http://localhost:5173 in your browser.

## Tech Stack

- **Backend:** FastAPI (Python 3.10+), async httpx, Bedrock Runtime API
- **Frontend:** React + Vite, react-markdown for rendering
- **Storage:** JSON files in `data/conversations/`
- **Package Management:** uv for Python, npm for JavaScript

## API Highlights

- `POST /api/conversations/{id}/message`: Non‑streaming 3‑stage response
- `POST /api/conversations/{id}/message/stream`: SSE streaming (stage1/2/3 events)
- `POST /api/conversations/{id}/message/cancel`: Cancel active stream
- `POST /api/settings/council`: Update council settings
- `GET /api/settings/bedrock-models`: Models available for current region

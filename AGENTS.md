# AGENTS.md - Technical Notes for LLM Council

This file contains technical details, architectural decisions, and important implementation notes for future development sessions.

## Project Overview

LLM Council is a 3-stage deliberation system where multiple LLMs collaboratively answer user questions. The key innovation is anonymized peer review in Stage 2, preventing models from playing favorites. The app is a local web UI backed by a FastAPI server that calls Amazon Bedrock Runtime (Converse API).

## Architecture

### Backend Structure (`backend/`)

**`config.py`**
- Loads Bedrock API key from `BEDROCK_API_KEY` (or `AWS_BEARER_TOKEN_BEDROCK`).
- Tracks current Bedrock region and exposes a curated list of Converse-capable model families.
- Defines defaults: `COUNCIL_MODELS`, `COUNCIL_ALIASES`, `CHAIRMAN_MODEL`, `CHAIRMAN_ALIAS`, `TITLE_MODEL`.
- Defines `BEDROCK_REGION_OPTIONS` for the UI and `DATA_DIR` for storage.
- Backend runs on **port 8001** (not 8000).

**`openrouter.py`**
- `query_model()`: Single async model query (Bedrock Runtime Converse).
- Supports per-model system prompt (sent as `system`).
- If a model rejects the system prompt (400), retries without it and marks `system_prompt_dropped`.
- Returns dict with `content` and optional `reasoning_details`, or `{error: ...}` on failure (may be `None` if no API key).

**`council.py`** (Core logic)
- `stage1_collect_responses()`: Parallel queries to all council members, keeps per-member status and error.
- `stage2_collect_rankings()`: Anonymizes responses as `Response A/B/C`, prompts models to rank, returns `(rankings, label_to_model)`.
- `parse_ranking_from_text()`: Extracts `FINAL RANKING:` list with fallback regex.
- `calculate_aggregate_rankings()`: Average rank position across peer evaluations.
- `stage3_synthesize_final()`: Chairman synthesizes from Stage 1 + Stage 2 context.
- `generate_conversation_title()`: Title model generates a short conversation title.

**`council_settings.py`**
- Runtime-configurable council settings persisted to `data/council_settings.json`.
- Members are configurable (max 7), with per-member `system_prompt`.
- Toggles to disable system prompts in Stage 2 & 3 (`use_system_prompt_stage2`, `use_system_prompt_stage3`).
- Region normalization maps model IDs to the selected region scope when possible.

**`council_presets.py`**
- Presets are persisted in `data/council_presets.json`.
- Supports save/update, apply, and delete.

**`storage.py`**
- JSON-based conversation storage in `data/conversations/`.
- Soft-delete via `data/conversations/.trash/` with restore.
- Assistant messages contain `{role, stage1, stage2, stage3}`.
- Metadata (label_to_model, aggregate_rankings) is **not** persisted.

**`main.py`**
- FastAPI app with CORS enabled for localhost:5173 and localhost:3000.
- `/api/conversations/{id}/message`: Non-streaming, returns stages + metadata.
- `/api/conversations/{id}/message/stream`: SSE streaming for stage1/2/3.
- `/api/conversations/{id}/message/cancel`: Cancel active stream.
- `/api/settings/*`: Bedrock region, models, council settings, and presets.

### Frontend Structure (`frontend/src/`)

**`App.jsx`**
- Orchestrates conversation list + active conversation.
- SSE streaming updates for stages; supports stop/cancel.
- Handles soft-delete with undo UI.

**`components/ChatInterface.jsx`**
- Multiline textarea; Enter to send, Shift+Enter for new line.
- Builds label map if metadata is missing (fallback to Stage 1 order).

**`components/Stage1.jsx`**
- Tab view of individual responses.
- Displays error state and system prompt drop warning.

**`components/Stage2.jsx`**
- Shows raw peer evaluations (de‑anonymized client‑side for readability).
- Displays parsed ranking list per model.
- Shows aggregate rankings (avg rank + vote count).

**`components/Stage3.jsx`**
- Final synthesized answer with copy-to-clipboard support.
- De‑anonymizes labels client‑side for readability.

**Styling (`*.css`)**
- Light theme with global `.markdown-content` styling in `index.css`.
- Stage 3 has a green‑tinted background to highlight the final answer.

## Key Design Decisions

### Stage 2 Prompt Format
A strict format ensures reliable parsing:
```
1. Evaluate each response individually
2. Provide "FINAL RANKING:" header
3. Numbered list: "1. Response C", "2. Response A", etc.
4. No extra text after ranking section
```

### De‑anonymization Strategy
- Models see: `Response A`, `Response B`, etc.
- Backend returns `label_to_model` mapping for UI display.
- Frontend renders model names in **bold** for readability while preserving the anonymized ranking process.

### Error Handling Philosophy
- Continue with successful responses if some models fail.
- Never fail the entire request due to one model failure.
- Stage 1 tracks failures per member and surfaces them in the UI.

### UI/UX Transparency
- All raw outputs are inspectable via tabs.
- Parsed rankings are shown below raw text for validation.
- Aggregate rankings summarize peer consensus.

## Important Implementation Details

### Relative Imports
All backend modules use relative imports (e.g., `from .config import ...`) so `python -m backend.main` works from repo root.

### Design System Reference
See `DESIGN_SYSTEM.md` for the current design system tokens, typography, and UI guidelines. Extend or evolve the system there so future agents have a single source of truth.

### Port Configuration
- Backend: 8001
- Frontend: 5173 (Vite default)
- Update both `backend/main.py` and `frontend/src/api.js` if changing.

### Markdown Rendering
All ReactMarkdown components must be wrapped in `<div className="markdown-content">` for proper spacing (global styles in `index.css`).

### Model Configuration
Defaults live in `backend/config.py`, but the UI can override council composition, chairman, and title model at runtime.

## Common Gotchas

1. **Module Import Errors**: Always run backend as `python -m backend.main` from project root.
2. **CORS Issues**: Frontend must match allowed origins in `main.py`.
3. **Ranking Parse Failures**: Fallback regex extracts any `Response X` patterns in order.
4. **Missing Metadata**: `label_to_model` is ephemeral (not persisted), only in API responses.
5. **Region Mismatch**: Selected region must support each model ID.

## Future Enhancement Ideas

- Configurable council/chairman via URL params or shareable presets
- Streaming persistence (store stage updates in conversation history)
- Export conversations to markdown/PDF
- Model performance analytics over time
- Custom ranking criteria (beyond accuracy/insight)
- Support for reasoning‑only models with special handling

## Data Flow Summary

```
User Query
    ↓
Stage 1: Parallel queries → [individual responses]
    ↓
Stage 2: Anonymize → Parallel ranking queries → [evaluations + parsed rankings]
    ↓
Aggregate Rankings Calculation → [sorted by avg position]
    ↓
Stage 3: Chairman synthesis with full context
    ↓
Return: {stage1, stage2, stage3, metadata}
    ↓
Frontend: Display with tabs + validation UI
```

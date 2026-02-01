# AGENTS.md - Technical Notes for LLM Council

This file contains technical details, architectural decisions, and important implementation notes for future development sessions.

## Project Overview

LLM Council is a deliberation system where multiple LLMs collaboratively answer user questions. This project has evolved from a fixed 3-stage prototype into a flexible, configurable platform supporting custom pipelined stages, multi-turn conversation ("Speaker Mode"), and enterprise-grade backend integration via Amazon Bedrock.

## Architecture Structure

### Backend Modules (`backend/`)

**`config.py`**
- **Purpose**: Central configuration and environment variable loading.
- **Key Keys**: `BEDROCK_API_KEY`, `AWS_REGION` (defaults to `us-east-1` if unset).
- **Inference Profiles**: Tracks model IDs like `us.anthropic.claude-...` and ensures they match the active region.

**`db.py`** (SQLite Persistence)
- **Engine**: SQLite (`data/council.db`).
- **Schema**:
  - `conversations (id, created_at, title, deleted_at, settings_snapshot)`: Header info. `settings_snapshot` preserves the council state at the time of creation.
  - `messages (id, conversation_id, role, content, stage1_json, stage2_json, stage3_json, stages_json)`:
    - `stages_json`: Stores the full trace of dynamic pipelines (list of stage results).
    - `message_type`: `'council'` (deliberation) or `'speaker'` (chat follow-up).
  - `council_settings (id, settings_json)`: Singleton row (id=1) for current active config.
  - `meta`: Key-value store for system props like `auth_pin`.
- **Migrations**: `_migrate_from_json` automatically imports legacy `data/*.json` files on startup.

**`council.py`** (The Brain)
- **`PipelineStage`**: Dataclass defining a stage with `runner` function.
- **`run_full_council`**: The main orchestration loop.
  - Iterates through `stages_config`.
  - Dynamically resolves members via `_resolve_stage_members`.
  - Chains context: Passing previous stage outputs to the next via prompt templates.
- **Templating**: `_apply_prompt_template` injects variables like `{responses}`, `{stage1}`, `{question}` into stage prompts.

**`main.py`** (API Layer)
- **FastAPI**: Runs on port **8001**.
- **SSE Streaming**: `/message/stream` endpoint pushes events (`stage1_start`, `stage1_complete`, etc.) to the frontend.
- **Session Security**: Uses `session_store` for cookie-based session management and PIN validation (`_require_pin` middleware).

### Frontend Structure (`frontend/src/`)

**`App.jsx`**
- Manages global state: `currentConversationId`, `pinVerified`.
- Handles soft navigation and the "PIN Gate" logic.

**`components/ChatInterface.jsx`**
- **Render Logic**: Maps message types (`council` vs `speaker`) to different views.
- **Streaming**: Consumes the SSE stream, updating the UI stage-by-stage in real-time.

**`components/StageBuilder.jsx`**
- **Drag-and-Drop**: Uses `dnd-kit` (or similar logic) to reorder stages.
- **Config**: updates the global `council_settings` JSON structure via API.

## Key Design Flows

### 1. Dynamic Council Execution (`run_full_council`)
Instead of a hardcoded function, the council follows a JSON-defined pipeline.
```python
# Pseudo-flow in council.py
context = CouncilRunContext(user_query=...)
for stage_config in settings.stages:
    # 1. Resolve Runner (Parallel vs Sequential)
    runner = _get_runner(stage_config.execution_mode)
    
    # 2. Build Prompt
    prompt = _format_stage_prompt(stage_config.prompt, context)
    
    # 3. Execute
    results = await runner.execute(prompt, stage_config.members)
    
    # 4. Update Context
    context.history.append(results)
```
*Note*: The legacy `stage1`, `stage2`, `stage3` fields in the DB are kept for backward compatibility, but modern execution relies on `stages_json`.

### 2. Speaker Mode (Multi-turn)
When a user replies to a Council response, they enter "Speaker Mode".
- **Concept**: You are chatting with a single "Speaker" model that has read the entire council deliberation.
- **Context Construction**: `_build_speaker_context` (in `council.py`) compiles the User Query + All Stage Results + Final Synthesis into a system prompt for the Speaker.
- **Flow**: User Msg -> `storage.add_user_message` -> `query_council_speaker` -> `storage.add_speaker_message`.

### 3. Authentication Flow
- **Encryption**: PIN is salted and hashed using `PBKDF2-HMAC-SHA256`.
- **Middleware**: `_require_pin` checks for the `x-llm-council-pin` header or a valid session cookie on sensitive API routes.

## Data & Storage Details

- **Database Location**: `data/council.db` (created automatically).
- **Settings**: Stored in DB, but a `settings_snapshot` is saved *per conversation* to ensure historical accuracy (so changing the council today doesn't break old chat logs).
- **Trash**: Soft-delete sets `deleted_at` timestamp. Restore clears it.

## Common Gotchas & Troubleshooting

1. **"Model Not Found" Errors**:
   - **Cause**: The `AWS_REGION` in `.env` does not support the requested model ID (Inference Profile).
   - **Fix**: Check `backend/config.py` or the Bedrock console. Update `.env` to a region that supports the model (e.g., `us-east-1` has most).

2. **Template Errors in Custom Stages**:
   - **Symptom**: Model responds "I don't see any previous responses."
   - **Cause**: Custom stage prompt is missing placeholders like `{responses}`.
   - **Fix**: Ensure the prompt includes `{responses}` so the Python backend injects the text from previous stages.

3. **Database Locks**:
   - **Symptom**: `database is locked` error.
   - **Cause**: High concurrency writes to SQLite.
   - **Fix**: The system uses a specialized connection context manager (`with_connection`), but extreme load might still trigger this. Avoid running multiple backend instances against the same file.

4. **Stream Interruption**:
   - **Symptom**: Frontend shows "Connection Error" mid-stream.
   - **Detail**: SSE connections can be fragile. The backend tracks `active_tasks` to handle cancellation cleanups, but network drops may leave "orphan" Bedrock calls running (though they won't save to the specific conversation stream).

## Future Development Ideas

- **Tool Use**: Integrate Bedrock's `toolConfig` to allow Council members to search the web or run Python.
- **Vector Memory**: Store finalized Council outputs in a vector store (e.g., Chroma/FAISS) to allow referencing *past* councils in *new* conversations.
- **Orchestrator Mode**: Allow a "Manager" LLM to dynamically decide the next stage (looping back for critique) rather than a fixed linear pipeline.

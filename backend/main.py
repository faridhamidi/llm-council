"""FastAPI backend for LLM Council."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any
import uuid
import json
import asyncio

from . import storage
from .config import set_bedrock_api_key, get_bedrock_region, set_bedrock_region, BEDROCK_REGION_OPTIONS
from .council import run_full_council, generate_conversation_title, stage1_collect_responses, stage2_collect_rankings, stage3_synthesize_final, calculate_aggregate_rankings

app = FastAPI(title="LLM Council API")

# Track active streaming tasks so they can be cancelled from the UI.
ACTIVE_STREAMS: Dict[str, Dict[str, Any]] = {}

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    pass


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str


class UpdateBedrockTokenRequest(BaseModel):
    """Request to update the Bedrock API token at runtime."""
    token: str


class UpdateBedrockRegionRequest(BaseModel):
    """Request to update the Bedrock region at runtime."""
    region: str


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    created_at: str
    title: str
    message_count: int


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    messages: List[Dict[str, Any]]


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Council API"}


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations():
    """List all conversations (metadata only)."""
    return storage.list_conversations()


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str):
    """Get a specific conversation with all its messages."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """Soft-delete a conversation (move to trash)."""
    deleted = storage.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "ok", "deleted": True}


@app.post("/api/conversations/{conversation_id}/restore")
async def restore_conversation(conversation_id: str):
    """Restore a trashed conversation."""
    restored = storage.restore_conversation(conversation_id)
    if not restored:
        raise HTTPException(status_code=404, detail="Conversation not found in trash")
    conversation = storage.get_conversation(conversation_id)
    return {"status": "ok", "restored": True, "conversation": conversation}


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and run the 3-stage council process.
    Returns the complete response with all stages.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    # Add user message
    storage.add_user_message(conversation_id, request.content)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title)

    # Run the 3-stage council process
    stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
        request.content
    )

    # Add assistant message with all stages
    storage.add_assistant_message(
        conversation_id,
        stage1_results,
        stage2_results,
        stage3_result
    )

    # Return the complete response with metadata
    return {
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata
    }


@app.post("/api/settings/bedrock-token")
async def update_bedrock_token(request: UpdateBedrockTokenRequest):
    """
    Update the Bedrock API key at runtime (in-memory only).
    """
    token = request.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token is required")

    set_bedrock_api_key(token)
    return {"status": "ok"}


@app.get("/api/settings/bedrock-region")
async def get_bedrock_region_setting():
    """Get the current Bedrock region."""
    return {"region": get_bedrock_region()}


@app.get("/api/settings/bedrock-region/options")
async def get_bedrock_region_options():
    """Get supported Bedrock region options for the UI."""
    return {"regions": BEDROCK_REGION_OPTIONS}


@app.post("/api/settings/bedrock-region")
async def update_bedrock_region(request: UpdateBedrockRegionRequest):
    """Update the Bedrock region at runtime (in-memory only)."""
    region = request.region.strip()
    if not region:
        raise HTTPException(status_code=400, detail="Region is required")

    allowed = {opt["code"] for opt in BEDROCK_REGION_OPTIONS}
    if region not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported region")

    set_bedrock_region(region)
    return {"status": "ok", "region": region}


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(conversation_id: str, request: SendMessageRequest, http_request: Request):
    """
    Send a message and stream the 3-stage council process.
    Returns Server-Sent Events as each stage completes.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    async def stream_worker(event_queue: "asyncio.Queue[Dict[str, Any]]", cancel_event: asyncio.Event):
        try:
            if cancel_event.is_set():
                await event_queue.put({"type": "cancelled"})
                return

            # Add user message
            storage.add_user_message(conversation_id, request.content)

            # Start title generation in parallel (don't await yet)
            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(request.content))

            # Stage 1: Collect responses
            await event_queue.put({"type": "stage1_start"})
            stage1_results = await stage1_collect_responses(request.content)
            await event_queue.put({"type": "stage1_complete", "data": stage1_results})

            if cancel_event.is_set():
                await event_queue.put({"type": "cancelled"})
                return

            # Stage 2: Collect rankings
            await event_queue.put({"type": "stage2_start"})
            stage2_results, label_to_model = await stage2_collect_rankings(request.content, stage1_results)
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            await event_queue.put({
                "type": "stage2_complete",
                "data": stage2_results,
                "metadata": {
                    "label_to_model": label_to_model,
                    "aggregate_rankings": aggregate_rankings,
                },
            })

            if cancel_event.is_set():
                await event_queue.put({"type": "cancelled"})
                return

            # Stage 3: Synthesize final answer
            await event_queue.put({"type": "stage3_start"})
            stage3_result = await stage3_synthesize_final(request.content, stage1_results, stage2_results)
            await event_queue.put({"type": "stage3_complete", "data": stage3_result})

            if cancel_event.is_set():
                await event_queue.put({"type": "cancelled"})
                return

            # Wait for title generation if it was started
            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title)
                await event_queue.put({"type": "title_complete", "data": {"title": title}})

            # Save complete assistant message
            storage.add_assistant_message(
                conversation_id,
                stage1_results,
                stage2_results,
                stage3_result
            )

            # Send completion event
            await event_queue.put({"type": "complete"})
        except asyncio.CancelledError:
            await asyncio.shield(event_queue.put({"type": "cancelled"}))
            raise
        except Exception as e:
            await event_queue.put({"type": "error", "message": str(e)})
        finally:
            current = ACTIVE_STREAMS.get(conversation_id)
            if current and current.get("task") is asyncio.current_task():
                ACTIVE_STREAMS.pop(conversation_id, None)

    async def cancel_active_stream():
        current = ACTIVE_STREAMS.pop(conversation_id, None)
        if current:
            current["cancel_event"].set()
            current["task"].cancel()

    async def cleanup_active_stream():
        current = ACTIVE_STREAMS.pop(conversation_id, None)
        if current and not current["task"].done() and current["cancel_event"].is_set():
            current["task"].cancel()

    # Cancel any existing stream for this conversation
    await cancel_active_stream()

    event_queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    cancel_event = asyncio.Event()
    task = asyncio.create_task(stream_worker(event_queue, cancel_event))
    ACTIVE_STREAMS[conversation_id] = {"task": task, "cancel_event": cancel_event}

    async def event_generator():
        try:
            while True:
                if await http_request.is_disconnected():
                    await cancel_active_stream()
                    break

                event = await event_queue.get()
                yield f"data: {json.dumps(event)}\n\n"

                if event.get("type") in {"complete", "error", "cancelled"}:
                    break
        finally:
            await cleanup_active_stream()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/api/conversations/{conversation_id}/message/cancel")
async def cancel_message_stream(conversation_id: str):
    """
    Cancel an active streaming request for a conversation.
    """
    current = ACTIVE_STREAMS.pop(conversation_id, None)
    if current:
        current["cancel_event"].set()
        current["task"].cancel()
        return {"status": "ok", "cancelled": True}
    return {"status": "ok", "cancelled": False}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

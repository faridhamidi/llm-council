"""FastAPI backend for LLM Council."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, ValidationError
from typing import List, Dict, Any, Literal
import uuid
import json
import asyncio
import os

from . import storage
from . import db
from . import session_store
from .config import (
    get_bedrock_region,
    set_bedrock_region,
    BEDROCK_REGION_OPTIONS,
    list_converse_models_for_region,
    MAX_FOLLOW_UP_MESSAGES,
    SPEAKER_CONTEXT_LEVELS,
    get_bedrock_api_key,
)
from .council_settings import (
    get_settings,
    update_settings,
    MAX_COUNCIL_MEMBERS,
    MAX_COUNCIL_STAGES,
    MAX_STAGE_MEMBERS,
    build_default_stages,
    normalize_settings_for_region,
)
from .council_presets import (
    list_presets,
    create_preset,
    find_preset,
    delete_preset,
)
from .council import (
    run_full_council,
    generate_conversation_title,
    stage1_collect_responses,
    stage2_collect_rankings,
    stage3_synthesize_final,
    calculate_aggregate_rankings,
    query_council_speaker,
    estimate_token_count,
)

app = FastAPI(title="LLM Council API")
DISABLE_APP_PIN = os.getenv("DISABLE_APP_PIN", "").lower() in {"1", "true", "yes"}

# Track active streaming tasks so they can be cancelled from the UI.
ACTIVE_STREAMS: Dict[str, Dict[str, Any]] = {}

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$|^http://.*:(5173|3000)$|^https://.*\.trycloudflare\.com$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# PIN gate. If no PIN exists, only allow setup + status endpoints.
@app.middleware("http")
async def _session_middleware(request: Request, call_next):
    session_id, is_new = session_store.ensure_session(
        request.cookies.get(session_store.SESSION_COOKIE_NAME)
    )
    request.state.session_id = session_id
    response = await call_next(request)
    if is_new:
        is_https = request.url.scheme == "https"
        response.set_cookie(
            session_store.SESSION_COOKIE_NAME,
            session_id,
            httponly=True,
            samesite="None" if is_https else "Lax",
            secure=is_https,
        )
    return response


@app.middleware("http")
async def _require_pin(request: Request, call_next):
    if DISABLE_APP_PIN:
        return await call_next(request)
    if request.method == "OPTIONS":
        return await call_next(request)
    if request.url.path.startswith("/api"):
        if request.url.path in {"/api/auth/status", "/api/auth/setup"}:
            return await call_next(request)
        if request.url.path == "/api/auth/policy":
            return await call_next(request)

        policy = db.get_auth_policy()
        if policy is None:
            return JSONResponse(status_code=401, content={"detail": "PIN_SETUP_REQUIRED"})
        if policy == "disabled":
            return await call_next(request)

        if not db.has_auth_pin():
            return JSONResponse(status_code=401, content={"detail": "PIN_REQUIRED"})

        supplied = request.headers.get("x-llm-council-pin", "")
        if not supplied or not db.verify_auth_pin(supplied):
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


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


class AuthPinRequest(BaseModel):
    """Request to set the access PIN."""
    pin: str


class AuthPolicyRequest(BaseModel):
    """Request to set the PIN policy for a deployment."""
    enabled: bool

MAX_SYSTEM_PROMPT_CHARS = 4000


class CouncilMemberConfig(BaseModel):
    id: str
    alias: str
    model_id: str
    system_prompt: str | None = ""


class CouncilStageConfig(BaseModel):
    id: str
    name: str
    prompt: str | None = ""
    execution_mode: Literal["parallel", "sequential"] = "parallel"
    member_ids: List[str]


class CouncilSettingsRequest(BaseModel):
    members: List[CouncilMemberConfig]
    chairman_id: str
    chairman_label: str | None = "Chairman"
    title_model_id: str
    use_system_prompt_stage2: bool = True
    use_system_prompt_stage3: bool = True
    stages: List[CouncilStageConfig] | None = None


class CouncilPresetRequest(BaseModel):
    name: str
    settings: CouncilSettingsRequest


class CouncilPresetApplyRequest(BaseModel):
    preset_id: str


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


@app.get("/api/auth/status")
async def auth_status():
    """Return whether a PIN is configured."""
    if DISABLE_APP_PIN:
        return {"has_pin": False, "disabled": True, "policy": "disabled", "requires_setup": False}
    policy = db.get_auth_policy()
    return {
        "has_pin": db.has_auth_pin(),
        "disabled": False,
        "policy": policy,
        "requires_setup": policy is None,
    }


@app.post("/api/auth/setup")
async def auth_setup(request: AuthPinRequest):
    """Set the access PIN if none exists."""
    if DISABLE_APP_PIN:
        raise HTTPException(status_code=400, detail="PIN is disabled")
    pin = request.pin.strip()
    if not pin:
        raise HTTPException(status_code=400, detail="PIN is required")
    if len(pin) < 4:
        raise HTTPException(status_code=400, detail="PIN must be at least 4 characters")
    if db.has_auth_pin():
        raise HTTPException(status_code=409, detail="PIN already set")
    db.set_auth_pin(pin)
    if db.get_auth_policy() is None:
        db.set_auth_policy("required")
    return {"status": "ok", "has_pin": True}


@app.post("/api/auth/policy")
async def set_auth_policy(request: AuthPolicyRequest):
    """Set the PIN policy for this deployment."""
    if DISABLE_APP_PIN:
        raise HTTPException(status_code=400, detail="PIN is disabled")
    if db.get_auth_policy() is not None:
        raise HTTPException(status_code=409, detail="PIN policy already configured")
    policy = "required" if request.enabled else "disabled"
    db.set_auth_policy(policy)
    return {"status": "ok", "policy": policy}


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
async def send_message(conversation_id: str, payload: SendMessageRequest, http_request: Request):
    """
    Send a message to a conversation.
    - First message: Run full council process
    - Follow-up messages: Query council speaker only
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    session_id = http_request.state.session_id
    bedrock_key = session_store.get_bedrock_key(session_id)
    if not bedrock_key:
        bedrock_key = get_bedrock_api_key()
    if not bedrock_key:
        raise HTTPException(status_code=400, detail="Bedrock key not set. Please configuring it in the settings or .env file.")

    # Estimate tokens for user message
    user_token_count = estimate_token_count(payload.content)
    
    # Add user message
    storage.add_user_message(conversation_id, payload.content, token_count=user_token_count)

    if is_first_message:
        # First message: Run full council process
        
        # Generate title in parallel
        title = await generate_conversation_title(payload.content, api_key=bedrock_key)
        storage.update_conversation_title(conversation_id, title)

        # Snapshot current settings for this conversation
        current_settings = get_settings()
        storage.save_settings_snapshot(conversation_id, current_settings)

        # Run the 3-stage council process
        stage1_results, stage2_results, stage3_result, metadata, stages = await run_full_council(
            payload.content,
            api_key=bedrock_key,
        )

        # Estimate tokens for response
        response_tokens = estimate_token_count(str(stage3_result.get("response", "")))

        # Add assistant message with all stages
        storage.add_assistant_message(
            conversation_id,
            stage1_results,
            stage2_results,
            stage3_result,
            stages=stages,
            token_count=response_tokens,
        )

        # Refresh conversation to get updated data
        updated_conversation = storage.get_conversation(conversation_id)

        # Return the complete response with metadata
        return {
            "message_type": "council",
            "stage1": stage1_results,
            "stage2": stage2_results,
            "stage3": stage3_result,
            "metadata": metadata,
            "stages": stages,
            "remaining_messages": MAX_FOLLOW_UP_MESSAGES,
            "total_tokens": updated_conversation.get("total_tokens", 0),
        }
    else:
        # Follow-up message: Use council speaker
        
        # Count user messages to check limit (exclude the one we just added)
        user_message_count = sum(1 for msg in conversation["messages"] if msg.get("role") == "user")
        
        if user_message_count >= MAX_FOLLOW_UP_MESSAGES:
            raise HTTPException(
                status_code=400,
                detail=f"Message limit reached. Maximum {MAX_FOLLOW_UP_MESSAGES} follow-up messages per conversation."
            )
        
        # Get settings snapshot (or current settings as fallback)
        settings = conversation.get("settings_snapshot") or get_settings()
        
        # Refresh conversation to include the new user message
        conversation = storage.get_conversation(conversation_id)
        
        # Query the council speaker
        speaker_response = await query_council_speaker(
            payload.content,
            conversation["messages"],
            settings,
            api_key=bedrock_key,
        )
        
        # Add speaker message
        storage.add_speaker_message(
            conversation_id,
            speaker_response.get("response", ""),
            token_count=speaker_response.get("token_count", 0),
        )
        
        # Calculate remaining messages
        remaining = MAX_FOLLOW_UP_MESSAGES - user_message_count - 1
        
        # Refresh conversation to get updated token count
        updated_conversation = storage.get_conversation(conversation_id)
        
        return {
            "message_type": "speaker",
            "model": speaker_response.get("model"),
            "response": speaker_response.get("response"),
            "error": speaker_response.get("error", False),
            "remaining_messages": remaining,
            "total_tokens": updated_conversation.get("total_tokens", 0),
        }


@app.post("/api/conversations/{conversation_id}/message/retry")
async def retry_message(conversation_id: str, http_request: Request):
    """
    Retry the last message by deleting it and re-running the query.
    """
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    messages = conversation.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="No messages to retry")
    
    # Find the last user message and corresponding assistant message
    last_user_msg = None
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user_msg = msg
            break
    
    if not last_user_msg:
        raise HTTPException(status_code=400, detail="No user message to retry")
    
    # Delete the last assistant message
    storage.delete_last_assistant_message(conversation_id)
    
    # Re-run with the same content
    class RetryPayload:
        content = last_user_msg.get("content", "")
    
    # Use the send_message logic but skip adding the user message
    session_id = http_request.state.session_id
    bedrock_key = session_store.get_bedrock_key(session_id)
    if not bedrock_key:
        bedrock_key = get_bedrock_api_key()
    if not bedrock_key:
        raise HTTPException(status_code=400, detail="Bedrock key not set. Please configuring it in the settings or .env file.")
    
    # Refresh conversation
    conversation = storage.get_conversation(conversation_id)
    settings = conversation.get("settings_snapshot") or get_settings()
    
    # Determine if this was a council or speaker response
    user_message_count = sum(1 for msg in conversation.get("messages", []) if msg.get("role") == "user")
    
    if user_message_count == 1:
        # This was the first message - retry full council
        stage1_results, stage2_results, stage3_result, metadata, stages = await run_full_council(
            last_user_msg.get("content", ""),
            api_key=bedrock_key,
        )
        
        response_tokens = estimate_token_count(str(stage3_result.get("response", "")))
        storage.add_assistant_message(
            conversation_id,
            stage1_results,
            stage2_results,
            stage3_result,
            stages=stages,
            token_count=response_tokens,
        )
        
        updated_conversation = storage.get_conversation(conversation_id)
        return {
            "message_type": "council",
            "stage1": stage1_results,
            "stage2": stage2_results,
            "stage3": stage3_result,
            "metadata": metadata,
            "stages": stages,
            "remaining_messages": MAX_FOLLOW_UP_MESSAGES,
            "total_tokens": updated_conversation.get("total_tokens", 0),
        }
    else:
        # This was a follow-up - retry speaker query
        speaker_response = await query_council_speaker(
            last_user_msg.get("content", ""),
            conversation["messages"],
            settings,
            api_key=bedrock_key,
        )
        
        storage.add_speaker_message(
            conversation_id,
            speaker_response.get("response", ""),
            token_count=speaker_response.get("token_count", 0),
        )
        
        remaining = MAX_FOLLOW_UP_MESSAGES - user_message_count
        updated_conversation = storage.get_conversation(conversation_id)
        
        return {
            "message_type": "speaker",
            "model": speaker_response.get("model"),
            "response": speaker_response.get("response"),
            "error": speaker_response.get("error", False),
            "remaining_messages": remaining,
            "total_tokens": updated_conversation.get("total_tokens", 0),
        }


@app.get("/api/conversations/{conversation_id}/info")
async def get_conversation_info(conversation_id: str):
    """
    Get conversation metadata including remaining messages and token count.
    """
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    messages = conversation.get("messages", [])
    user_message_count = sum(1 for msg in messages if msg.get("role") == "user")
    
    # First message doesn't count against limit
    follow_up_count = max(0, user_message_count - 1)
    remaining = MAX_FOLLOW_UP_MESSAGES - follow_up_count
    
    return {
        "id": conversation.get("id"),
        "title": conversation.get("title"),
        "message_count": len(messages),
        "user_message_count": user_message_count,
        "remaining_messages": remaining,
        "max_follow_up_messages": MAX_FOLLOW_UP_MESSAGES,
        "total_tokens": conversation.get("total_tokens", 0),
        "has_settings_snapshot": conversation.get("settings_snapshot") is not None,
    }


@app.get("/api/settings/speaker-context-levels")
async def get_speaker_context_levels():
    """Get available speaker context level options."""
    return {
        "levels": SPEAKER_CONTEXT_LEVELS,
        "default": "full",
    }


@app.post("/api/settings/bedrock-token")
async def update_bedrock_token(payload: UpdateBedrockTokenRequest, http_request: Request):
    """
    Update the Bedrock API key at runtime (in-memory only).
    """
    token = payload.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token is required")

    session_id = http_request.state.session_id
    session_store.set_bedrock_key(session_id, token)
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
    settings = normalize_settings_for_region(get_settings(), region)
    update_settings(settings)
    return {"status": "ok", "region": region, "settings": settings}


@app.get("/api/settings/council")
async def get_council_settings():
    """Return current council settings."""
    return get_settings()


@app.get("/api/settings/council/presets")
async def get_council_presets():
    """Return available council presets."""
    return {"presets": list_presets()}


@app.get("/api/settings/bedrock-models")
async def get_bedrock_models():
    """Return Converse-capable models for the current region."""
    region = get_bedrock_region()
    return {"region": region, "models": list_converse_models_for_region(region)}


def _validate_council_settings(payload: CouncilSettingsRequest) -> List[str]:
    errors: List[str] = []
    members = payload.members
    if not members:
        errors.append("At least one council member is required.")
    if len(members) > MAX_COUNCIL_MEMBERS:
        errors.append(f"Maximum {MAX_COUNCIL_MEMBERS} council members allowed.")

    ids = [member.id for member in members]
    aliases = [member.alias.strip() for member in members]
    if len(set(ids)) != len(ids):
        errors.append("Member IDs must be unique.")
    if len(set(a.lower() for a in aliases)) != len(aliases):
        errors.append("Member aliases must be unique.")
    if any(not alias for alias in aliases):
        errors.append("Member aliases cannot be empty.")

    allowed_models = {model["id"] for model in list_converse_models_for_region(get_bedrock_region())}
    for member in members:
        if member.model_id not in allowed_models:
            errors.append(f"Unsupported model for region: {member.model_id}")
            break
        prompt_value = member.system_prompt or ""
        if len(prompt_value) > MAX_SYSTEM_PROMPT_CHARS:
            errors.append(f"System prompt too long for {member.alias}.")
            break

    if payload.title_model_id not in allowed_models:
        errors.append(f"Unsupported title model for region: {payload.title_model_id}")

    if payload.chairman_id not in ids:
        errors.append("Chairman must be one of the council members.")

    stages = (
        [stage.model_dump() for stage in payload.stages]
        if payload.stages
        else build_default_stages(
            [member.model_dump() for member in members],
            payload.chairman_id,
        )
    )
    if len(stages) > MAX_COUNCIL_STAGES:
        errors.append(f"Maximum {MAX_COUNCIL_STAGES} stages allowed.")
    stage_ids = [stage["id"] for stage in stages]
    if len(set(stage_ids)) != len(stage_ids):
        errors.append("Stage IDs must be unique.")
    for stage in stages:
        stage_name = (stage.get("name") or "").strip()
        if not stage_name:
            errors.append("Stage names cannot be empty.")
            break
        member_ids = stage.get("member_ids", [])
        if not member_ids:
            errors.append(f"Stage '{stage_name}' must include at least one member.")
            break
        if len(member_ids) > MAX_STAGE_MEMBERS:
            errors.append(f"Stage '{stage_name}' exceeds max members ({MAX_STAGE_MEMBERS}).")
            break
        if any(member_id not in ids for member_id in member_ids):
            errors.append(f"Stage '{stage_name}' references unknown members.")
            break

    return errors


@app.post("/api/settings/council")
async def update_council_settings(request: CouncilSettingsRequest):
    """Update council settings."""
    errors = _validate_council_settings(request)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    stages = (
        [stage.model_dump() for stage in request.stages]
        if request.stages
        else build_default_stages(
            [member.model_dump() for member in request.members],
            request.chairman_id,
        )
    )
    settings = {
        "version": 2,
        "max_members": MAX_COUNCIL_MEMBERS,
        "members": [member.model_dump() for member in request.members],
        "chairman_id": request.chairman_id,
        "chairman_label": request.chairman_label or "Chairman",
        "title_model_id": request.title_model_id,
        "use_system_prompt_stage2": request.use_system_prompt_stage2,
        "use_system_prompt_stage3": request.use_system_prompt_stage3,
        "stages": stages,
    }

    update_settings(settings)
    return {"status": "ok", "settings": settings}


@app.post("/api/settings/council/presets")
async def create_council_preset(request: CouncilPresetRequest):
    """Create a new council preset."""
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail={"errors": ["Preset name is required."]})
    errors = _validate_council_settings(request.settings)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})
    try:
        preset = create_preset(name, request.settings.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from exc
    was_updated = "updated_at" in preset
    return {"status": "ok", "preset": preset, "presets": list_presets(), "updated": was_updated}


@app.post("/api/settings/council/presets/apply")
async def apply_council_preset(request: CouncilPresetApplyRequest):
    """Apply a preset to the current council settings."""
    preset = find_preset(request.preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    region = get_bedrock_region()
    settings = normalize_settings_for_region(preset.get("settings", {}), region)

    try:
        payload = CouncilSettingsRequest.model_validate(settings)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from exc

    errors = _validate_council_settings(payload)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    update_settings(settings)
    return {"status": "ok", "settings": settings, "preset": {"id": preset["id"], "name": preset["name"]}}


@app.delete("/api/settings/council/presets/{preset_id}")
async def delete_council_preset(preset_id: str):
    """Delete a council preset."""
    try:
        deleted = delete_preset(preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"errors": [str(exc)]}) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Preset not found")
    return {"status": "ok", "presets": list_presets()}


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

    session_id = http_request.state.session_id
    bedrock_key = session_store.get_bedrock_key(session_id)
    if not bedrock_key:
        bedrock_key = get_bedrock_api_key()
    if not bedrock_key:
        raise HTTPException(status_code=400, detail="Bedrock key not set. Please configuring it in the settings or .env file.")

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
                title_task = asyncio.create_task(generate_conversation_title(request.content, api_key=bedrock_key))

            # Stage 1: Collect responses
            await event_queue.put({"type": "stage1_start"})
            stage1_results = await stage1_collect_responses(request.content, api_key=bedrock_key)
            await event_queue.put({"type": "stage1_complete", "data": stage1_results})

            if cancel_event.is_set():
                await event_queue.put({"type": "cancelled"})
                return

            # Stage 2: Collect rankings
            await event_queue.put({"type": "stage2_start"})
            stage2_results, label_to_model = await stage2_collect_rankings(
                request.content,
                stage1_results,
                api_key=bedrock_key,
            )
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
            stage3_result = await stage3_synthesize_final(
                request.content,
                stage1_results,
                stage2_results,
                api_key=bedrock_key,
            )
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
# Ensure database connectivity on startup.
@app.on_event("startup")
async def _startup_check_db() -> None:
    try:
        db.check_db()
    except Exception as exc:
        print(f"Database health check failed: {exc}")
        raise

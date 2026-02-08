"""FastAPI backend for LLM Council."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, ValidationError
from typing import List, Dict, Any, Literal
from contextlib import asynccontextmanager
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
    MAX_CHAT_MESSAGES,
    SPEAKER_CONTEXT_LEVELS,
)
from .openrouter import check_bedrock_connection
from .council_settings import (
    get_settings,
    update_settings,
    MAX_COUNCIL_MEMBERS,
    MAX_COUNCIL_STAGES,
    MAX_STAGE_MEMBERS,
    build_default_stages,
    normalize_settings_for_region,
    regenerate_settings_ids,
    sanitize_settings_ids,
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
    get_final_response,
    query_council_speaker,
    query_normal_chat,
    estimate_token_count,
)

def calculate_council_output_count(messages: List[Dict[str, Any]]) -> int:
    """
    Calculate the total number of council outputs (responses) generated in the conversation.
    This iterates through all messages, finds 'council' type messages, and sums up the
    number of results in all stages.
    """
    count = 0
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("message_type") == "council":
            stages = msg.get("stages", [])
            for stage in stages:
                results = stage.get("results")
                if isinstance(results, list):
                    # List of results (e.g. from parallel execution or rankings)
                    count += len(results)
                elif isinstance(results, dict):
                    # Single result (e.g. synthesis)
                    count += 1
    return count


def _get_session_bedrock_token(request: Request) -> str | None:
    """
    Hidden fallback path: per-session bearer token support remains available
    for manual/debug use, but UI no longer exposes token controls.
    """
    session_id = request.state.session_id
    return session_store.get_bedrock_key(session_id)


def _calculate_chat_remaining(messages: List[Dict[str, Any]]) -> int:
    user_message_count = sum(1 for msg in messages if msg.get("role") == "user")
    return max(0, MAX_CHAT_MESSAGES - user_message_count)

@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        db.check_db()
        yield
    except Exception as exc:
        print(f"Database health check failed: {exc}")
        raise


app = FastAPI(title="LLM Council API", lifespan=lifespan)
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
    mode: Literal["council", "chat"] = "council"


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str
    force_council: bool = False


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
    mode: Literal["council", "chat"] = "council"
    message_count: int


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    mode: Literal["council", "chat"] = "council"
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
    mode = request.mode or "council"
    conversation = storage.create_conversation(conversation_id, mode=mode)
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

    conversation_mode = conversation.get("mode", "council")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    bedrock_key = _get_session_bedrock_token(http_request)

    if conversation_mode == "chat":
        current_user_messages = sum(1 for msg in conversation.get("messages", []) if msg.get("role") == "user")
        if current_user_messages >= MAX_CHAT_MESSAGES:
            raise HTTPException(
                status_code=400,
                detail=f"Message limit reached. Maximum {MAX_CHAT_MESSAGES} messages allowed in chat mode.",
            )

    # Estimate tokens for user message
    user_token_count = estimate_token_count(payload.content)
    
    # Add user message
    storage.add_user_message(conversation_id, payload.content, token_count=user_token_count)

    # Refresh conversation to get the message we just added (for context)
    conversation = storage.get_conversation(conversation_id)
    messages = conversation.get("messages", [])

    if conversation_mode == "chat":
        settings = conversation.get("settings_snapshot") or get_settings()
        if is_first_message and not conversation.get("settings_snapshot"):
            storage.save_settings_snapshot(conversation_id, settings)
            title = await generate_conversation_title(payload.content, api_key=bedrock_key)
            storage.update_conversation_title(conversation_id, title)

        chat_response = await query_normal_chat(
            payload.content,
            conversation.get("messages", []),
            settings,
            api_key=bedrock_key,
        )

        storage.add_speaker_message(
            conversation_id,
            chat_response.get("response", ""),
            token_count=chat_response.get("token_count", 0),
        )

        updated_conversation = storage.get_conversation(conversation_id)
        return {
            "message_type": "speaker",
            "model": chat_response.get("model", "Assistant"),
            "response": chat_response.get("response", ""),
            "error": chat_response.get("error", False),
            "remaining_messages": _calculate_chat_remaining(updated_conversation.get("messages", [])),
            "max_messages": MAX_CHAT_MESSAGES,
            "mode": "chat",
            "total_tokens": updated_conversation.get("total_tokens", 0),
        }

    if is_first_message or payload.force_council:
        # Run full council process (either first run or manual reconvene)
        
        # Generate title in parallel if first message
        if is_first_message:
            title = await generate_conversation_title(payload.content, api_key=bedrock_key)
            storage.update_conversation_title(conversation_id, title)
            # Use current settings
            settings = get_settings()
            storage.save_settings_snapshot(conversation_id, settings)
        else:
            # For reconvene, use existing snapshot or fallback
            settings = conversation.get("settings_snapshot") or get_settings()

        # Run the council pipeline with HISTORY
        stages, metadata = await run_full_council(
            payload.content,
            api_key=bedrock_key,
            settings=settings,
            conversation_messages=messages[:-1] if not is_first_message else None # Exclude the very last message if it's the trigger? 
            # Actually, standard is to include history UP TO the current prompt. 
            # The prompt IS the user's last message.
            # So history should be everything BEFORE the last message.
        )

        final_result = get_final_response(stages)

        # Estimate tokens for response
        response_tokens = estimate_token_count(str(final_result.get("response", "")))

        # Add assistant message with all stages
        storage.add_assistant_message(
            conversation_id,
            stages,
            token_count=response_tokens,
        )

        # Refresh conversation to get updated data
        updated_conversation = storage.get_conversation(conversation_id)

        # Return the complete response with metadata
        return {
            "message_type": "council",
            "metadata": metadata,
            "stages": stages,
            "remaining_messages": MAX_FOLLOW_UP_MESSAGES + calculate_council_output_count(updated_conversation.get("messages", [])),
            "total_tokens": updated_conversation.get("total_tokens", 0),
        }
    else:
        # Follow-up message: Use council speaker
        
        # Count user messages to check limit (exclude the one we just added?)
        # Wait, the logic before was calculating limit based on EXISTING messages.
        user_message_count = sum(1 for msg in conversation["messages"] if msg.get("role") == "user")
        
        # Calculate dynamic limit based on council outputs
        council_outputs = calculate_council_output_count(conversation["messages"])
        dynamic_limit = MAX_FOLLOW_UP_MESSAGES + council_outputs

        # First message uses 0 follow-ups.
        used_followups = max(0, user_message_count - 1)
        
        if used_followups >= dynamic_limit:
            raise HTTPException(
                status_code=400,
                detail=f"Message limit reached. Maximum {dynamic_limit} follow-up messages allowed for this conversation. You can trigger a full council reconvene to reset."
            )
        
        # Get settings snapshot (or current settings as fallback)
        settings = conversation.get("settings_snapshot") or get_settings()
        
        # Query the council speaker
        speaker_response = await query_council_speaker(
            payload.content,
            conversation["messages"], # This includes the new user message
            settings,
            api_key=bedrock_key,
        )
        
        # Add speaker message
        storage.add_speaker_message(
            conversation_id,
            speaker_response.get("response", ""),
            token_count=speaker_response.get("token_count", 0),
        )
        
        # Refresh conversation to get updated token count
        updated_conversation = storage.get_conversation(conversation_id)
        
        # Re-calc limit for UI
        council_outputs = calculate_council_output_count(conversation["messages"])
        dynamic_limit = MAX_FOLLOW_UP_MESSAGES + council_outputs
        
        # Recalculate remaining
        # conversation["messages"] has the new user message + new speaker message (not yet? no storage.get is before add_speaker)
        # updated_conversation has both.
        user_message_count = sum(1 for msg in updated_conversation["messages"] if msg.get("role") == "user")
        used_followups = max(0, user_message_count - 1) # Approximate
        remaining = max(0, dynamic_limit - used_followups)

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
    bedrock_key = _get_session_bedrock_token(http_request)
    
    # Refresh conversation
    conversation = storage.get_conversation(conversation_id)
    conversation_mode = conversation.get("mode", "council")
    settings = conversation.get("settings_snapshot") or get_settings()

    if conversation_mode == "chat":
        chat_response = await query_normal_chat(
            last_user_msg.get("content", ""),
            conversation.get("messages", []),
            settings,
            api_key=bedrock_key,
        )

        storage.add_speaker_message(
            conversation_id,
            chat_response.get("response", ""),
            token_count=chat_response.get("token_count", 0),
        )
        updated_conversation = storage.get_conversation(conversation_id)
        return {
            "message_type": "speaker",
            "model": chat_response.get("model", "Assistant"),
            "response": chat_response.get("response", ""),
            "error": chat_response.get("error", False),
            "remaining_messages": _calculate_chat_remaining(updated_conversation.get("messages", [])),
            "max_messages": MAX_CHAT_MESSAGES,
            "mode": "chat",
            "total_tokens": updated_conversation.get("total_tokens", 0),
        }
    
    # Determine if this was a council or speaker response
    user_message_count = sum(1 for msg in conversation.get("messages", []) if msg.get("role") == "user")
    
    if user_message_count == 1:
        # This was the first message - retry full council
        # This was the first message - retry full council
        # We need to construct history. Since we deleted the last assistant message,
        # the history is everything in 'messages' up to the last user message.
        # But wait, 'messages' here comes from storage BEFORE deletion?
        # No, we called storage.delete_last_assistant_message.
        # So we should re-fetch conversation.
        updated_conv = storage.get_conversation(conversation_id)
        current_messages = updated_conv.get("messages", [])
        
        # We need to exclude the very last user message (the one being retried) from history
        history = current_messages[:-1] if current_messages else []

        stages, metadata = await run_full_council(
            last_user_msg.get("content", ""),
            api_key=bedrock_key,
            settings=settings,
            conversation_messages=history,
        )

        final_result = get_final_response(stages)
        response_tokens = estimate_token_count(str(final_result.get("response", "")))
        storage.add_assistant_message(
            conversation_id,
            stages,
            token_count=response_tokens,
        )
        
        updated_conversation = storage.get_conversation(conversation_id)
        return {
            "message_type": "council",
            "metadata": metadata,
            "stages": stages,
            "remaining_messages": MAX_FOLLOW_UP_MESSAGES + calculate_council_output_count(updated_conversation.get("messages", [])),
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
        updated_conversation = storage.get_conversation(conversation_id)
        council_outputs = calculate_council_output_count(updated_conversation.get("messages", []))
        dynamic_limit = MAX_FOLLOW_UP_MESSAGES + council_outputs
        used_followups = max(0, user_message_count) # user_message_count here includes only the ones before retry? No wait.
        # Logic in retry: we found last user msg, deleted assistant msg.
        # So user_message_count is the total user messages.
        # If it was a follow-up, used_followups = user_message_count - 1.
        used_followups = max(0, user_message_count - 1)
        
        remaining = max(0, dynamic_limit - used_followups)
        
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
    mode = conversation.get("mode", "council")
    user_message_count = sum(1 for msg in messages if msg.get("role") == "user")

    if mode == "chat":
        remaining = max(0, MAX_CHAT_MESSAGES - user_message_count)
        return {
            "id": conversation.get("id"),
            "title": conversation.get("title"),
            "mode": mode,
            "message_count": len(messages),
            "user_message_count": user_message_count,
            "remaining_messages": remaining,
            "max_messages": MAX_CHAT_MESSAGES,
            "total_tokens": conversation.get("total_tokens", 0),
            "has_settings_snapshot": conversation.get("settings_snapshot") is not None,
        }

    # Council mode: first message does not count against follow-up limit.
    follow_up_count = max(0, user_message_count - 1)
    council_outputs = calculate_council_output_count(messages)
    dynamic_limit = MAX_FOLLOW_UP_MESSAGES + council_outputs
    remaining = max(0, dynamic_limit - follow_up_count)

    return {
        "id": conversation.get("id"),
        "title": conversation.get("title"),
        "mode": mode,
        "message_count": len(messages),
        "user_message_count": user_message_count,
        "remaining_messages": remaining,
        "max_follow_up_messages": dynamic_limit,
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
    Hidden fallback: update bearer token at runtime (in-memory only).
    Primary path uses AWS SDK credentials (SSO/IAM).
    """
    token = payload.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token is required")

    session_id = http_request.state.session_id
    session_store.set_bedrock_key(session_id, token)
    return {"status": "ok"}


@app.get("/api/settings/bedrock-connection")
async def get_bedrock_connection_status(http_request: Request):
    """Return Bedrock credential status for UI diagnostics."""
    session_token = _get_session_bedrock_token(http_request)
    status = await check_bedrock_connection(api_key=session_token)
    return status


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
    # DECOUPLED: Aliases are no longer required to be globally unique since members are scoped to stages
    # if len(set(a.lower() for a in aliases)) != len(aliases):
    #     errors.append("Member aliases must be unique.")
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
        clean_settings = sanitize_settings_ids(request.settings.model_dump())
        preset = create_preset(name, clean_settings)
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
    # Normalize settings first (resolves models)
    settings = normalize_settings_for_region(preset.get("settings", {}), region)
    
    # Regenerate IDs to ensure uniqueness and unlink from preset defaults
    settings = regenerate_settings_ids(settings)
    settings["max_members"] = MAX_COUNCIL_MEMBERS

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
    print(f"DEBUG STREAM: content='{request.content[:20]}...', force_council={request.force_council}")
    """
    Send a message and stream the council process.
    Returns Server-Sent Events as each stage completes.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation_mode = conversation.get("mode", "council")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    bedrock_key = _get_session_bedrock_token(http_request)

    if conversation_mode == "chat":
        user_message_count = sum(1 for msg in conversation.get("messages", []) if msg.get("role") == "user")
        if user_message_count >= MAX_CHAT_MESSAGES:
            raise HTTPException(
                status_code=400,
                detail=f"Message limit reached. Maximum {MAX_CHAT_MESSAGES} messages allowed in chat mode.",
            )

    async def stream_worker(event_queue: "asyncio.Queue[Dict[str, Any]]", cancel_event: asyncio.Event):
        try:
            if cancel_event.is_set():
                await event_queue.put({"type": "cancelled"})
                return

            # Add user message
            user_token_count = estimate_token_count(request.content)
            storage.add_user_message(conversation_id, request.content, token_count=user_token_count)

            if conversation_mode == "chat":
                conversation_snapshot = storage.get_conversation(conversation_id) or {}
                settings = conversation_snapshot.get("settings_snapshot") or get_settings()
                if is_first_message and not conversation_snapshot.get("settings_snapshot"):
                    storage.save_settings_snapshot(conversation_id, settings)
                    title = await generate_conversation_title(request.content, api_key=bedrock_key)
                    storage.update_conversation_title(conversation_id, title)
                    await event_queue.put({"type": "title_complete", "data": {"title": title}})

                chat_response = await query_normal_chat(
                    request.content,
                    conversation_snapshot.get("messages", []),
                    settings,
                    api_key=bedrock_key,
                )

                storage.add_speaker_message(
                    conversation_id,
                    chat_response.get("response", ""),
                    token_count=chat_response.get("token_count", 0),
                )
                latest = storage.get_conversation(conversation_id) or {}
                await event_queue.put({
                    "type": "speaker_complete",
                    "data": chat_response,
                    "remaining_messages": _calculate_chat_remaining(latest.get("messages", [])),
                    "mode": "chat",
                })
                await event_queue.put({"type": "complete"})
                return

            if is_first_message or request.force_council:
                # Snapshot current settings for this conversation (if first message)
                # or use existing snapshot (if reconvene)
                if is_first_message:
                    current_settings = get_settings()
                    storage.save_settings_snapshot(conversation_id, current_settings)
                    
                    # Start title generation in parallel (don't await yet)
                    title_task = asyncio.create_task(generate_conversation_title(request.content, api_key=bedrock_key))
                else:
                    conversation_snapshot = storage.get_conversation(conversation_id) or {}
                    current_settings = conversation_snapshot.get("settings_snapshot") or get_settings()
                    title_task = None # No title generation for reconvene? Or maybe we should? Probably not needed.

                async def on_stage_start(stage_entry: Dict[str, Any]) -> None:
                    if cancel_event.is_set():
                        raise asyncio.CancelledError()
                    await event_queue.put({"type": "stage_start", "data": stage_entry})

                async def on_stage_complete(stage_entry: Dict[str, Any]) -> None:
                    await event_queue.put({"type": "stage_complete", "data": stage_entry})
                    if cancel_event.is_set():
                        raise asyncio.CancelledError()

                # Get history for reconvening
                conversation_snapshot = storage.get_conversation(conversation_id) or {}
                messages = conversation_snapshot.get("messages", [])
                # The user message was JUST added. So history is everything up to the user message.
                # messages includes the new user message at the end.
                # So we pass messages[:-1] as history.
                history = messages[:-1] if not is_first_message else None

                stages, _ = await run_full_council(
                    request.content,
                    api_key=bedrock_key,
                    settings=current_settings,
                    on_stage_start=on_stage_start,
                    on_stage_complete=on_stage_complete,
                    conversation_messages=history,
                )

                # Wait for title generation if it exists
                if title_task:
                    title = await title_task
                    storage.update_conversation_title(conversation_id, title)
                    await event_queue.put({"type": "title_complete", "data": {"title": title}})

                final_result = get_final_response(stages)
                response_tokens = estimate_token_count(str(final_result.get("response", "")))

                # Save complete assistant message
                storage.add_assistant_message(
                    conversation_id,
                    stages,
                    token_count=response_tokens,
                )

                # Send completion event
                await event_queue.put({"type": "complete"})
            else:
                # Follow-up message: Use council speaker only
                if cancel_event.is_set():
                    await event_queue.put({"type": "cancelled"})
                    return

                # Refresh conversation to include the new user message
                conversation_snapshot = storage.get_conversation(conversation_id) or {}
                settings = conversation_snapshot.get("settings_snapshot") or get_settings()

                speaker_response = await query_council_speaker(
                    request.content,
                    conversation_snapshot.get("messages", []),
                    settings,
                    api_key=bedrock_key,
                )

                storage.add_speaker_message(
                    conversation_id,
                    speaker_response.get("response", ""),
                    token_count=speaker_response.get("token_count", 0),
                )

                await event_queue.put({"type": "speaker_complete", "data": speaker_response})
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

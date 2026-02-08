"""Bedrock Runtime client for making LLM requests via Converse."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx

from .config import (
    BEDROCK_MAX_OUTPUT_TOKENS,
    get_bedrock_api_key,
    get_bedrock_region,
    get_bedrock_runtime_url,
)

_MODEL_LIST_CACHE_TTL_SECONDS = 120.0
_MODEL_LIST_CACHE: Dict[str, Dict[str, Any]] = {}


def _build_bedrock_messages(messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    bedrock_messages: List[Dict[str, Any]] = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if isinstance(content, list):
            content_blocks = content
        else:
            content_blocks = [{"text": str(content)}]
        bedrock_messages.append({
            "role": role,
            "content": content_blocks,
        })
    return bedrock_messages


def _parse_converse_response(data: Dict[str, Any]) -> Dict[str, Any]:
    message = data.get("output", {}).get("message", {})
    content_blocks = message.get("content", []) or []
    text_parts: List[str] = []
    reasoning_parts: List[str] = []

    for block in content_blocks:
        if "text" in block:
            text_parts.append(block["text"])
            continue

        reasoning_content = block.get("reasoningContent")
        if not reasoning_content:
            continue

        # Keep compatibility across API representations.
        direct_text = reasoning_content.get("text")
        if direct_text:
            reasoning_parts.append(direct_text)
            continue

        nested_text = (
            reasoning_content.get("reasoningText", {})
            .get("text")
        )
        if nested_text:
            reasoning_parts.append(nested_text)

    return {
        "content": "\n".join(text_parts).strip(),
        "reasoning_details": "\n".join(reasoning_parts).strip() if reasoning_parts else None,
    }


def _extract_text_from_stream_event(event: Dict[str, Any]) -> tuple[str, str]:
    delta_event = event.get("contentBlockDelta")
    if not isinstance(delta_event, dict):
        return "", ""

    delta = delta_event.get("delta")
    if not isinstance(delta, dict):
        return "", ""

    text = delta.get("text")
    if isinstance(text, str) and text:
        return text, ""

    reasoning = delta.get("reasoningContent")
    if isinstance(reasoning, dict):
        direct_text = reasoning.get("text")
        if isinstance(direct_text, str) and direct_text:
            return "", direct_text
        nested_text = (
            reasoning.get("reasoningText", {})
            .get("text")
        )
        if isinstance(nested_text, str) and nested_text:
            return "", nested_text

    return "", ""


def _resolve_max_output_tokens(max_output_tokens: int | None = None) -> int:
    if max_output_tokens is None:
        return BEDROCK_MAX_OUTPUT_TOKENS
    try:
        parsed = int(max_output_tokens)
    except (TypeError, ValueError):
        return BEDROCK_MAX_OUTPUT_TOKENS
    if parsed < 1:
        return BEDROCK_MAX_OUTPUT_TOKENS
    return parsed


def _aws_profile_hint(aws_profile: str | None = None) -> str:
    profile = _resolve_aws_profile(aws_profile)
    if profile:
        return f"aws sso login --profile {profile}"
    return "aws sso login"


def _resolve_aws_profile(aws_profile: str | None = None) -> str | None:
    explicit_profile = (aws_profile or "").strip()
    if explicit_profile:
        return explicit_profile

    profile = os.getenv("AWS_PROFILE", "").strip()
    if profile:
        return profile

    default_profile = os.getenv("AWS_DEFAULT_PROFILE", "").strip()
    if default_profile:
        return default_profile

    # Convenience fallback: if exactly one profile exists locally, use it.
    # This helps when users authenticate with `aws sso login --profile X`
    # but forget to export AWS_PROFILE before starting the app.
    try:
        import boto3  # type: ignore
        profiles = boto3.session.Session().available_profiles
    except Exception:
        return None

    if len(profiles) == 1:
        return profiles[0]
    return None


def list_local_aws_profiles() -> List[str]:
    try:
        import boto3  # type: ignore
        profiles = boto3.session.Session().available_profiles
        return sorted(profiles)
    except Exception:
        return []


def _normalize_boto3_error(exc: Exception, aws_profile: str | None = None) -> str:
    message = str(exc)

    try:
        from botocore.exceptions import (  # type: ignore
            ClientError,
            CredentialRetrievalError,
            NoCredentialsError,
            PartialCredentialsError,
            UnauthorizedSSOTokenError,
        )
    except Exception:
        return f"Bedrock request failed: {message}"

    relogin_help = (
        f"AWS SSO session expired or invalid. Run `{_aws_profile_hint(aws_profile)}` and retry."
    )

    if isinstance(exc, UnauthorizedSSOTokenError):
        return relogin_help

    if isinstance(exc, (NoCredentialsError, PartialCredentialsError, CredentialRetrievalError)):
        return (
            "AWS credentials not found. Configure SSO (`aws configure sso`), "
            f"run `{_aws_profile_hint(aws_profile)}`, and retry."
        )

    if isinstance(exc, ClientError):
        error = exc.response.get("Error", {}) if isinstance(exc.response, dict) else {}
        code = (error.get("Code") or "").strip()
        detail = (error.get("Message") or "").strip()

        if code in {"ExpiredTokenException", "InvalidSignatureException", "UnrecognizedClientException"}:
            return relogin_help

        if code in {"AccessDeniedException", "NotAuthorizedException"}:
            return (
                "AWS credentials are valid but lack Bedrock permissions. "
                "Grant Bedrock Converse/Invoke permissions to this role."
            )

        if code in {"ResourceNotFoundException"}:
            return (
                "Bedrock model or inference profile not found in the selected region. "
                "Check model ID and Bedrock region settings."
            )

        if detail:
            return f"Bedrock API error ({code}): {detail}"
        if code:
            return f"Bedrock API error ({code})."

    if "sso" in message.lower() and "token" in message.lower():
        return relogin_help

    return f"Bedrock request failed: {message}"


async def _query_model_with_bearer(
    model: str,
    bedrock_messages: List[Dict[str, Any]],
    timeout: float,
    system_prompt: Optional[str],
    api_key: str,
    max_output_tokens: int | None = None,
) -> Dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async def _post(payload: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{get_bedrock_runtime_url()}/model/{model}/converse",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    resolved_max_tokens = _resolve_max_output_tokens(max_output_tokens)

    payload: Dict[str, Any] = {
        "messages": bedrock_messages,
        "inferenceConfig": {"maxTokens": resolved_max_tokens},
    }
    if system_prompt:
        payload["system"] = [{"text": system_prompt}]

    system_prompt_dropped = False
    try:
        try:
            data = await _post(payload)
        except httpx.HTTPStatusError as exc:
            if system_prompt and exc.response is not None and exc.response.status_code == 400:
                data = await _post({
                    "messages": bedrock_messages,
                    "inferenceConfig": {"maxTokens": resolved_max_tokens},
                })
                system_prompt_dropped = True
            else:
                raise

        parsed = _parse_converse_response(data)
        if system_prompt_dropped:
            parsed["system_prompt_dropped"] = True
        return parsed
    except Exception as exc:
        return {"error": f"Bearer token request failed: {exc}"}


def _sync_converse_with_sdk(
    model: str,
    bedrock_messages: List[Dict[str, Any]],
    system_prompt: Optional[str],
    timeout: float = 300.0,
    aws_profile: str | None = None,
    max_output_tokens: int | None = None,
) -> Dict[str, Any]:
    try:
        import boto3  # type: ignore
        from botocore.exceptions import ClientError  # type: ignore
    except Exception as exc:  # pragma: no cover - import path only
        return {
            "error": (
                "AWS SDK for Python (boto3) is required for SSO-based Bedrock auth. "
                f"Install it and retry. ({exc})"
            )
        }

    profile = _resolve_aws_profile(aws_profile)
    region = get_bedrock_region()

    connect_timeout = max(2.0, min(10.0, timeout / 3.0))
    read_timeout = max(5.0, timeout)

    session = boto3.Session(profile_name=profile, region_name=region)
    client_kwargs: Dict[str, Any] = {"region_name": region}
    try:
        from botocore.config import Config  # type: ignore

        client_kwargs["config"] = Config(
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            retries={"max_attempts": 2, "mode": "standard"},
        )
    except Exception:
        pass
    client = session.client("bedrock-runtime", **client_kwargs)

    def _candidate_model_ids(base_model_id: str) -> List[str]:
        candidates = [base_model_id]
        parts = base_model_id.split(".", 1)
        if len(parts) == 2 and parts[0] in {"us", "global", "apac", "eu"}:
            stripped = parts[1]
            if stripped:
                candidates.append(stripped)
        return candidates

    for index, candidate in enumerate(_candidate_model_ids(model)):
        resolved_max_tokens = _resolve_max_output_tokens(max_output_tokens)
        payload: Dict[str, Any] = {
            "modelId": candidate,
            "messages": bedrock_messages,
            "inferenceConfig": {"maxTokens": resolved_max_tokens},
        }
        if system_prompt:
            payload["system"] = [{"text": system_prompt}]

        try:
            response = client.converse(**payload)
            parsed = _parse_converse_response(response)
            if candidate != model:
                parsed["resolved_model_id"] = candidate
            return parsed
        except ClientError as exc:
            error = exc.response.get("Error", {}) if isinstance(exc.response, dict) else {}
            code = error.get("Code")

            if system_prompt and code == "ValidationException":
                try:
                    retry_response = client.converse(
                        modelId=candidate,
                        messages=bedrock_messages,
                        inferenceConfig={"maxTokens": resolved_max_tokens},
                    )
                    parsed = _parse_converse_response(retry_response)
                    parsed["system_prompt_dropped"] = True
                    if candidate != model:
                        parsed["resolved_model_id"] = candidate
                    return parsed
                except Exception:
                    pass

            if code in {"ValidationException", "ResourceNotFoundException"} and index == 0:
                # Retry once with stripped prefix model IDs when settings use profile-like IDs.
                continue

            return {"error": _normalize_boto3_error(exc, profile)}
        except Exception as exc:
            return {"error": _normalize_boto3_error(exc, profile)}

    return {"error": "Bedrock model identifier is invalid for the current region."}


def _sync_converse_stream_with_sdk(
    model: str,
    bedrock_messages: List[Dict[str, Any]],
    system_prompt: Optional[str],
    timeout: float = 300.0,
    aws_profile: str | None = None,
    max_output_tokens: int | None = None,
    on_text_chunk: Callable[[str], None] | None = None,
) -> Dict[str, Any]:
    try:
        import boto3  # type: ignore
        from botocore.exceptions import ClientError  # type: ignore
    except Exception as exc:  # pragma: no cover - import path only
        return {
            "error": (
                "AWS SDK for Python (boto3) is required for SSO-based Bedrock auth. "
                f"Install it and retry. ({exc})"
            )
        }

    profile = _resolve_aws_profile(aws_profile)
    region = get_bedrock_region()

    connect_timeout = max(2.0, min(10.0, timeout / 4.0))
    # Keep stream open for long outputs.
    read_timeout = max(300.0, timeout)

    session = boto3.Session(profile_name=profile, region_name=region)
    client_kwargs: Dict[str, Any] = {"region_name": region}
    try:
        from botocore.config import Config  # type: ignore

        client_kwargs["config"] = Config(
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            retries={"max_attempts": 2, "mode": "standard"},
        )
    except Exception:
        pass
    client = session.client("bedrock-runtime", **client_kwargs)

    def _candidate_model_ids(base_model_id: str) -> List[str]:
        candidates = [base_model_id]
        parts = base_model_id.split(".", 1)
        if len(parts) == 2 and parts[0] in {"us", "global", "apac", "eu"}:
            stripped = parts[1]
            if stripped:
                candidates.append(stripped)
        return candidates

    def _stream_once(candidate: str, use_system_prompt: bool) -> Dict[str, Any]:
        resolved_max_tokens = _resolve_max_output_tokens(max_output_tokens)
        payload: Dict[str, Any] = {
            "modelId": candidate,
            "messages": bedrock_messages,
            "inferenceConfig": {"maxTokens": resolved_max_tokens},
        }
        if use_system_prompt and system_prompt:
            payload["system"] = [{"text": system_prompt}]

        text_parts: List[str] = []
        reasoning_parts: List[str] = []

        try:
            response = client.converse_stream(**payload)
            for event in response.get("stream", []):
                text_chunk, reasoning_chunk = _extract_text_from_stream_event(event)
                if text_chunk:
                    text_parts.append(text_chunk)
                    if on_text_chunk:
                        try:
                            on_text_chunk(text_chunk)
                        except Exception:
                            pass
                if reasoning_chunk:
                    reasoning_parts.append(reasoning_chunk)
            parsed: Dict[str, Any] = {
                "content": "".join(text_parts).strip(),
                "reasoning_details": "\n".join(reasoning_parts).strip() if reasoning_parts else None,
            }
            return parsed
        except Exception as exc:
            partial = "".join(text_parts).strip()
            if partial:
                return {
                    "content": partial,
                    "partial": True,
                    "error": _normalize_boto3_error(exc, profile),
                }
            raise

    for index, candidate in enumerate(_candidate_model_ids(model)):
        try:
            parsed = _stream_once(candidate, use_system_prompt=True)
            if candidate != model:
                parsed["resolved_model_id"] = candidate
            return parsed
        except ClientError as exc:
            error = exc.response.get("Error", {}) if isinstance(exc.response, dict) else {}
            code = error.get("Code")

            if system_prompt and code == "ValidationException":
                try:
                    parsed = _stream_once(candidate, use_system_prompt=False)
                    parsed["system_prompt_dropped"] = True
                    if candidate != model:
                        parsed["resolved_model_id"] = candidate
                    return parsed
                except Exception:
                    pass

            if code in {"ValidationException", "ResourceNotFoundException"} and index == 0:
                continue

            return {"error": _normalize_boto3_error(exc, profile)}
        except Exception as exc:
            return {"error": _normalize_boto3_error(exc, profile)}

    return {"error": "Bedrock model identifier is invalid for the current region."}


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 300.0,
    system_prompt: Optional[str] = None,
    api_key: Optional[str] = None,
    aws_profile: Optional[str] = None,
    max_output_tokens: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Query a single model via Bedrock Runtime Converse API.

    Auth strategy:
    1) AWS SDK credentials (supports AWS SSO via `aws sso login`) [default]
    2) Bearer token fallback (sleeper feature), only when token is explicitly set
       per request/session or in env.
    """
    bedrock_messages = _build_bedrock_messages(messages)

    explicit_token = (api_key or "").strip() or None
    if explicit_token:
        return await _query_model_with_bearer(
            model,
            bedrock_messages,
            timeout,
            system_prompt,
            explicit_token,
            max_output_tokens=max_output_tokens,
        )

    sdk_response = await asyncio.to_thread(
        _sync_converse_with_sdk,
        model,
        bedrock_messages,
        system_prompt,
        timeout,
        aws_profile,
        max_output_tokens,
    )
    if sdk_response.get("error"):
        fallback_token = (get_bedrock_api_key() or "").strip()
        if fallback_token:
            return await _query_model_with_bearer(
                model,
                bedrock_messages,
                timeout,
                system_prompt,
                fallback_token,
                max_output_tokens=max_output_tokens,
            )
    return sdk_response


async def query_model_stream(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 300.0,
    system_prompt: Optional[str] = None,
    api_key: Optional[str] = None,
    aws_profile: Optional[str] = None,
    max_output_tokens: Optional[int] = None,
    on_delta: Optional[Callable[[str], Awaitable[None]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Query a single model via Bedrock streaming API.
    Falls back to non-streaming in bearer-token mode.
    """
    bedrock_messages = _build_bedrock_messages(messages)
    explicit_token = (api_key or "").strip() or None

    if explicit_token:
        response = await _query_model_with_bearer(
            model,
            bedrock_messages,
            timeout,
            system_prompt,
            explicit_token,
            max_output_tokens=max_output_tokens,
        )
        if on_delta and response.get("content"):
            await on_delta(response.get("content", ""))
        return response

    # No live deltas requested, use streaming transport but return full payload.
    if on_delta is None:
        sdk_response = await asyncio.to_thread(
            _sync_converse_stream_with_sdk,
            model,
            bedrock_messages,
            system_prompt,
            timeout,
            aws_profile,
            max_output_tokens,
            None,
        )
        if sdk_response.get("error") and not sdk_response.get("content"):
            fallback_token = (get_bedrock_api_key() or "").strip()
            if fallback_token:
                return await _query_model_with_bearer(
                    model,
                    bedrock_messages,
                    timeout,
                    system_prompt,
                    fallback_token,
                    max_output_tokens=max_output_tokens,
                )
        return sdk_response

    loop = asyncio.get_running_loop()
    delta_queue: asyncio.Queue[str] = asyncio.Queue()

    def _on_text_chunk(chunk: str) -> None:
        if not chunk:
            return
        try:
            loop.call_soon_threadsafe(delta_queue.put_nowait, chunk)
        except RuntimeError:
            pass

    sdk_task = asyncio.create_task(asyncio.to_thread(
        _sync_converse_stream_with_sdk,
        model,
        bedrock_messages,
        system_prompt,
        timeout,
        aws_profile,
        max_output_tokens,
        _on_text_chunk,
    ))

    sdk_response: Optional[Dict[str, Any]] = None
    cancelled = False
    try:
        while True:
            if sdk_task.done() and delta_queue.empty():
                break
            try:
                chunk = await asyncio.wait_for(delta_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            await on_delta(chunk)
    except asyncio.CancelledError:
        cancelled = True
        sdk_task.cancel()
        raise
    if not cancelled:
        sdk_response = await sdk_task
    if sdk_response is None:
        return None

    if sdk_response.get("error") and not sdk_response.get("content"):
        fallback_token = (get_bedrock_api_key() or "").strip()
        if fallback_token:
            token_response = await _query_model_with_bearer(
                model,
                bedrock_messages,
                timeout,
                system_prompt,
                fallback_token,
                max_output_tokens=max_output_tokens,
            )
            if token_response.get("content"):
                await on_delta(token_response.get("content", ""))
            return token_response

    return sdk_response


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]],
    system_prompts: Optional[Dict[str, str]] = None,
    api_key: Optional[str] = None,
    aws_profile: Optional[str] = None,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """Query multiple models in parallel."""
    tasks = [
        query_model(
            model,
            messages,
            system_prompt=(system_prompts or {}).get(model),
            api_key=api_key,
            aws_profile=aws_profile,
        )
        for model in models
    ]
    responses = await asyncio.gather(*tasks)
    return {model: response for model, response in zip(models, responses)}


async def check_bedrock_connection(
    api_key: Optional[str] = None,
    aws_profile: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate auth readiness for Bedrock without showing token configuration in UI."""
    explicit_token = (api_key or "").strip() or None
    if explicit_token:
        return {"ok": True, "mode": "token"}

    try:
        import boto3  # type: ignore
        from botocore.exceptions import (  # type: ignore
            BotoCoreError,
            ClientError,
            CredentialRetrievalError,
            NoCredentialsError,
            PartialCredentialsError,
            UnauthorizedSSOTokenError,
        )
    except Exception as exc:
        return {
            "ok": False,
            "mode": "sdk",
            "error": (
                "AWS SDK for Python (boto3) is not installed. "
                f"Install it to use AWS SSO auth. ({exc})"
            ),
        }

    profile = _resolve_aws_profile(aws_profile)
    region = get_bedrock_region()

    def _sync_check() -> Dict[str, Any]:
        session = boto3.Session(profile_name=profile, region_name=region)

        try:
            sts = session.client("sts", region_name=region)
            identity = sts.get_caller_identity()
            return {
                "ok": True,
                "mode": "sso",
                "profile": profile,
                "region": region,
                "account": identity.get("Account", ""),
                "arn": identity.get("Arn", ""),
            }
        except UnauthorizedSSOTokenError as exc:
            return {"ok": False, "mode": "sso", "error": _normalize_boto3_error(exc, profile), "region": region, "profile": profile}
        except (NoCredentialsError, PartialCredentialsError, CredentialRetrievalError) as exc:
            return {"ok": False, "mode": "sso", "error": _normalize_boto3_error(exc, profile), "region": region, "profile": profile}
        except ClientError as exc:
            return {"ok": False, "mode": "sso", "error": _normalize_boto3_error(exc, profile), "region": region, "profile": profile}
        except BotoCoreError as exc:
            return {"ok": False, "mode": "sso", "error": _normalize_boto3_error(exc, profile), "region": region, "profile": profile}
        except Exception as exc:
            return {"ok": False, "mode": "sso", "error": _normalize_boto3_error(exc, profile), "region": region, "profile": profile}

    status = await asyncio.to_thread(_sync_check)

    fallback_token = (get_bedrock_api_key() or "").strip()
    if not status.get("ok") and fallback_token:
        return {
            "ok": True,
            "mode": "token",
            "region": region,
            "note": "Using hidden bearer-token fallback from environment.",
        }

    return status


async def validate_bedrock_model_ids(
    model_ids: List[str],
    api_key: Optional[str] = None,
    aws_profile: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Validate model IDs against live Bedrock foundation models for the current region.
    Returns invalid model IDs for fail-fast checks.
    """
    unique_models: List[str] = []
    seen = set()
    for model_id in model_ids:
        mid = (model_id or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        unique_models.append(mid)

    if not unique_models:
        return {"ok": True, "invalid_models": []}

    explicit_token = (api_key or "").strip() or None
    if explicit_token:
        # Bearer token mode cannot reliably query model catalog; skip hard validation.
        return {"ok": True, "invalid_models": [], "skipped": True, "mode": "token"}

    try:
        import boto3  # type: ignore
        from botocore.exceptions import BotoCoreError, ClientError  # type: ignore
    except Exception as exc:
        return {
            "ok": False,
            "invalid_models": [],
            "error": f"Model preflight unavailable (boto3 missing): {exc}",
            "skipped": True,
        }

    profile = _resolve_aws_profile(aws_profile)
    region = get_bedrock_region()
    cache_key = f"{profile or '_default'}::{region}"
    now = time.time()

    cached = _MODEL_LIST_CACHE.get(cache_key)
    if cached and (now - cached.get("ts", 0.0) < _MODEL_LIST_CACHE_TTL_SECONDS):
        available_models = cached.get("models", set())
    else:
        def _sync_list_models() -> Dict[str, Any]:
            connect_timeout = 5
            read_timeout = 15
            session = boto3.Session(profile_name=profile, region_name=region)
            client_kwargs: Dict[str, Any] = {"region_name": region}
            try:
                from botocore.config import Config  # type: ignore

                client_kwargs["config"] = Config(
                    connect_timeout=connect_timeout,
                    read_timeout=read_timeout,
                    retries={"max_attempts": 2, "mode": "standard"},
                )
            except Exception:
                pass

            client = session.client("bedrock", **client_kwargs)
            models: set[str] = set()
            next_token: str | None = None
            try:
                while True:
                    params: Dict[str, Any] = {"byOutputModality": "TEXT"}
                    if next_token:
                        params["nextToken"] = next_token
                    response = client.list_foundation_models(**params)
                    for summary in response.get("modelSummaries", []) or []:
                        model_id = (summary.get("modelId") or "").strip()
                        if model_id:
                            models.add(model_id)
                    next_token = response.get("nextToken")
                    if not next_token:
                        break
                return {"ok": True, "models": models}
            except ClientError as exc:
                return {"ok": False, "error": _normalize_boto3_error(exc, profile)}
            except BotoCoreError as exc:
                return {"ok": False, "error": _normalize_boto3_error(exc, profile)}
            except Exception as exc:
                return {"ok": False, "error": _normalize_boto3_error(exc, profile)}

        listed = await asyncio.to_thread(_sync_list_models)
        if not listed.get("ok"):
            return {
                "ok": False,
                "invalid_models": [],
                "error": listed.get("error", "Failed to fetch Bedrock models for validation."),
                "region": region,
                "profile": profile,
                "skipped": True,
            }

        available_models = listed.get("models", set())
        _MODEL_LIST_CACHE[cache_key] = {"ts": now, "models": available_models}

    def _candidates(model_id: str) -> List[str]:
        values = [model_id]
        parts = model_id.split(".", 1)
        if len(parts) == 2 and parts[0] in {"us", "global", "apac", "eu"}:
            stripped = parts[1]
            if stripped:
                values.append(stripped)
        return values

    invalid_models: List[str] = []
    for model_id in unique_models:
        if not any(candidate in available_models for candidate in _candidates(model_id)):
            invalid_models.append(model_id)

    return {
        "ok": len(invalid_models) == 0,
        "invalid_models": invalid_models,
        "region": region,
        "profile": profile,
        "checked_count": len(unique_models),
    }

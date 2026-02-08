"""Bedrock Runtime client for making LLM requests via Converse."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

import httpx

from .config import get_bedrock_api_key, get_bedrock_region, get_bedrock_runtime_url


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


def _aws_profile_hint() -> str:
    profile = _resolve_aws_profile()
    if profile:
        return f"aws sso login --profile {profile}"
    return "aws sso login"


def _resolve_aws_profile() -> str | None:
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


def _normalize_boto3_error(exc: Exception) -> str:
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
        f"AWS SSO session expired or invalid. Run `{_aws_profile_hint()}` and retry."
    )

    if isinstance(exc, UnauthorizedSSOTokenError):
        return relogin_help

    if isinstance(exc, (NoCredentialsError, PartialCredentialsError, CredentialRetrievalError)):
        return (
            "AWS credentials not found. Configure SSO (`aws configure sso`), "
            f"run `{_aws_profile_hint()}`, and retry."
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

    payload: Dict[str, Any] = {"messages": bedrock_messages}
    if system_prompt:
        payload["system"] = [{"text": system_prompt}]

    system_prompt_dropped = False
    try:
        try:
            data = await _post(payload)
        except httpx.HTTPStatusError as exc:
            if system_prompt and exc.response is not None and exc.response.status_code == 400:
                data = await _post({"messages": bedrock_messages})
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

    profile = _resolve_aws_profile()
    region = get_bedrock_region()

    session = boto3.Session(profile_name=profile, region_name=region)
    client = session.client("bedrock-runtime", region_name=region)

    payload: Dict[str, Any] = {
        "modelId": model,
        "messages": bedrock_messages,
    }
    if system_prompt:
        payload["system"] = [{"text": system_prompt}]

    try:
        response = client.converse(**payload)
        return _parse_converse_response(response)
    except ClientError as exc:
        error = exc.response.get("Error", {}) if isinstance(exc.response, dict) else {}
        if system_prompt and (error.get("Code") == "ValidationException"):
            retry_response = client.converse(modelId=model, messages=bedrock_messages)
            parsed = _parse_converse_response(retry_response)
            parsed["system_prompt_dropped"] = True
            return parsed
        return {"error": _normalize_boto3_error(exc)}
    except Exception as exc:
        return {"error": _normalize_boto3_error(exc)}


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 120.0,
    system_prompt: Optional[str] = None,
    api_key: Optional[str] = None,
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
        )

    sdk_response = await asyncio.to_thread(
        _sync_converse_with_sdk,
        model,
        bedrock_messages,
        system_prompt,
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
            )
    return sdk_response


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]],
    system_prompts: Optional[Dict[str, str]] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """Query multiple models in parallel."""
    tasks = [
        query_model(
            model,
            messages,
            system_prompt=(system_prompts or {}).get(model),
            api_key=api_key,
        )
        for model in models
    ]
    responses = await asyncio.gather(*tasks)
    return {model: response for model, response in zip(models, responses)}


async def check_bedrock_connection(api_key: Optional[str] = None) -> Dict[str, Any]:
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

    profile = _resolve_aws_profile()
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
            return {"ok": False, "mode": "sso", "error": _normalize_boto3_error(exc), "region": region, "profile": profile}
        except (NoCredentialsError, PartialCredentialsError, CredentialRetrievalError) as exc:
            return {"ok": False, "mode": "sso", "error": _normalize_boto3_error(exc), "region": region, "profile": profile}
        except ClientError as exc:
            return {"ok": False, "mode": "sso", "error": _normalize_boto3_error(exc), "region": region, "profile": profile}
        except BotoCoreError as exc:
            return {"ok": False, "mode": "sso", "error": _normalize_boto3_error(exc), "region": region, "profile": profile}
        except Exception as exc:
            return {"ok": False, "mode": "sso", "error": _normalize_boto3_error(exc), "region": region, "profile": profile}

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

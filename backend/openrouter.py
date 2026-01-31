"""Bedrock Runtime client for making LLM requests via Converse."""

import httpx
from typing import List, Dict, Any, Optional
from .config import get_bedrock_api_key, get_bedrock_runtime_url


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 120.0,
    system_prompt: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Query a single model via Bedrock Runtime Converse API.

    Args:
        model: Bedrock model or inference profile identifier
        messages: List of message dicts with 'role' and 'content'
        timeout: Request timeout in seconds

    Returns:
        Response dict with 'content' and optional 'reasoning_details', or None if failed
    """
    bedrock_api_key = api_key or get_bedrock_api_key()
    if not bedrock_api_key:
        print("Error: BEDROCK_API_KEY (or AWS_BEARER_TOKEN_BEDROCK) is not set.")
        return None

    headers = {
        "Authorization": f"Bearer {bedrock_api_key}",
        "Content-Type": "application/json",
    }

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

    async def _post(payload: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{get_bedrock_runtime_url()}/model/{model}/converse",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            return response.json()

    def _parse(data: Dict[str, Any]) -> Dict[str, Any]:
        message = data.get("output", {}).get("message", {})
        content_blocks = message.get("content", []) or []
        text_parts: List[str] = []
        reasoning_parts: List[str] = []

        for block in content_blocks:
            if "text" in block:
                text_parts.append(block["text"])
            elif "reasoningContent" in block:
                reasoning_text = block.get("reasoningContent", {}).get("text")
                if reasoning_text:
                    reasoning_parts.append(reasoning_text)

        return {
            "content": "\n".join(text_parts).strip(),
            "reasoning_details": "\n".join(reasoning_parts).strip() if reasoning_parts else None
        }

    payload: Dict[str, Any] = {"messages": bedrock_messages}
    if system_prompt:
        payload["system"] = [{"text": system_prompt}]

    system_prompt_dropped = False
    try:
        try:
            data = await _post(payload)
        except httpx.HTTPStatusError as exc:
            if system_prompt and exc.response is not None and exc.response.status_code == 400:
                retry_payload = {"messages": bedrock_messages}
                data = await _post(retry_payload)
                system_prompt_dropped = True
            else:
                raise
        parsed = _parse(data)
        if system_prompt_dropped:
            parsed["system_prompt_dropped"] = True
        return parsed
    except Exception as e:
        print(f"Error querying model {model}: {e}")
        return {"error": str(e)}


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]],
    system_prompts: Optional[Dict[str, str]] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Query multiple models in parallel.

    Args:
        models: List of Bedrock model or inference profile identifiers
        messages: List of message dicts to send to each model

    Returns:
        Dict mapping model identifier to response dict (or None if failed)
    """
    import asyncio

    # Create tasks for all models
    tasks = [
        query_model(
            model,
            messages,
            system_prompt=(system_prompts or {}).get(model),
            api_key=api_key,
        )
        for model in models
    ]

    # Wait for all to complete
    responses = await asyncio.gather(*tasks)

    # Map models to their responses
    return {model: response for model, response in zip(models, responses)}

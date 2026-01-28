"""Bedrock Runtime client for making LLM requests via Converse."""

import httpx
from typing import List, Dict, Any, Optional
from .config import BEDROCK_API_KEY, BEDROCK_RUNTIME_URL


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 120.0
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
    if not BEDROCK_API_KEY:
        print("Error: BEDROCK_API_KEY (or AWS_BEARER_TOKEN_BEDROCK) is not set.")
        return None

    headers = {
        "Authorization": f"Bearer {BEDROCK_API_KEY}",
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

    payload = {
        "messages": bedrock_messages,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{BEDROCK_RUNTIME_URL}/model/{model}/converse",
                headers=headers,
                json=payload
            )
            response.raise_for_status()

            data = response.json()
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

    except Exception as e:
        print(f"Error querying model {model}: {e}")
        return None


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]]
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
    tasks = [query_model(model, messages) for model in models]

    # Wait for all to complete
    responses = await asyncio.gather(*tasks)

    # Map models to their responses
    return {model: response for model, response in zip(models, responses)}

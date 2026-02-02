"""LLM Council orchestration."""

from typing import List, Dict, Any, Tuple, Callable, Awaitable
import asyncio

from .openrouter import query_model
from .council_settings import get_settings, build_default_stages, DEFAULT_STAGE2_PROMPT, DEFAULT_STAGE3_PROMPT

StageEventHandler = Callable[[Dict[str, Any]], Awaitable[None]]


def _council_config() -> Tuple[
    List[Dict[str, Any]],
    Dict[str, str],
    str,
    str,
    str,
    bool,
    bool,
]:
    """
    Returns (members, alias_map, chairman_model_id, chairman_label, title_model_id,
    use_system_prompt_stage2, use_system_prompt_stage3).
    """
    settings = get_settings()
    members = settings.get("members", [])
    alias_map = {member["model_id"]: member.get("alias", member["model_id"]) for member in members}
    use_system_prompt_stage2 = settings.get("use_system_prompt_stage2", True)
    use_system_prompt_stage3 = settings.get("use_system_prompt_stage3", True)

    chairman_id = settings.get("chairman_id")
    chairman_label = settings.get("chairman_label", "Chairman")
    title_model_id = settings.get("title_model_id", "")

    chairman_model_id = ""
    if chairman_id:
        for member in members:
            if member.get("id") == chairman_id:
                chairman_model_id = member.get("model_id", "")
                break
    if not chairman_model_id and members:
        chairman_model_id = members[0].get("model_id", "")

    return (
        members,
        alias_map,
        chairman_model_id,
        chairman_label,
        title_model_id,
        use_system_prompt_stage2,
        use_system_prompt_stage3,
    )


def _format_stage_prompt(
    stage_prompt: str | None,
    user_query: str,
    prior_context: str | None = None,
    template_values: Dict[str, str] | None = None,
) -> str:
    prompt_parts = []
    if stage_prompt:
        values = {
            "question": user_query,
            "responses": prior_context or "",
            "response_count": "0",
            "response_labels": "",
            "stage1": "",
            "stage2": "",
        }
        if template_values:
            values.update(template_values)
        return _apply_prompt_template(stage_prompt.strip(), values).strip()
    prompt_parts.append(f"User Question: {user_query}")
    if prior_context:
        prompt_parts.append("Previous Stage Outputs:\n" + prior_context)
    return "\n\n".join(prompt_parts).strip()


def _apply_prompt_template(template: str, values: Dict[str, str]) -> str:
    text = template
    for key, value in values.items():
        text = text.replace(f"{{{key}}}", value)
    return text


def _format_responses_for_context(results: List[Dict[str, Any]]) -> str:
    lines = []
    for result in results:
        if result.get("status") == "failed":
            error_detail = result.get("error", "No response received.")
            lines.append(f"Model: {result['model']}\nResponse: [FAILED]\nError: {error_detail}")
        else:
            lines.append(f"Model: {result['model']}\nResponse: {result.get('response', '')}")
    return "\n\n".join(lines)


async def _collect_stage_responses(
    members: List[Dict[str, Any]],
    user_query: str,
    stage_prompt: str | None,
    execution_mode: str,
    prior_context: str | None,
    api_key: str | None,
    prior_results: List[Dict[str, Any]] | None = None,
    responses_context: List[Dict[str, Any]] | None = None,
    rankings_context: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    response_count = len(prior_results) if prior_results else 0
    response_labels = ", ".join([
        result.get("model", "")
        for result in (prior_results or [])
        if result.get("model")
    ])
    responses_text = _format_responses_for_context(responses_context) if responses_context else ""
    rankings_text = _format_responses_for_context(rankings_context) if rankings_context else ""
    prompt_text = _format_stage_prompt(
        stage_prompt,
        user_query,
        prior_context,
        template_values={
            "responses": prior_context or "",
            "response_count": str(response_count),
            "response_labels": response_labels,
            "stage1": responses_text,
            "stage2": rankings_text,
        },
    )
    messages = [{"role": "user", "content": prompt_text}]
    tasks = []
    if execution_mode == "sequential":
        responses = []
        for member in members:
            response = await query_model(
                member["model_id"],
                messages,
                system_prompt=member.get("system_prompt", ""),
                api_key=api_key,
            )
            responses.append(response)
    else:
        tasks = [
            query_model(
                member["model_id"],
                messages,
                system_prompt=member.get("system_prompt", ""),
                api_key=api_key,
            )
            for member in members
        ]
        responses = await asyncio.gather(*tasks)

    results = []
    for member, response in zip(members, responses):
        model_id = member.get("model_id", "")
        content = response.get("content") if response else None
        if content:
            results.append({
                "model": member.get("alias", model_id),
                "response": content,
                "status": "ok",
                "system_prompt_dropped": bool(response.get("system_prompt_dropped")),
            })
        else:
            results.append({
                "model": member.get("alias", model_id),
                "response": "",
                "status": "failed",
                "error": (response or {}).get("error", "No response received."),
                "system_prompt_dropped": bool((response or {}).get("system_prompt_dropped")),
            })
    return results


async def collect_rankings(
    user_query: str,
    responses: List[Dict[str, Any]],
    api_key: str | None = None,
    stage_prompt: str | None = None,
    execution_mode: str = "parallel",
    stage_members: List[Dict[str, Any]] | None = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Each model ranks the anonymized responses.

    Args:
        user_query: The original user query
        responses: Results from the responses stage

    Returns:
        Tuple of (rankings list, label_to_model mapping)
    """
    # Only include successful responses in rankings.
    successful_results = [
        result for result in responses
        if result.get("status") != "failed" and result.get("response")
    ]

    if not successful_results:
        return [], {}

    # Create anonymized labels for responses (Response A, Response B, etc.)
    labels = [chr(65 + i) for i in range(len(successful_results))]  # A, B, C, ...

    # Create mapping from label to model name
    label_to_model = {
        f"Response {label}": result['model']
        for label, result in zip(labels, successful_results)
    }

    # Build the ranking prompt
    responses_text = "\n\n".join([
        f"Response {label}:\n{result['response']}"
        for label, result in zip(labels, successful_results)
    ])

    response_labels = [f"Response {label}" for label in labels]
    response_count = len(response_labels)

    prompt_template = stage_prompt or DEFAULT_STAGE2_PROMPT
    ranking_prompt = _apply_prompt_template(
        prompt_template,
        {
            "question": user_query,
            "responses": responses_text,
            "response_count": str(response_count),
            "response_labels": ", ".join(response_labels),
        },
    )

    messages = [{"role": "user", "content": ranking_prompt}]

    # Get rankings from all council models
    members, _, _, _, _, use_stage2_prompt, _ = _council_config()
    if stage_members is not None:
        members = stage_members
    if execution_mode == "sequential":
        responses = []
        for member in members:
            response = await query_model(
                member["model_id"],
                messages,
                system_prompt=member.get("system_prompt", "") if use_stage2_prompt else None,
                api_key=api_key,
            )
            responses.append(response)
    else:
        tasks = [
            query_model(
                member["model_id"],
                messages,
                system_prompt=member.get("system_prompt", "") if use_stage2_prompt else None,
                api_key=api_key,
            )
            for member in members
        ]
        responses = await asyncio.gather(*tasks)

    # Format results
    rankings_results = []
    for member, response in zip(members, responses):
        if response is not None and response.get('content'):
            full_text = response.get('content', '')
            parsed = parse_ranking_from_text(full_text)
            rankings_results.append({
                "model": member.get("alias", member.get("model_id", "")),
                "ranking": full_text,
                "parsed_ranking": parsed
            })

    return rankings_results, label_to_model


async def synthesize_final(
    user_query: str,
    responses: List[Dict[str, Any]],
    rankings: List[Dict[str, Any]],
    api_key: str | None = None,
    stage_prompt: str | None = None,
    stage_members: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """
    Chairman synthesizes final response.

    Args:
        user_query: The original user query
        responses: Individual model responses from the responses stage
        rankings: Rankings from the rankings stage

    Returns:
        Dict with 'model' and 'response' keys
    """
    # Build comprehensive context for chairman
    response_lines = []
    for result in responses:
        if result.get("status") == "failed":
            error_detail = result.get("error", "No response received.")
            response_lines.append(
                f"Model: {result['model']}\nResponse: [FAILED]\nError: {error_detail}"
            )
        else:
            response_lines.append(
                f"Model: {result['model']}\nResponse: {result['response']}"
            )
    responses_text = "\n\n".join(response_lines)

    rankings_text = "\n\n".join([
        f"Model: {result['model']}\nRanking: {result['ranking']}"
        for result in rankings
    ])

    prompt_template = stage_prompt or DEFAULT_STAGE3_PROMPT
    chairman_prompt = _apply_prompt_template(
        prompt_template,
        {
            "question": user_query,
            "stage1": responses_text,
            "stage2": rankings_text,
        },
    )

    messages = [{"role": "user", "content": chairman_prompt}]

    # Query the chairman model
    members, _, chairman_model_id, chairman_label, _, _, use_stage3_prompt = _council_config()
    if stage_members is not None and stage_members:
        members = stage_members
        chairman_model_id = stage_members[0].get("model_id", chairman_model_id)
        chairman_label = stage_members[0].get("alias", chairman_label)
    chairman_prompt_text = ""
    for member in members:
        if member.get("model_id") == chairman_model_id:
            chairman_prompt_text = member.get("system_prompt", "")
            break
    response = await query_model(
        chairman_model_id,
        messages,
        system_prompt=chairman_prompt_text if use_stage3_prompt else None,
        api_key=api_key,
    )

    if response is None or not response.get("content"):
        # Fallback if chairman fails
        return {
            "model": chairman_label,
            "response": "Error: Unable to generate final synthesis."
        }

    return {
        "model": chairman_label,
        "response": response.get('content', '')
    }


def parse_ranking_from_text(ranking_text: str) -> List[str]:
    """
    Parse the FINAL RANKING section from the model's response.

    Args:
        ranking_text: The full text response from the model

    Returns:
        List of response labels in ranked order
    """
    import re

    # Look for "FINAL RANKING:" section
    if "FINAL RANKING:" in ranking_text:
        # Extract everything after "FINAL RANKING:"
        parts = ranking_text.split("FINAL RANKING:")
        if len(parts) >= 2:
            ranking_section = parts[1]
            # Try to extract numbered list format (e.g., "1. Response A")
            # This pattern looks for: number, period, optional space, "Response X"
            numbered_matches = re.findall(r'\d+\.\s*Response [A-Z]', ranking_section)
            if numbered_matches:
                # Extract just the "Response X" part
                return [re.search(r'Response [A-Z]', m).group() for m in numbered_matches]

            # Fallback: Extract all "Response X" patterns in order
            matches = re.findall(r'Response [A-Z]', ranking_section)
            return matches

    # Fallback: try to find any "Response X" patterns in order
    matches = re.findall(r'Response [A-Z]', ranking_text)
    return matches


def calculate_aggregate_rankings(
    rankings_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Calculate aggregate rankings across all models.

    Args:
        rankings_results: Rankings from each model
        label_to_model: Mapping from anonymous labels to model names

    Returns:
        List of dicts with model name and average rank, sorted best to worst
    """
    from collections import defaultdict

    # Track positions for each model
    model_positions = defaultdict(list)

    for ranking in rankings_results:
        ranking_text = ranking['ranking']

        # Parse the ranking from the structured format
        parsed_ranking = parse_ranking_from_text(ranking_text)

        for position, label in enumerate(parsed_ranking, start=1):
            if label in label_to_model:
                model_name = label_to_model[label]
                model_positions[model_name].append(position)

    # Calculate average position for each model
    aggregate = []
    for model, positions in model_positions.items():
        if positions:
            avg_rank = sum(positions) / len(positions)
            aggregate.append({
                "model": model,
                "average_rank": round(avg_rank, 2),
                "rankings_count": len(positions)
            })

    # Sort by average rank (lower is better)
    aggregate.sort(key=lambda x: x['average_rank'])

    return aggregate


async def generate_conversation_title(user_query: str, api_key: str | None = None) -> str:
    """
    Generate a short title for a conversation based on the first user message.

    Args:
        user_query: The first user message

    Returns:
        A short title (3-5 words)
    """
    title_prompt = f"""Generate a very short title (3-5 words maximum) that summarizes the following question.
The title should be concise and descriptive. Do not use quotes or punctuation in the title.

Question: {user_query}

Title:"""

    messages = [{"role": "user", "content": title_prompt}]

    # Use gemini-2.5-flash for title generation (fast and cheap)
    members, _, chairman_model_id, _, title_model_id, _, _ = _council_config()
    fallback_model = chairman_model_id or (members[0]["model_id"] if members else "")
    response = await query_model(title_model_id or fallback_model, messages, timeout=30.0, api_key=api_key)

    if response is None or not response.get("content"):
        # Fallback to a generic title
        return "New Conversation"

    title = response.get('content', 'New Conversation').strip()

    # Clean up the title - remove quotes, limit length
    title = title.strip('"\'')

    # Truncate if too long
    if len(title) > 50:
        title = title[:47] + "..."

    return title


def _resolve_stage_members(
    stage: Dict[str, Any],
    members: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    member_map = {member["id"]: member for member in members}
    return [member_map[member_id] for member_id in stage.get("member_ids", []) if member_id in member_map]


def _resolve_stage_kind(stage: Dict[str, Any], index: int) -> str:
    kind = stage.get("kind")
    if kind:
        return kind
    if index == 1:
        return "rankings"
    if index == 2:
        return "synthesis"
    return "responses"


def get_final_response(stages: List[Dict[str, Any]]) -> Dict[str, Any]:
    for stage in reversed(stages):
        results = stage.get("results")
        if isinstance(results, dict) and results.get("response"):
            return results
    return {}


async def run_full_council(
    user_query: str,
    api_key: str | None = None,
    settings: Dict[str, Any] | None = None,
    on_stage_start: StageEventHandler | None = None,
    on_stage_complete: StageEventHandler | None = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Run the council pipeline using the configured stages.

    Args:
        user_query: The user's question
        settings: Optional settings snapshot to lock this run
        on_stage_start: Optional async callback before a stage runs
        on_stage_complete: Optional async callback after a stage completes

    Returns:
        Tuple of (stages_output, metadata)
    """
    settings = settings or get_settings()
    members = settings.get("members", [])
    stages_config = settings.get("stages") or build_default_stages(members, settings.get("chairman_id"))
    stages_output: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {}

    last_responses: List[Dict[str, Any]] = []
    last_rankings: List[Dict[str, Any]] = []

    for index, stage in enumerate(stages_config):
        stage_members = _resolve_stage_members(stage, members)
        stage_prompt = stage.get("prompt") or ""
        execution_mode = stage.get("execution_mode", "parallel")
        stage_kind = _resolve_stage_kind(stage, index)
        stage_entry = {
            "index": index,
            "id": stage.get("id", f"stage-{index + 1}"),
            "name": stage.get("name", f"Stage {index + 1}"),
            "prompt": stage_prompt,
            "execution_mode": execution_mode,
            "kind": stage_kind,
            "type": stage.get("type", "ai"),
        }

        if on_stage_start:
            await on_stage_start(dict(stage_entry))

        if stage_kind == "rankings":
            rankings_results, label_to_model = await collect_rankings(
                user_query,
                last_responses,
                api_key=api_key,
                stage_prompt=stage_prompt,
                execution_mode=execution_mode,
                stage_members=stage_members if stage_members else None,
            )
            aggregate_rankings = calculate_aggregate_rankings(rankings_results, label_to_model)
            metadata["label_to_model"] = label_to_model
            metadata["aggregate_rankings"] = aggregate_rankings
            stage_entry.update({
                "results": rankings_results,
                "label_to_model": label_to_model,
                "aggregate_rankings": aggregate_rankings,
            })
            last_rankings = rankings_results
        elif stage_kind == "synthesis":
            synthesis_result = await synthesize_final(
                user_query,
                last_responses,
                last_rankings,
                api_key=api_key,
                stage_prompt=stage_prompt,
                stage_members=stage_members if stage_members else None,
            )
            stage_entry.update({"results": synthesis_result})
        else:
            prior_context = _format_responses_for_context(last_responses) if last_responses else None
            responses_results = await _collect_stage_responses(
                stage_members or members,
                user_query,
                stage_prompt,
                execution_mode,
                prior_context,
                api_key,
                prior_results=last_responses,
                responses_context=last_responses,
                rankings_context=last_rankings,
            )
            last_responses = responses_results
            stage_entry.update({"results": responses_results})

        stages_output.append(stage_entry)

        if on_stage_complete:
            await on_stage_complete(dict(stage_entry))

    if not stages_output:
        return [], metadata

    if not last_responses:
        stages_output.append({
            "index": len(stages_output),
            "id": "stage-error",
            "name": "Council Error",
            "prompt": "",
            "execution_mode": "sequential",
            "kind": "synthesis",
            "type": "ai",
            "results": {
                "model": "error",
                "response": "All models failed to respond. Please try again.",
            },
        })

    return stages_output, metadata


def estimate_token_count(text: str) -> int:
    """
    Estimate token count for a given text.
    Uses a simple heuristic of ~4 characters per token.
    
    Args:
        text: The text to estimate tokens for
    
    Returns:
        Estimated token count
    """
    if not text:
        return 0
    return len(text) // 4


def _build_speaker_context(
    conversation_messages: List[Dict[str, Any]],
    settings: Dict[str, Any],
    context_level: str = "full",
) -> str:
    """
    Build context for the speaker based on context level.
    
    Args:
        conversation_messages: All messages in the conversation
        settings: Council settings snapshot
        context_level: One of 'minimal', 'standard', 'full'
    
    Returns:
        Context string for the speaker
    """
    context_parts = []
    
    # Find the first council response for stage data
    council_response = None
    for msg in conversation_messages:
        if msg.get("role") == "assistant" and msg.get("message_type") == "council":
            council_response = msg
            break
    
    if not council_response:
        return ""
    
    if context_level == "minimal":
        # Just the final synthesis
        final_result = get_final_response(council_response.get("stages") or [])
        if final_result.get("response"):
            context_parts.append(f"Council's Initial Analysis:\n{final_result.get('response')}")
    
    elif context_level == "standard":
        # Final synthesis + all user queries
        final_result = get_final_response(council_response.get("stages") or [])
        if final_result.get("response"):
            context_parts.append(f"Council's Initial Analysis:\n{final_result.get('response')}")
        
        # Add all user messages
        user_queries = []
        for msg in conversation_messages:
            if msg.get("role") == "user":
                user_queries.append(msg.get("content", ""))
        if user_queries:
            context_parts.append("User Queries:\n" + "\n---\n".join(user_queries))
    
    elif context_level == "full":
        # All stages + rankings + full conversation
        stages = council_response.get("stages") or []
        
        for stage in stages:
            stage_name = stage.get("name", "Stage")
            stage_prompt = stage.get("prompt", "")
            results = stage.get("results")
            
            stage_text = f"=== {stage_name} ==="
            if stage_prompt:
                stage_text += f"\nPrompt: {stage_prompt[:500]}..." if len(stage_prompt) > 500 else f"\nPrompt: {stage_prompt}"
            
            if isinstance(results, list):
                for result in results:
                    if isinstance(result, dict):
                        model = result.get("model", "Unknown")
                        response = result.get("response") or result.get("ranking", "")
                        stage_text += f"\n\n[{model}]:\n{response}"
            elif isinstance(results, dict):
                model = results.get("model", "Unknown")
                response = results.get("response", "")
                stage_text += f"\n\n[{model}]:\n{response}"
            
            context_parts.append(stage_text)
        
        # Add full conversation history
        conv_history = []
        for msg in conversation_messages:
            role = msg.get("role")
            if role == "user":
                conv_history.append(f"User: {msg.get('content', '')}")
            elif role == "assistant":
                if msg.get("message_type") == "speaker":
                    conv_history.append(f"Speaker: {msg.get('response', '')}")
                else:
                    # For council response, just reference it
                    conv_history.append("Assistant: [Council Analysis - see above]")
        
        if conv_history:
            context_parts.append("=== Conversation History ===\n" + "\n\n".join(conv_history))
    
    return "\n\n".join(context_parts)


async def query_council_speaker(
    user_query: str,
    conversation_messages: List[Dict[str, Any]],
    settings: Dict[str, Any],
    api_key: str | None = None,
) -> Dict[str, Any]:
    """
    Query the council speaker for a follow-up response.
    
    Args:
        user_query: The new user question
        conversation_messages: All previous messages in the conversation
        settings: Council settings (from snapshot)
        api_key: Optional API key
    
    Returns:
        Dict with 'model', 'response', and 'token_count' keys
    """
    members = settings.get("members", [])
    # Chairman always handles follow-ups (simplified from separate speaker setting)
    chairman_id = settings.get("chairman_id")
    context_level = settings.get("speaker_context_level", "full")
    
    # Find the chairman member
    chairman_member = None
    for member in members:
        if member.get("id") == chairman_id:
            chairman_member = member
            break
    
    # Fallback to first member if chairman not found
    if not chairman_member and members:
        chairman_member = members[0]
    
    if not chairman_member:
        return {
            "model": "Error",
            "response": "No council chairman configured.",
            "token_count": 0,
        }
    
    chairman_model_id = chairman_member.get("model_id", "")
    chairman_label = chairman_member.get("alias", "Chairman")
    chairman_system_prompt = chairman_member.get("system_prompt", "")
    
    # Build context based on level
    context = _build_speaker_context(conversation_messages, settings, context_level)
    
    # Create the prompt for the chairman (follow-up role)
    chairman_prompt = f"""You are the Council Chairman, continuing a conversation after the initial council analysis.

{context}

---

The user has a follow-up question. Please respond based on the council's analysis and the conversation so far.

User's Follow-up Question: {user_query}

Provide a helpful, accurate response:"""
    
    messages = [{"role": "user", "content": chairman_prompt}]
    
    try:
        response = await query_model(
            chairman_model_id,
            messages,
            system_prompt=chairman_system_prompt if chairman_system_prompt else None,
            api_key=api_key,
        )
        
        if response is None or not response.get("content"):
            return {
                "model": chairman_label,
                "response": "Error: Unable to generate response. Please try again.",
                "token_count": 0,
            }
        
        response_text = response.get("content", "")
        token_count = estimate_token_count(chairman_prompt + response_text)
        
        return {
            "model": chairman_label,
            "response": response_text,
            "token_count": token_count,
        }
    
    except Exception as e:
        error_msg = str(e)
        # Check for specific API errors
        if "expired" in error_msg.lower() or "unauthorized" in error_msg.lower():
            return {
                "model": chairman_label,
                "response": f"API Error: Token expired or unauthorized. Please refresh your API credentials.",
                "token_count": 0,
                "error": True,
            }
        elif "region" in error_msg.lower():
            return {
                "model": chairman_label,
                "response": f"API Error: Wrong region configured. Please check your Bedrock region settings.",
                "token_count": 0,
                "error": True,
            }
        else:
            return {
                "model": chairman_label,
                "response": f"Error: {error_msg}",
                "token_count": 0,
                "error": True,
            }

"""3-stage LLM Council orchestration."""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Awaitable, Callable
import asyncio
from .openrouter import query_model
from .council_settings import get_settings, build_default_stages, DEFAULT_STAGE2_PROMPT, DEFAULT_STAGE3_PROMPT


@dataclass
class CouncilRunContext:
    user_query: str
    api_key: str | None = None
    stage1_results: List[Dict[str, Any]] = field(default_factory=list)
    stage2_results: List[Dict[str, Any]] = field(default_factory=list)
    stage3_result: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineStage:
    stage_id: str
    name: str
    runner: Callable[[CouncilRunContext], Awaitable[bool]]


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


def _default_pipeline() -> List[PipelineStage]:
    return [
        PipelineStage(stage_id="stage1", name="Individual Responses", runner=_run_stage1),
        PipelineStage(stage_id="stage2", name="Peer Rankings", runner=_run_stage2),
        PipelineStage(stage_id="stage3", name="Final Synthesis", runner=_run_stage3),
    ]


def _format_stage_prompt(stage_prompt: str | None, user_query: str, prior_context: str | None = None) -> str:
    prompt_parts = []
    if stage_prompt:
        prompt_parts.append(stage_prompt.strip())
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
) -> List[Dict[str, Any]]:
    prompt_text = _format_stage_prompt(stage_prompt, user_query, prior_context)
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


async def _run_pipeline(stages: List[PipelineStage], context: CouncilRunContext) -> CouncilRunContext:
    for stage in stages:
        should_continue = await stage.runner(context)
        if not should_continue:
            break
    return context


async def _run_stage1(context: CouncilRunContext) -> bool:
    context.stage1_results = await stage1_collect_responses(context.user_query, api_key=context.api_key)
    return bool(context.stage1_results)


async def _run_stage2(context: CouncilRunContext) -> bool:
    stage2_results, label_to_model = await stage2_collect_rankings(
        context.user_query,
        context.stage1_results,
        api_key=context.api_key,
    )
    context.stage2_results = stage2_results
    context.metadata["label_to_model"] = label_to_model
    context.metadata["aggregate_rankings"] = calculate_aggregate_rankings(stage2_results, label_to_model)
    return True


async def _run_stage3(context: CouncilRunContext) -> bool:
    context.stage3_result = await stage3_synthesize_final(
        context.user_query,
        context.stage1_results,
        context.stage2_results,
        api_key=context.api_key,
    )
    return True


async def stage1_collect_responses(user_query: str, api_key: str | None = None) -> List[Dict[str, Any]]:
    """
    Stage 1: Collect individual responses from all council models.

    Args:
        user_query: The user's question

    Returns:
        List of dicts with 'model' and 'response' keys
    """
    messages = [{"role": "user", "content": user_query}]

    # Query all models in parallel
    members, _, _, _, _, _, _ = _council_config()
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

    # Format results
    stage1_results = []
    for member, response in zip(members, responses):
        model_id = member.get("model_id", "")
        content = response.get("content") if response else None
        if content:
            stage1_results.append({
                "model": member.get("alias", model_id),
                "response": content,
                "status": "ok",
                "system_prompt_dropped": bool(response.get("system_prompt_dropped")),
            })
        else:
            stage1_results.append({
                "model": member.get("alias", model_id),
                "response": "",
                "status": "failed",
                "error": (response or {}).get("error", "No response received."),
                "system_prompt_dropped": bool((response or {}).get("system_prompt_dropped")),
            })

    return stage1_results


async def stage2_collect_rankings(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    api_key: str | None = None,
    stage_prompt: str | None = None,
    execution_mode: str = "parallel",
    stage_members: List[Dict[str, Any]] | None = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Stage 2: Each model ranks the anonymized responses.

    Args:
        user_query: The original user query
        stage1_results: Results from Stage 1

    Returns:
        Tuple of (rankings list, label_to_model mapping)
    """
    # Only include successful responses in rankings.
    successful_results = [
        result for result in stage1_results
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
    stage2_results = []
    for member, response in zip(members, responses):
        if response is not None and response.get('content'):
            full_text = response.get('content', '')
            parsed = parse_ranking_from_text(full_text)
            stage2_results.append({
                "model": member.get("alias", member.get("model_id", "")),
                "ranking": full_text,
                "parsed_ranking": parsed
            })

    return stage2_results, label_to_model


async def stage3_synthesize_final(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    api_key: str | None = None,
    stage_prompt: str | None = None,
    stage_members: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """
    Stage 3: Chairman synthesizes final response.

    Args:
        user_query: The original user query
        stage1_results: Individual model responses from Stage 1
        stage2_results: Rankings from Stage 2

    Returns:
        Dict with 'model' and 'response' keys
    """
    # Build comprehensive context for chairman
    stage1_lines = []
    for result in stage1_results:
        if result.get("status") == "failed":
            error_detail = result.get("error", "No response received.")
            stage1_lines.append(
                f"Model: {result['model']}\nResponse: [FAILED]\nError: {error_detail}"
            )
        else:
            stage1_lines.append(
                f"Model: {result['model']}\nResponse: {result['response']}"
            )
    stage1_text = "\n\n".join(stage1_lines)

    stage2_text = "\n\n".join([
        f"Model: {result['model']}\nRanking: {result['ranking']}"
        for result in stage2_results
    ])

    prompt_template = stage_prompt or DEFAULT_STAGE3_PROMPT
    chairman_prompt = _apply_prompt_template(
        prompt_template,
        {
            "question": user_query,
            "stage1": stage1_text,
            "stage2": stage2_text,
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
    stage2_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Calculate aggregate rankings across all models.

    Args:
        stage2_results: Rankings from each model
        label_to_model: Mapping from anonymous labels to model names

    Returns:
        List of dicts with model name and average rank, sorted best to worst
    """
    from collections import defaultdict

    # Track positions for each model
    model_positions = defaultdict(list)

    for ranking in stage2_results:
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


async def run_full_council(
    user_query: str,
    api_key: str | None = None,
) -> Tuple[List, List, Dict, Dict, List[Dict[str, Any]]]:
    """
    Run the complete 3-stage council process.

    Args:
        user_query: The user's question

    Returns:
        Tuple of (stage1_results, stage2_results, stage3_result, metadata, stages_output)
    """
    settings = get_settings()
    members = settings.get("members", [])
    stages_config = settings.get("stages") or build_default_stages(members, settings.get("chairman_id"))
    stages_output: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {}

    stage1_results: List[Dict[str, Any]] = []
    stage2_results: List[Dict[str, Any]] = []
    stage3_result: Dict[str, Any] = {}
    last_responses: List[Dict[str, Any]] = []

    for index, stage in enumerate(stages_config):
        stage_members = _resolve_stage_members(stage, members)
        stage_prompt = stage.get("prompt") or ""
        execution_mode = stage.get("execution_mode", "parallel")
        stage_entry = {
            "id": stage.get("id", f"stage-{index + 1}"),
            "name": stage.get("name", f"Stage {index + 1}"),
            "prompt": stage_prompt,
            "execution_mode": execution_mode,
        }

        if index == 0:
            stage1_results = await _collect_stage_responses(
                stage_members,
                user_query,
                stage_prompt,
                execution_mode,
                None,
                api_key,
            )
            last_responses = stage1_results
            stage_entry.update({"kind": "responses", "results": stage1_results})
        elif index == 1:
            stage2_results, label_to_model = await stage2_collect_rankings(
                user_query,
                stage1_results,
                api_key=api_key,
                stage_prompt=stage_prompt,
                execution_mode=execution_mode,
                stage_members=stage_members,
            )
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            metadata["label_to_model"] = label_to_model
            metadata["aggregate_rankings"] = aggregate_rankings
            stage_entry.update({
                "kind": "rankings",
                "results": stage2_results,
                "label_to_model": label_to_model,
                "aggregate_rankings": aggregate_rankings,
            })
        elif index == 2:
            stage3_result = await stage3_synthesize_final(
                user_query,
                stage1_results,
                stage2_results,
                api_key=api_key,
                stage_prompt=stage_prompt,
                stage_members=stage_members,
            )
            stage_entry.update({"kind": "synthesis", "results": stage3_result})
        else:
            prior_context = _format_responses_for_context(last_responses) if last_responses else None
            stage_results = await _collect_stage_responses(
                stage_members,
                user_query,
                stage_prompt,
                execution_mode,
                prior_context,
                api_key,
            )
            last_responses = stage_results
            stage_entry.update({"kind": "responses", "results": stage_results})

        stages_output.append(stage_entry)

    if not stage1_results:
        return [], [], {
            "model": "error",
            "response": "All models failed to respond. Please try again.",
        }, {}, stages_output

    return stage1_results, stage2_results, stage3_result, metadata, stages_output

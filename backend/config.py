"""Configuration for the LLM Council."""

import os
from dotenv import load_dotenv

load_dotenv()

# Bedrock API key (or AWS_BEARER_TOKEN_BEDROCK)
_BEDROCK_API_KEY = os.getenv("BEDROCK_API_KEY") or os.getenv("AWS_BEARER_TOKEN_BEDROCK")


def get_bedrock_api_key() -> str | None:
    return _BEDROCK_API_KEY


def set_bedrock_api_key(token: str) -> None:
    global _BEDROCK_API_KEY
    _BEDROCK_API_KEY = token.strip()

# AWS region (Bedrock Runtime endpoint)
_AWS_REGION = os.getenv("AWS_REGION", "us-east-2")


def get_bedrock_region() -> str:
    return _AWS_REGION


def set_bedrock_region(region: str) -> None:
    global _AWS_REGION
    _AWS_REGION = region.strip()


def get_bedrock_runtime_url() -> str:
    return f"https://bedrock-runtime.{_AWS_REGION}.amazonaws.com"

# Converse-capable Bedrock model families (curated list).
CONVERSE_MODEL_FAMILIES = [
    {
        "family_id": "claude-opus-4-6",
        "label": "Claude Opus 4.6",
        "provider": "anthropic",
        "variants": {
            "us": "us.anthropic.claude-opus-4-6-v1",
            "global": "global.anthropic.claude-opus-4-6-v1",
        },
    },
    {
        "family_id": "claude-opus-4-5",
        "label": "Claude Opus 4.5",
        "provider": "anthropic",
        "variants": {
            "us": "us.anthropic.claude-opus-4-5-20251101-v1:0",
            "global": "global.anthropic.claude-opus-4-5-20251101-v1:0",
        },
    },
    {
        "family_id": "claude-sonnet-4-5",
        "label": "Claude Sonnet 4.5",
        "provider": "anthropic",
        "variants": {
            "us": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "global": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
        },
    },
    {
        "family_id": "claude-haiku-4-5",
        "label": "Claude Haiku 4.5",
        "provider": "anthropic",
        "variants": {
            "us": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            "global": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
        },
    },
    {
        "family_id": "claude-sonnet-3-7",
        "label": "Claude Sonnet 3.7",
        "provider": "anthropic",
        "variants": {
            "us": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            "apac": "apac.anthropic.claude-3-7-sonnet-20250219-v1:0",
        },
    },
    {
        "family_id": "llama-4-maverick",
        "label": "Llama 4 Maverick 17B Instruct",
        "provider": "meta",
        "variants": {
            "us": "us.meta.llama4-maverick-17b-instruct-v1:0",
            "global": "meta.llama4-maverick-17b-instruct-v1:0",
        },
    },
    {
        "family_id": "llama-4-scout",
        "label": "Llama 4 Scout 17B Instruct",
        "provider": "meta",
        "variants": {
            "us": "us.meta.llama4-scout-17b-instruct-v1:0",
            "global": "meta.llama4-scout-17b-instruct-v1:0",
        },
    },
    {
        "family_id": "llama-3-3-70b",
        "label": "Llama 3.3 70B Instruct",
        "provider": "meta",
        "variants": {
            "us": "us.meta.llama3-3-70b-instruct-v1:0",
            "global": "meta.llama3-3-70b-instruct-v1:0",
        },
    },
    {
        "family_id": "llama-3-2-90b",
        "label": "Llama 3.2 90B Instruct",
        "provider": "meta",
        "variants": {
            "us": "us.meta.llama3-2-90b-instruct-v1:0",
            "global": "meta.llama3-2-90b-instruct-v1:0",
        },
    },
    {
        "family_id": "llama-3-2-11b",
        "label": "Llama 3.2 11B Instruct",
        "provider": "meta",
        "variants": {
            "us": "us.meta.llama3-2-11b-instruct-v1:0",
            "global": "meta.llama3-2-11b-instruct-v1:0",
        },
    },
    {
        "family_id": "llama-3-2-3b",
        "label": "Llama 3.2 3B Instruct",
        "provider": "meta",
        "variants": {
            "us": "us.meta.llama3-2-3b-instruct-v1:0",
            "global": "meta.llama3-2-3b-instruct-v1:0",
        },
    },
    {
        "family_id": "llama-3-2-1b",
        "label": "Llama 3.2 1B Instruct",
        "provider": "meta",
        "variants": {
            "us": "us.meta.llama3-2-1b-instruct-v1:0",
            "global": "meta.llama3-2-1b-instruct-v1:0",
        },
    },
    {
        "family_id": "llama-3-1-405b",
        "label": "Llama 3.1 405B Instruct",
        "provider": "meta",
        "variants": {
            "us": "us.meta.llama3-1-405b-instruct-v1:0",
            "global": "meta.llama3-1-405b-instruct-v1:0",
        },
    },
    {
        "family_id": "llama-3-1-70b",
        "label": "Llama 3.1 70B Instruct",
        "provider": "meta",
        "variants": {
            "us": "us.meta.llama3-1-70b-instruct-v1:0",
            "global": "meta.llama3-1-70b-instruct-v1:0",
        },
    },
    {
        "family_id": "llama-3-1-8b",
        "label": "Llama 3.1 8B Instruct",
        "provider": "meta",
        "variants": {
            "us": "us.meta.llama3-1-8b-instruct-v1:0",
            "global": "meta.llama3-1-8b-instruct-v1:0",
        },
    },
    {
        "family_id": "llama-3-70b",
        "label": "Llama 3 70B Instruct",
        "provider": "meta",
        "variants": {
            "global": "meta.llama3-70b-instruct-v1:0",
        },
    },
    {
        "family_id": "llama-3-8b",
        "label": "Llama 3 8B Instruct",
        "provider": "meta",
        "variants": {
            "global": "meta.llama3-8b-instruct-v1:0",
        },
    },
    {
        "family_id": "deepseek-r1",
        "label": "DeepSeek R1",
        "provider": "deepseek",
        "variants": {
            "us": "us.deepseek.r1-v1:0",
        },
    },
    {
        "family_id": "amazon-nova-premier",
        "label": "Amazon Nova Premier",
        "provider": "amazon",
        "variants": {
            "global": "amazon.nova-premier-v1:0",
        },
    },
    {
        "family_id": "amazon-nova-pro",
        "label": "Amazon Nova Pro",
        "provider": "amazon",
        "variants": {
            "global": "amazon.nova-pro-v1:0",
        },
    },
    {
        "family_id": "amazon-nova-lite",
        "label": "Amazon Nova Lite",
        "provider": "amazon",
        "variants": {
            "global": "amazon.nova-lite-v1:0",
        },
    },
    {
        "family_id": "amazon-nova-micro",
        "label": "Amazon Nova Micro",
        "provider": "amazon",
        "variants": {
            "global": "amazon.nova-micro-v1:0",
        },
    },
    {
        "family_id": "amazon-titan-text-premier",
        "label": "Amazon Titan Text Premier",
        "provider": "amazon",
        "variants": {
            "global": "amazon.titan-text-premier-v1:0",
        },
    },
    {
        "family_id": "amazon-titan-text-express",
        "label": "Amazon Titan Text Express",
        "provider": "amazon",
        "variants": {
            "global": "amazon.titan-text-express-v1",
        },
    },
    {
        "family_id": "amazon-titan-text-lite",
        "label": "Amazon Titan Text Lite",
        "provider": "amazon",
        "variants": {
            "global": "amazon.titan-text-lite-v1",
        },
    },
]


def _region_scope(region: str) -> str:
    if region.startswith("us-"):
        return "us"
    if region.startswith("ap-"):
        return "apac"
    return "global"


def list_converse_models_for_region(region: str) -> list[dict]:
    """List models for a region, picking the best variant per family."""
    scope = _region_scope(region)
    models: list[dict] = []
    for family in CONVERSE_MODEL_FAMILIES:
        variants = family.get("variants", {})
        model_id = variants.get(scope) or variants.get("global")
        if not model_id:
            continue
        models.append(
            {
                "id": model_id,
                "label": family["label"],
                "provider": family["provider"],
                "family_id": family["family_id"],
                "variant": scope if variants.get(scope) else "global",
            }
        )
    return models


def resolve_model_for_region(model_id: str, region: str) -> str:
    """Swap model id to region-appropriate variant if available."""
    scope = _region_scope(region)
    for family in CONVERSE_MODEL_FAMILIES:
        variants = family.get("variants", {})
        if model_id in variants.values():
            return variants.get(scope) or variants.get("global") or model_id
    return model_id

# Council members - list of Bedrock model or inference profile identifiers
COUNCIL_MODELS = [
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-opus-4-6-v1",
    "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
]

# Optional display aliases (same order as COUNCIL_MODELS) for anonymity in UI
COUNCIL_ALIASES = [
    "Astraeus",
    "Phorcys",
    "Ananke",
    "Erebus",
]

# Chairman model - synthesizes final response
CHAIRMAN_MODEL = "us.anthropic.claude-opus-4-6-v1"
CHAIRMAN_ALIAS = "Chairman"

# Lightweight model for title generation
TITLE_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

# Bedrock region options for UI selection (US + APAC).
BEDROCK_REGION_OPTIONS = [
    {"code": "us-east-1", "label": "US East (N. Virginia)"},
    {"code": "us-east-2", "label": "US East (Ohio)"},
    {"code": "us-west-1", "label": "US West (N. California)"},
    {"code": "us-west-2", "label": "US West (Oregon)"},
    {"code": "ap-east-1", "label": "Asia Pacific (Hong Kong)"},
    {"code": "ap-east-2", "label": "Asia Pacific (Taipei)"},
    {"code": "ap-south-1", "label": "Asia Pacific (Mumbai)"},
    {"code": "ap-south-2", "label": "Asia Pacific (Hyderabad)"},
    {"code": "ap-northeast-1", "label": "Asia Pacific (Tokyo)"},
    {"code": "ap-northeast-2", "label": "Asia Pacific (Seoul)"},
    {"code": "ap-northeast-3", "label": "Asia Pacific (Osaka)"},
    {"code": "ap-southeast-1", "label": "Asia Pacific (Singapore)"},
    {"code": "ap-southeast-2", "label": "Asia Pacific (Sydney)"},
    {"code": "ap-southeast-3", "label": "Asia Pacific (Jakarta)"},
    {"code": "ap-southeast-4", "label": "Asia Pacific (Melbourne)"},
    {"code": "ap-southeast-5", "label": "Asia Pacific (Malaysia)"},
    {"code": "ap-southeast-6", "label": "Asia Pacific (New Zealand)"},
    {"code": "ap-southeast-7", "label": "Asia Pacific (Thailand)"},
]

# Data directory for conversation storage
DATA_DIR = "data/conversations"

# Multi-turn conversation settings
MAX_FOLLOW_UP_MESSAGES = 20  # Maximum follow-up messages per conversation (easily adjustable)
MAX_CHAT_MESSAGES = 50  # Maximum user messages for normal chat mode per conversation

# Speaker context levels - determines how much context the speaker receives for follow-ups
SPEAKER_CONTEXT_LEVELS = {
    "minimal": "Final synthesis only",
    "standard": "Synthesis + all user queries",
    "full": "All stages + rankings + full conversation",
}
DEFAULT_SPEAKER_CONTEXT_LEVEL = "full"

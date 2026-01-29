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
_AWS_REGION = os.getenv("AWS_REGION", "ap-southeast-1")


def get_bedrock_region() -> str:
    return _AWS_REGION


def set_bedrock_region(region: str) -> None:
    global _AWS_REGION
    _AWS_REGION = region.strip()


def get_bedrock_runtime_url() -> str:
    return f"https://bedrock-runtime.{_AWS_REGION}.amazonaws.com"

# Council members - list of Bedrock model or inference profile identifiers
COUNCIL_MODELS = [
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-opus-4-5-20251101-v1:0",
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
CHAIRMAN_MODEL = "us.anthropic.claude-opus-4-5-20251101-v1:0"
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

"""Configuration for the LLM Council."""

import os
from dotenv import load_dotenv

load_dotenv()

# Bedrock API key (or AWS_BEARER_TOKEN_BEDROCK)
BEDROCK_API_KEY = os.getenv("BEDROCK_API_KEY") or os.getenv("AWS_BEARER_TOKEN_BEDROCK")

# AWS region (Bedrock Runtime endpoint)
AWS_REGION = os.getenv("AWS_REGION", "ap-southeast-1")

# Council members - list of Bedrock model or inference profile identifiers
COUNCIL_MODELS = [
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-opus-4-5-20251101-v1:0",
    "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
]

# Chairman model - synthesizes final response
CHAIRMAN_MODEL = "us.anthropic.claude-opus-4-5-20251101-v1:0"

# Bedrock Runtime base endpoint
BEDROCK_RUNTIME_URL = f"https://bedrock-runtime.{AWS_REGION}.amazonaws.com"

# Data directory for conversation storage
DATA_DIR = "data/conversations"

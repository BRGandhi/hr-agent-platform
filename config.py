import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

# Database
DB_PATH = str(BASE_DIR / "hr_data.db")
ACCESS_DB_PATH = str(BASE_DIR / "access_control.db")
CONTEXT_DB_PATH = str(BASE_DIR / "context_store.db")

# LLM providers
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

DEFAULT_PROVIDER = os.getenv("DEFAULT_LLM_PROVIDER", "anthropic")
DEFAULT_MODEL = os.getenv("DEFAULT_LLM_MODEL", "claude-opus-4-6")
DEFAULT_OPENAI_COMPAT_MODEL = os.getenv("DEFAULT_OPENAI_COMPAT_MODEL", "gpt-5.2")
DEFAULT_OPENAI_COMPAT_BASE_URL = os.getenv("DEFAULT_OPENAI_COMPAT_BASE_URL", "https://api.openai.com/v1")

# Agent loop safety
MAX_AGENT_ITERATIONS = 10
SESSION_TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "120"))

# Auth gate
AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "true").lower() == "true"
DEV_SSO_ENABLED = os.getenv("DEV_SSO_ENABLED", "true").lower() == "true"
SECURE_COOKIES = os.getenv("SECURE_COOKIES", "false").lower() == "true"
SSO_PROVIDERS = [
    provider.strip()
    for provider in os.getenv("SSO_PROVIDERS", "Microsoft,Google,Okta").split(",")
    if provider.strip()
]

# Security: CORS origins (comma-separated)
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")
    if origin.strip()
]

# Security: rate limiting (per-IP)
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "40"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

# Security: LLM call timeout (seconds)
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
LLM_RATE_LIMIT_RETRIES = int(os.getenv("LLM_RATE_LIMIT_RETRIES", "2"))
LLM_RATE_LIMIT_BACKOFF_SECONDS = float(os.getenv("LLM_RATE_LIMIT_BACKOFF_SECONDS", "1.5"))

# Conversation history: max messages kept in agent loop
MAX_CONVERSATION_HISTORY = int(os.getenv("MAX_CONVERSATION_HISTORY", "40"))

# Memory retention: days to keep conversation memory; 0 disables auto-cleanup.
MEMORY_RETENTION_DAYS = int(os.getenv("MEMORY_RETENTION_DAYS", "0"))

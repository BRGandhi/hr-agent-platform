import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

# Database
DB_PATH = str(BASE_DIR / "hr_data.db")
CSV_PATH = str(Path(__file__).parent.parent / "WA_Fn-UseC_-HR-Employee-Attrition.csv")

# LLM providers
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

DEFAULT_PROVIDER = os.getenv("DEFAULT_LLM_PROVIDER", "anthropic")
DEFAULT_MODEL = os.getenv("DEFAULT_LLM_MODEL", "claude-opus-4-6")
DEFAULT_OPENAI_COMPAT_MODEL = os.getenv("DEFAULT_OPENAI_COMPAT_MODEL", "llama3.1:8b")
DEFAULT_OPENAI_COMPAT_BASE_URL = os.getenv("DEFAULT_OPENAI_COMPAT_BASE_URL", "http://localhost:11434/v1")

# Agent loop safety
MAX_AGENT_ITERATIONS = 10
SESSION_TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "120"))

# Auth gate
AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "true").lower() == "true"
DEV_SSO_ENABLED = os.getenv("DEV_SSO_ENABLED", "true").lower() == "true"
SSO_PROVIDERS = [
    provider.strip()
    for provider in os.getenv("SSO_PROVIDERS", "Microsoft,Google,Okta").split(",")
    if provider.strip()
]

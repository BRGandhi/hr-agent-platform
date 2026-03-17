import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

# Database
DB_PATH = str(BASE_DIR / "hr_data.db")
CSV_PATH = str(Path(__file__).parent.parent / "WA_Fn-UseC_-HR-Employee-Attrition.csv")

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DEFAULT_MODEL = "claude-opus-4-6"

# Agent loop safety
MAX_AGENT_ITERATIONS = 10

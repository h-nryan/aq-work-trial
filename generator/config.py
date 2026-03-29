import os

# --- Models ---
# Generator: Sonnet produces task content
GENERATOR_MODEL = "anthropic/claude-sonnet-4-5-20241022"
# Pre-filter: Haiku screens out trivially easy tasks (cheap)
PREFILTER_MODEL = "anthropic/claude-haiku-4-5-20251001"
# Evaluation target: tasks must be learnable for Opus (1-3/5 passes)
EVAL_MODEL = "anthropic/claude-opus-4-0-20250115"

# --- API ---
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
EXAMPLES_DIR = os.path.join(BASE_DIR, "examples")

# --- Generation ---
MAX_GENERATION_RETRIES = 2
LEARNABLE_MIN = 1  # minimum passes out of 5
LEARNABLE_MAX = 3  # maximum passes out of 5
EVAL_TRIALS = 5    # number of Opus runs per task

# --- Task categories for diverse generation ---
TASK_CATEGORIES = [
    "debugging",
    "data-processing",
    "system-administration",
    "software-engineering",
    "build-systems",
    "networking",
]

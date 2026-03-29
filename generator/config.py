import os

# --- Models ---
# Generator: Sonnet produces task content
GENERATOR_MODEL = "anthropic/claude-sonnet-4.5"
# Pre-filter: Haiku screens out trivially easy tasks (cheap)
PREFILTER_MODEL = "anthropic/claude-3.5-haiku"
# Evaluation target: tasks must be learnable for Opus (1-3/5 passes)
EVAL_MODEL = "anthropic/claude-opus-4"

# --- API ---
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
EXAMPLES_DIR = os.path.join(BASE_DIR, "examples")
OPUS_EXAMPLES_DIR = os.path.join(BASE_DIR, "examples-opus")

# --- Generation ---
MAX_GENERATION_RETRIES = 2
LEARNABLE_MIN = 1  # minimum passes out of 5
LEARNABLE_MAX = 3  # maximum passes out of 5
EVAL_TRIALS = 5    # number of Opus runs per task

# --- Tiered filter thresholds ---
# Tier 1: Haiku × 5 runs (cheapest)
HAIKU_FILTER_RUNS = 5
HAIKU_SKIP_THRESHOLD = 4   # skip if Haiku passes >= this many (too easy for Opus)
# Tier 2: Sonnet × 3 runs (medium cost, closer Opus proxy)
SONNET_FILTER_RUNS = 3
SONNET_SKIP_THRESHOLD = 3  # skip if Sonnet passes all 3 (too easy for Opus)
# Sonnet as middle filter model (same as generator, but used for evaluation here)
SONNET_FILTER_MODEL = GENERATOR_MODEL

# --- Task categories for diverse generation ---
TASK_CATEGORIES = [
    "debugging",
    "data-processing",
    "system-administration",
    "software-engineering",
    "build-systems",
    "networking",
]

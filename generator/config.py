import hashlib
import os
import re

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
SONNET_EXAMPLES_DIR = os.path.join(BASE_DIR, "examples-sonnet")

# --- Generation ---
MAX_GENERATION_RETRIES = 2
MAX_SOLUTION_FIRST_RETRIES = 3  # Retries 4-6 rarely succeed (bimodal: tasks pass in 1-2 or not at all)
LEARNABLE_MIN = 1  # minimum passes out of 5
LEARNABLE_MAX = 3  # maximum passes out of 5
EVAL_TRIALS = 5    # number of Opus runs per task

# --- Tiered filter thresholds ---
# Tier 1: Haiku × 5 runs (cheapest)
HAIKU_FILTER_RUNS = 5
HAIKU_SKIP_THRESHOLD = 4   # skip if Haiku passes >= this many (too easy for Opus)
# Tier 2: Sonnet × 5 runs (medium cost, closer Opus proxy)
# Increased from 3 runs to 5 for higher confidence — Sonnet 3/3 was too noisy
# (a 70% true solve rate has 34% chance of 3/3, but only 17% chance of 5/5).
SONNET_FILTER_RUNS = 5
SONNET_SKIP_THRESHOLD = 3  # skip if Sonnet passes >= 3/5 (Opus >= Sonnet, so 3/5 Sonnet ≈ too easy for Opus)
# Sonnet as middle filter model (same as generator, but used for evaluation here)
SONNET_FILTER_MODEL = GENERATOR_MODEL

# --- Slug generation ---
_SLUG_MAX_LEN = 60  # Max slug length (Docker tag limit is 128; 60 keeps dirs readable)
_SLUG_HASH_LEN = 6  # Hex chars appended when truncation is needed


def _slugify(topic: str) -> str:
    """Convert a topic string to a filesystem-safe, Docker-tag-safe slug.

    If the cleaned slug fits within _SLUG_MAX_LEN, it is returned as-is.
    Otherwise, truncate at the last word boundary (hyphen) within the
    available prefix budget and append a 6-char hex hash of the full slug.
    The hash guarantees uniqueness: two topics that share a long prefix but
    differ anywhere in their text will always produce different slugs.
    """
    full = re.sub(r"[^a-z0-9-]", "", topic.lower().replace(" ", "-"))
    full = re.sub(r"-+", "-", full).strip("-")  # collapse consecutive hyphens

    if len(full) <= _SLUG_MAX_LEN:
        return full

    # Budget: prefix + "-" + hash chars must fit in _SLUG_MAX_LEN
    prefix_budget = _SLUG_MAX_LEN - _SLUG_HASH_LEN - 1
    truncated = full[:prefix_budget]
    last_hyphen = truncated.rfind("-")
    # Only snap to word boundary if it leaves at least half the budget
    if last_hyphen >= prefix_budget // 2:
        truncated = truncated[:last_hyphen]

    suffix = hashlib.sha256(full.encode()).hexdigest()[:_SLUG_HASH_LEN]
    return f"{truncated}-{suffix}"


# --- Task categories for diverse generation ---
TASK_CATEGORIES = [
    "debugging",
    "data-processing",
    "system-administration",
    "software-engineering",
    "build-systems",
    "networking",
]

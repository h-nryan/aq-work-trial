import os

MODEL = "anthropic/claude-haiku-4-5-20251001"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples")

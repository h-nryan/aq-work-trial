"""
Task generator — generates a Terminal Bench task from a topic string.
"""

import os
import sys

from config import OUTPUT_DIR


def generate_task(topic: str, output_dir: str | None = None) -> dict:
    """Generate a Terminal Bench task for the given topic.

    A generated task should follow the standard Terminal Bench format
    (see examples/ for reference).

    Args:
        topic: A short description of the task to generate (e.g. "fix a broken Python script").
        output_dir: Where to write the generated task files. Defaults to output/<slugified-topic>.

    Returns:
        dict with task_dir and status.
    """
    slug = topic.lower().replace(" ", "-").replace("/", "-")[:60]

    if output_dir is None:
        output_dir = os.path.join(OUTPUT_DIR, slug)

    os.makedirs(output_dir, exist_ok=True)

    # TODO: implement task generation
    pass


if __name__ == "__main__":
    topic = sys.argv[1] if len(sys.argv) > 1 else "fix a broken Python script"
    result = generate_task(topic)
    if result:
        print(f"Generated task at: {result['task_dir']}")

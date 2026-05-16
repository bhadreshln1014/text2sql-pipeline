"""
Logger — structured per-question logging.

Creates a JSON log file per question that records every pipeline step.
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class QuestionLogger:
    """Structured logger for a single question's pipeline execution."""

    def __init__(self, instance_id: str, output_dir: str):
        self.instance_id = instance_id
        self.output_dir = output_dir
        self.steps: list[dict] = []
        self.start_time = time.time()

    def log_step(self, step: str, data: dict[str, Any]):
        """Log a pipeline step with its data."""
        entry = {
            "step": step,
            "timestamp": datetime.now().isoformat(),
            "elapsed_ms": int((time.time() - self.start_time) * 1000),
            **data,
        }
        self.steps.append(entry)
        logger.info(f"[{self.instance_id}] {step}: {_summarize(data)}")

    def save(self):
        """Write the complete log to a JSON file."""
        os.makedirs(self.output_dir, exist_ok=True)
        log_path = os.path.join(self.output_dir, f"{self.instance_id}_log.json")

        log_data = {
            "instance_id": self.instance_id,
            "total_elapsed_ms": int((time.time() - self.start_time) * 1000),
            "steps": self.steps,
        }

        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, default=str)

        logger.debug(f"Log saved to {log_path}")


def setup_logging(verbose: bool = True):
    """Configure logging for the pipeline."""
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Suppress noisy third-party loggers
    for noisy in ["httpcore", "httpx", "litellm", "LiteLLM", "openai", "urllib3"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _summarize(data: dict) -> str:
    """Create a brief summary string from a log data dict."""
    parts = []
    for key, value in data.items():
        if isinstance(value, str) and len(value) > 80:
            parts.append(f"{key}=({len(value)} chars)")
        elif isinstance(value, (list, dict)):
            parts.append(f"{key}=({len(value)} items)")
        else:
            parts.append(f"{key}={value}")
    return ", ".join(parts[:5])

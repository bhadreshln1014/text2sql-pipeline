"""
LLM Gateway — provider-agnostic wrapper using litellm.

Supports Gemini, Ollama, Claude, Groq — swap via config.yaml with zero code changes.
All LLM calls in the pipeline go through llm_call().
"""

import asyncio
import json
import logging
import re
from typing import Optional

import litellm

logger = logging.getLogger(__name__)

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True


class LLMConfig:
    """LLM configuration loaded from config.yaml."""

    def __init__(self, config: dict):
        self.model = config.get("model", "gemini/gemini-2.0-flash")
        self.fallback_model = config.get("fallback_model", self.model)
        self.temperature = config.get("temperature", 0)
        self.ollama_base_url = config.get("ollama_base_url", "http://localhost:11434")

    def get_api_base(self, model: str) -> Optional[str]:
        """Return api_base for Ollama models, None otherwise."""
        if model.startswith("ollama/"):
            return self.ollama_base_url
        return None


# Module-level config — set once at startup
_config: Optional[LLMConfig] = None
_total_input_tokens = 0
_total_output_tokens = 0


def init_llm(config: dict):
    """Initialize LLM config. Call once at startup."""
    global _config
    _config = LLMConfig(config)


def get_token_usage() -> dict:
    """Return cumulative token usage."""
    return {
        "total_input_tokens": _total_input_tokens,
        "total_output_tokens": _total_output_tokens,
    }


async def llm_call(
    prompt: str,
    system: str,
    model: str = None,
    temperature: float = None,
    response_format: str = "text",
    max_retries: int = 3,
) -> str:
    """
    Make an LLM call with retry, fallback, and optional JSON validation.

    Args:
        prompt: User message content.
        system: System message content.
        model: Override model (falls back to config default).
        temperature: Override temperature (falls back to config default).
        response_format: "text" or "json". If "json", validates parseable JSON.
        max_retries: Max retry attempts on transient errors.

    Returns:
        Raw string response from the LLM.
    """
    global _total_input_tokens, _total_output_tokens

    if _config is None:
        raise RuntimeError("LLM not initialized. Call init_llm(config) first.")

    model = model or _config.model
    temperature = temperature if temperature is not None else _config.temperature

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    last_error = None
    # Keep effective_max separate so we can extend it for rate-limit retries
    # without touching the caller-supplied max_retries value.
    effective_max = max_retries
    attempt = 0

    while attempt < effective_max:
        # Use fallback model only on the last attempt (and only if it differs)
        use_fallback = (attempt == effective_max - 1) and (model != _config.fallback_model)
        current_model = _config.fallback_model if use_fallback else model
        api_base = _config.get_api_base(current_model)

        try:
            kwargs = {
                "model": current_model,
                "messages": messages,
                "temperature": temperature,
            }
            if api_base:
                kwargs["api_base"] = api_base

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None, lambda: litellm.completion(**kwargs)
            )

            content = response.choices[0].message.content
            if content is None:
                raise ValueError("LLM returned a None (empty) response.")
            content = content.strip()

            # Track token usage
            usage = getattr(response, "usage", None)
            if usage:
                _total_input_tokens += getattr(usage, "prompt_tokens", 0)
                _total_output_tokens += getattr(usage, "completion_tokens", 0)

            # JSON validation if requested
            if response_format == "json":
                content = _extract_json(content)
                json.loads(content)  # Validate parseable

            logger.debug(
                f"LLM call success: model={current_model}, "
                f"tokens_in={getattr(usage, 'prompt_tokens', '?')}, "
                f"tokens_out={getattr(usage, 'completion_tokens', '?')}"
            )

            return content

        except json.JSONDecodeError as e:
            last_error = e
            logger.warning(
                f"LLM returned invalid JSON (attempt {attempt + 1}/{effective_max}): {e}"
            )
            # Add hint to prompt for retry
            messages = [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": prompt
                    + "\n\nIMPORTANT: Your previous response was not valid JSON. "
                    "Return ONLY valid JSON with no markdown formatting.",
                },
            ]
            await asyncio.sleep(1)

        except Exception as e:
            last_error = e
            error_str = str(e).lower()

            # Don't retry on bad requests — invalid model ID, decommissioned, auth errors, etc.
            is_bad_request = (
                "400" in error_str
                or "bad request" in error_str
                or "badrequesterror" in error_str
                or "not a valid model" in error_str
                or "decommissioned" in error_str
                or "invalid_request_error" in error_str
            )
            if is_bad_request:
                logger.error(f"LLM bad request (not retrying): {e}")
                break

            if any(code in error_str for code in ["429", "503", "overloaded", "rate limit", "rate_limit"]):
                match = re.search(r"try again in ([\d\.]+)s", error_str) or re.search(r"retry in ([\d\.]+)s", error_str)
                wait = float(match.group(1)) + 1.0 if match else 2 ** (attempt + 1)

                logger.warning(
                    f"LLM rate limited (attempt {attempt + 1}/{effective_max}). "
                    f"Waiting {wait:.1f}s before resuming..."
                )
                await asyncio.sleep(wait)

                # Extend ceiling for rate-limit retries (cap at 10)
                if attempt == effective_max - 1 and effective_max < 10:
                    effective_max += 1
            else:
                logger.error(f"LLM call failed (attempt {attempt + 1}/{effective_max}): {e}")
                if attempt < effective_max - 1:
                    await asyncio.sleep(1)

        attempt += 1

    raise RuntimeError(
        f"LLM call failed after {effective_max} attempts. Last error: {last_error}"
    )


def _extract_json(text: str) -> str:
    """Extract JSON from a response that might be wrapped in markdown code blocks."""
    text = text.strip()

    # Remove ```json ... ``` wrapper
    if text.startswith("```"):
        lines = text.split("\n")
        start = 0
        end = len(lines) - 1
        for i, line in enumerate(lines):
            if line.strip().startswith("```") and i == 0:
                start = 1
            elif line.strip() == "```":
                end = i
                break
        text = "\n".join(lines[start:end]).strip()

    return text

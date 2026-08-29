import json
import os
import sys
import time
from collections import deque
from threading import Lock
from typing import Any, Protocol, runtime_checkable

import jsonschema
import requests

from edgedash.config import Config, load_config


class LLMError(Exception):
    """Raised when LLM calls fail, rate limits/retries are exceeded, or JSON validation fails."""

    pass


def _clean_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start_brace = text.find("{")
    start_bracket = text.find("[")

    if start_brace != -1 or start_bracket != -1:
        if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
            end_brace = text.rfind("}")
            if end_brace != -1:
                text = text[start_brace : end_brace + 1]
        elif start_bracket != -1:
            end_bracket = text.rfind("]")
            if end_bracket != -1:
                text = text[start_bracket : end_bracket + 1]

    return text.strip()


class RateLimiter:
    def __init__(self, min_interval: float = 1.0, max_calls_per_minute: int = 15) -> None:
        self.min_interval = min_interval

        self.max_calls_per_minute = max_calls_per_minute
        self.last_call_time = 0.0
        self.call_history: deque[float] = deque()
        self._lock = Lock()

    def wait_if_needed(self) -> None:
        with self._lock:
            now = time.time()

            elapsed = now - self.last_call_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
                now = time.time()

            while self.call_history and (now - self.call_history[0]) >= 60.0:
                self.call_history.popleft()

            if len(self.call_history) >= self.max_calls_per_minute:
                oldest = self.call_history[0]
                sleep_duration = 60.0 - (now - oldest) + 0.1
                if sleep_duration > 0:
                    time.sleep(sleep_duration)
                    now = time.time()

            self.last_call_time = now
            self.call_history.append(now)


_rate_limiter = RateLimiter(min_interval=1.0, max_calls_per_minute=15)


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def generate_text(self, prompt: str, model_name: str) -> str:
        ...


PROVIDERS: dict[str, type[LLMProvider]] = {}


from typing import Any, Callable, Protocol, runtime_checkable

def register_provider(name: str) -> Callable[[type[LLMProvider]], type[LLMProvider]]:
    def decorator(cls: type[LLMProvider]) -> type[LLMProvider]:
        PROVIDERS[name.lower()] = cls
        return cls

    return decorator



@register_provider("gemini")
class GeminiProvider:
    name: str = "gemini"

    def generate_text(self, prompt: str, model_name: str) -> str:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise LLMError(
                "Missing GEMINI_API_KEY environment variable. "
                "Please set GEMINI_API_KEY=your_key in your .env file."
            )

        try:
            import google.generativeai as genai
        except ImportError as err:
            raise LLMError("google-generativeai package is not installed.") from err

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)

        last_err: Exception | None = None
        for attempt in range(3):
            try:
                _rate_limiter.wait_if_needed()
                response = model.generate_content(prompt)
                if response and hasattr(response, "text") and response.text:
                    return str(response.text)
                elif response and hasattr(response, "parts"):
                    text_parts = [p.text for p in response.parts if hasattr(p, "text") and p.text]
                    if text_parts:
                        return "".join(text_parts)
                raise LLMError("Gemini response did not contain valid text content.")
            except Exception as err:
                last_err = err
                err_str = str(err).lower()
                is_quota_or_rate = (
                    "429" in err_str
                    or "quota" in err_str
                    or "resource_exhausted" in err_str
                    or "rate" in err_str
                )
                if is_quota_or_rate and attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                if attempt < 2 and isinstance(err, (requests.RequestException, ConnectionError)):
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise LLMError(
                    f"Gemini API call failed (attempt {attempt + 1}/3): {err}"
                ) from err

        raise LLMError(f"Gemini API call failed after 3 attempts: {last_err}")


@register_provider("ollama")
class OllamaProvider:
    name: str = "ollama"

    def generate_text(self, prompt: str, model_name: str) -> str:
        url = "http://localhost:11434/api/generate"
        payload = {
            "model": model_name or "llama3",
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }

        last_err: Exception | None = None
        for attempt in range(3):
            try:
                _rate_limiter.wait_if_needed()
                res = requests.post(url, json=payload, timeout=30)
                res.raise_for_status()
                data = res.json()
                response_text = data.get("response") or ""
                if response_text:
                    return str(response_text)
                raise LLMError("Ollama response did not contain 'response' field.")
            except Exception as err:
                last_err = err
                err_str = str(err).lower()
                is_quota_or_rate = "429" in err_str or "quota" in err_str
                if is_quota_or_rate and attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                if attempt < 2 and isinstance(err, requests.RequestException):
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise LLMError(
                    f"Ollama API call failed (attempt {attempt + 1}/3): {err}"
                ) from err

        raise LLMError(f"Ollama call failed after 3 attempts: {last_err}")


def complete_json(
    prompt: str,
    schema: dict[str, Any],
    *,
    max_retries: int = 1,
    config: Config | None = None,
) -> dict[str, Any]:
    if config is None:
        config = load_config()

    provider_name = config.llm_provider.lower()
    model_name = config.llm_model

    if provider_name not in PROVIDERS:
        raise LLMError(
            f"Unsupported LLM provider '{provider_name}'. Supported providers: {list(PROVIDERS.keys())}"
        )

    provider_cls = PROVIDERS[provider_name]
    provider_inst = provider_cls()

    schema_str = json.dumps(schema, indent=2)
    full_prompt = (
        f"{prompt}\n\n"
        f"CRITICAL REQUIREMENT: Respond ONLY with valid JSON conforming to this JSON Schema:\n"
        f"{schema_str}\n\n"
        f"Do NOT include markdown formatting, code fences (like ```json), or any conversational text before or after the JSON."
    )

    current_prompt = full_prompt
    last_validation_error: str = ""

    for attempt in range(max_retries + 1):
        if attempt > 0:
            current_prompt = (
                f"{full_prompt}\n\n"
                f"PREVIOUS ATTEMPT FAILED VALIDATION:\n"
                f"{last_validation_error}\n"
                f"Please fix the error and reply with valid JSON ONLY conforming to the schema. No markdown fences, no extra text."
            )

        raw_text = provider_inst.generate_text(current_prompt, model_name)
        cleaned_text = _clean_json_text(raw_text)

        try:
            parsed_data = json.loads(cleaned_text)
        except json.JSONDecodeError as err:
            last_validation_error = (
                f"JSON parsing failed: {err}. Output received: '{cleaned_text[:200]}'"
            )
            if attempt < max_retries:
                continue
            raise LLMError(
                f"Failed to parse model response as JSON: {last_validation_error}"
            ) from err

        try:
            jsonschema.validate(instance=parsed_data, schema=schema)
            return parsed_data
        except jsonschema.ValidationError as err:
            last_validation_error = (
                f"JSON Schema validation error: {err.message} at path {list(err.path)}"
            )
            if attempt < max_retries:
                continue
            raise LLMError(
                f"Model response failed schema validation after {max_retries + 1} attempts: {last_validation_error}"
            ) from err

    raise LLMError(f"LLM completion failed: {last_validation_error}")


def main() -> None:
    if "--check" in sys.argv or "-c" in sys.argv:
        cfg = load_config()
        print("\n" + "=" * 70)
        print(" EDGEDASH LLM PROVIDER CHECK".center(70))
        print("=" * 70)
        print(f"  * Provider : {cfg.llm_provider}")
        print(f"  * Model    : {cfg.llm_model}")

        test_schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["status", "message"],
        }

        try:
            result = complete_json(
                prompt="Respond with a JSON object containing status 'ok' and message 'LLM check successful'.",
                schema=test_schema,
                config=cfg,
            )
            print("  * Status   : SUCCESS")
            print(f"  * Result   : {result}")
        except Exception as err:
            print("  * Status   : FAILED")
            print(f"  * Error    : {err}")
        print("=" * 70 + "\n")


if __name__ == "__main__":
    main()

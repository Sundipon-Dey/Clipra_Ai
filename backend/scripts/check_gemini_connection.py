"""Make one minimal text-only request to check configured Gemini access."""

from __future__ import annotations

import re
import logging
import time
from pathlib import Path

from dotenv import dotenv_values
from google import genai
from google.genai import errors, types


BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_DIR / ".env"
TEST_PROMPT = "Reply with exactly: CLIPRA API TEST SUCCESS"
EXPECTED_TEXT = "CLIPRA API TEST SUCCESS"


def safe_message(value: object, api_key: str) -> str:
    message = str(value).replace(api_key, "[redacted]") if api_key else str(value)
    message = re.sub(r"(?i)(x-goog-api-key|api[_ -]?key|authorization)\s*[:=]\s*\S+", r"\1=[redacted]", message)
    message = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[redacted]", message)
    return " ".join(message.split())[:500]


def main() -> int:
    config = dotenv_values(ENV_FILE)
    api_key = (config.get("GEMINI_API_KEY") or "").strip()
    model = (config.get("GEMINI_MODEL") or "").strip()
    if not api_key:
        print("status=not_configured; GEMINI_API_KEY is missing from backend/.env")
        return 2
    if not model:
        print("status=not_configured; GEMINI_MODEL is missing from backend/.env")
        return 2
    client = None
    safe_model = safe_message(model, api_key)
    print(f"configured_model={safe_model}")
    response_metadata: dict[str, str | int] = {}
    request_id_headers = (
        "x-goog-request-id",
        "x-request-id",
        "request-id",
        "x-cloud-trace-context",
        "traceparent",
    )

    def capture_response(response) -> None:
        response_metadata["http_status"] = response.status_code
        for header in request_id_headers:
            value = response.headers.get(header)
            if value:
                response_metadata[header] = safe_message(value, api_key)

    try:
        # Prevent SDK or transport debug logging from writing request details.
        logging.disable(logging.CRITICAL)
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=60_000,
                retry_options=types.HttpRetryOptions(attempts=1),
                client_args={"event_hooks": {"response": [capture_response]}},
            ),
        )
        request_started = time.perf_counter()
        response = client.models.generate_content(
            model=model,
            contents=TEST_PROMPT,
            config=types.GenerateContentConfig(temperature=0, max_output_tokens=20),
        )
        elapsed_seconds = time.perf_counter() - request_started
        returned_text = getattr(response, "text", None) if response is not None else None
        print(f"http_status={response_metadata.get('http_status', 'unknown')}")
        print(f"elapsed_seconds={elapsed_seconds:.3f}")
        for header in request_id_headers:
            if header in response_metadata:
                print(f"{header}={response_metadata[header]}")
        if returned_text is None:
            print(f"status=FAIL; model={safe_model}; error=empty response")
            return 1
        safe_text = safe_message(returned_text, api_key)
        print(f"returned_text={safe_text}")
        passed = returned_text.strip() == EXPECTED_TEXT
        print(f"status={'PASS' if passed else 'FAIL'}; model={safe_model}; video_uploaded=no")
        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            prompt_tokens = getattr(usage, "prompt_token_count", None)
            output_tokens = getattr(usage, "candidates_token_count", None)
            if prompt_tokens is not None or output_tokens is not None:
                print(f"usage_prompt_tokens={prompt_tokens}; usage_output_tokens={output_tokens}")
        return 0
    except errors.APIError as error:
        code = getattr(error, "code", "unknown")
        message = safe_message(getattr(error, "message", "Gemini API request failed."), api_key)
        elapsed = time.perf_counter() - request_started if "request_started" in locals() else 0.0
        print(f"http_status={response_metadata.get('http_status', code)}")
        print(f"elapsed_seconds={elapsed:.3f}")
        for header in request_id_headers:
            if header in response_metadata:
                print(f"{header}={response_metadata[header]}")
        print(f"status=FAIL; model={safe_model}; error={message}")
        return 1
    except KeyboardInterrupt:
        print("status=interrupted; request did not return a result")
        return 1
    except BaseException as error:
        message = safe_message(error, api_key)
        elapsed = time.perf_counter() - request_started if "request_started" in locals() else 0.0
        if "request_started" in locals():
            print(f"http_status={response_metadata.get('http_status', 'unknown')}")
            print(f"elapsed_seconds={elapsed:.3f}")
            for header in request_id_headers:
                if header in response_metadata:
                    print(f"{header}={response_metadata[header]}")
        print(f"status=FAIL; model={safe_model}; error_type={type(error).__name__}; error={message}")
        return 1
    finally:
        if client is not None:
            try:
                client.close()
            except BaseException as error:
                message = safe_message(error, api_key)
                print(f"status=cleanup_warning; error_type={type(error).__name__}; error={message}")


if __name__ == "__main__":
    raise SystemExit(main())

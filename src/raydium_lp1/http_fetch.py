"""Resilient JSON GET for public Raydium API reads (retries transient network/SSL faults)."""

from __future__ import annotations

import json
import ssl
import time
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from raydium_lp1.http_json import load_json_from_urlopen_response

DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)


def _is_retryable_http(exc: HTTPError) -> bool:
    return exc.code in (408, 429, 500, 502, 503, 504)


def fetch_json_get(
    url: str,
    *,
    timeout: int,
    headers: dict[str, str],
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    backoff_seconds: Sequence[float] = DEFAULT_BACKOFF_SECONDS,
) -> dict[str, Any]:
    """GET *url* and parse JSON; retry transient failures between attempts."""

    attempts = max(1, max_attempts)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                payload = load_json_from_urlopen_response(response)
            if not isinstance(payload, dict):
                raise RuntimeError(f"API returned non-object JSON for {url}")
            return payload
        except HTTPError as exc:
            last_error = exc
            if not _is_retryable_http(exc) or attempt >= attempts:
                raise RuntimeError(f"API returned HTTP {exc.code} for {url}") from exc
        except URLError as exc:
            last_error = exc
            if attempt >= attempts:
                reason = getattr(exc, "reason", exc)
                raise RuntimeError(f"API request failed for {url}: {reason}") from exc
        except TimeoutError as exc:
            last_error = exc
            if attempt >= attempts:
                raise RuntimeError(f"API request timed out after {timeout}s for {url}") from exc
        except json.JSONDecodeError as exc:
            last_error = exc
            if attempt >= attempts:
                raise RuntimeError(f"API returned invalid JSON for {url}: {exc}") from exc
        except (OSError, ssl.SSLError) as exc:
            last_error = exc
            if attempt >= attempts:
                raise RuntimeError(f"API read failed for {url}: {exc}") from exc

        if attempt < attempts:
            pause = backoff_seconds[min(attempt - 1, len(backoff_seconds) - 1)]
            time.sleep(pause)

    raise RuntimeError(f"API request failed for {url}: {last_error}")

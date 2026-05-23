"""Decode JSON from urllib responses; some RPCs/CDNs return gzip bodies unchanged."""

from __future__ import annotations

import gzip
import json
from typing import Any


def json_loads_from_http_body(raw: bytes, *, content_encoding: str | None = None) -> Any:
    """Parse JSON from raw HTTP body bytes; decompress gzip when magic or header says gzip."""

    if not raw:
        raise json.JSONDecodeError("empty body", "", 0)
    data = raw
    ce = (content_encoding or "").lower()
    if data.startswith(b"\x1f\x8b"):
        data = gzip.decompress(data)
    elif "gzip" in ce:
        try:
            data = gzip.decompress(data)
        except OSError:
            pass
    return json.loads(data.decode("utf-8"))


def load_json_from_urlopen_response(resp: Any) -> Any:
    """Read a urllib ``HTTPResponse`` and return parsed JSON (handles gzip)."""

    raw = resp.read()
    ce = resp.headers.get("Content-Encoding") if hasattr(resp, "headers") else None
    return json_loads_from_http_body(raw, content_encoding=ce)

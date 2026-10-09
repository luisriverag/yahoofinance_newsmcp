"""Shared redaction for errors and structured values crossing public boundaries.

Mirrors the redaction module used by the sibling MCP servers (torrent_mcp,
homebox_mcp): any error the model or a log line may see is scrubbed of URL
credentials and known secret query parameters before it leaves this process.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "[REDACTED]"
_SECRET_FIELDS = {
    "apikey",
    "api_key",
    "key",
    "token",
    "access_token",
    "password",
    "passkey",
    "authorization",
    "cookie",
}
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def _is_secret_field(name: str) -> bool:
    return name.strip().lower() in _SECRET_FIELDS


def redact_url(url: str) -> str:
    """Remove URL credentials and redact known secret query parameters."""

    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if parts.port is not None:
            host = f"{host}:{parts.port}"
        query = urlencode(
            [
                (name, REDACTED if _is_secret_field(name) else value)
                for name, value in parse_qsl(parts.query, keep_blank_values=True)
            ]
        )
        return urlunsplit((parts.scheme, host, parts.path, query, parts.fragment))
    except (TypeError, ValueError):
        without_userinfo = re.sub(r"(?i)(https?://)[^/@\s]+@", r"\1", str(url))
        names = "|".join(
            re.escape(name) for name in sorted(_SECRET_FIELDS, key=len, reverse=True)
        )
        return re.sub(
            rf"(?i)([?&](?:{names})=)[^&#\s]+", rf"\1{REDACTED}", without_userinfo
        )


def redact_text(text: str) -> str:
    """Redact URLs and common ``secret=value`` fragments in free-form text."""

    redacted = _URL_RE.sub(lambda match: redact_url(match.group(0)), str(text))
    names = "|".join(re.escape(name) for name in sorted(_SECRET_FIELDS, key=len, reverse=True))
    return re.sub(
        rf"(?i)\b({names})\b(\s*[:=]\s*)([^\s,;&]+)",
        rf"\1\2{REDACTED}",
        redacted,
    )


def redact_value(value: Any) -> Any:
    """Recursively redact secret fields and URLs in JSON-like values."""

    if isinstance(value, Mapping):
        return {
            key: REDACTED if _is_secret_field(str(key)) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value

#!/usr/bin/env python3
"""Remove channel credentials from a Conda explicit manifest stream."""

from __future__ import annotations

import re
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_HEX_FRAGMENT = re.compile(r"^(?:[0-9a-f]{32}|[0-9a-f]{64})$")
_REDACTED = "REDACTED"


def sanitize_explicit_line(line: str) -> str:
    """Preserve package identity while redacting URL-carried credentials."""

    stripped = line.rstrip("\n")
    if not stripped or stripped.startswith("#") or stripped == "@EXPLICIT":
        return stripped
    parsed = urlsplit(stripped)
    if parsed.scheme not in {"http", "https", "file"}:
        raise ValueError("Conda explicit manifest contains an unsupported entry")
    if parsed.scheme in {"http", "https"} and parsed.hostname is None:
        raise ValueError("Conda explicit manifest contains a malformed package URL")

    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname + (f":{parsed.port}" if parsed.port is not None else "")
    components = parsed.path.split("/")
    for index, component in enumerate(components[:-1]):
        if component.lower() in {"t", "token"} and components[index + 1]:
            components[index + 1] = _REDACTED
    path = "/".join(components)
    query = urlencode([(key, _REDACTED if value else "") for key, value in parse_qsl(parsed.query)])
    fragment = parsed.fragment if _HEX_FRAGMENT.fullmatch(parsed.fragment) else ""
    return urlunsplit((parsed.scheme, netloc, path, query, fragment))


def main() -> int:
    for line in sys.stdin:
        print(sanitize_explicit_line(line))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Small JSON Lines logger with run context and secret redaction."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from verigym.core.redaction import redact_mapping


def append_json_log(
    path: Path,
    *,
    event: str,
    run_id: str,
    task_id: str,
    level: str = "info",
    **fields: Any,
) -> None:
    """Append one bounded orchestration record without serializing known secrets."""

    payload: dict[str, Any] = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "level": level,
        "event": event,
        "run_id": run_id,
        "task_id": task_id,
    }
    payload.update(redact_mapping(fields))
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True, default=str) + "\n")

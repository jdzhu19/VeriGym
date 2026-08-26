"""Frozen constants for one broker-authoritative OpenHands format recovery."""

from __future__ import annotations

import hashlib

OPENHANDS_FORMAT_RECOVERY_POLICY = "openhands_broker_stop_hook_recovery_v1"
OPENHANDS_FORMAT_RECOVERY_BUDGET = 1
OPENHANDS_STOP_HOOK_PREFIX = "[Stop hook feedback]"
OPENHANDS_FORMAT_RECOVERY_REASON = (
    "Your previous response did not call a tool. Continue in this same session with exactly "
    "one typed tool call and no prose. If the task is complete, call finish."
)
OPENHANDS_FORMAT_RECOVERY_MESSAGE = (
    f"{OPENHANDS_STOP_HOOK_PREFIX} {OPENHANDS_FORMAT_RECOVERY_REASON}"
)
OPENHANDS_FORMAT_RECOVERY_REASON_SHA256 = hashlib.sha256(
    OPENHANDS_FORMAT_RECOVERY_REASON.encode()
).hexdigest()
OPENHANDS_FORMAT_RECOVERY_MESSAGE_SHA256 = hashlib.sha256(
    OPENHANDS_FORMAT_RECOVERY_MESSAGE.encode()
).hexdigest()

__all__ = [
    "OPENHANDS_FORMAT_RECOVERY_BUDGET",
    "OPENHANDS_FORMAT_RECOVERY_MESSAGE",
    "OPENHANDS_FORMAT_RECOVERY_MESSAGE_SHA256",
    "OPENHANDS_FORMAT_RECOVERY_POLICY",
    "OPENHANDS_FORMAT_RECOVERY_REASON",
    "OPENHANDS_FORMAT_RECOVERY_REASON_SHA256",
    "OPENHANDS_STOP_HOOK_PREFIX",
]

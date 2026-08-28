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
OPENHANDS_SDK_STOP_CONTINUATION_POLICY = "openhands_sdk_blocked_stop_continuation_v1"
OPENHANDS_SDK_STOP_CONTINUATION_BUDGET = 1
OPENHANDS_SDK_STOP_CONTINUATION_MESSAGE = (
    "[Adapter continuation] Continue from the Stop hook feedback already present above with "
    "exactly one typed tool call and no prose."
)
OPENHANDS_SDK_STOP_CONTINUATION_MESSAGE_SHA256 = hashlib.sha256(
    OPENHANDS_SDK_STOP_CONTINUATION_MESSAGE.encode()
).hexdigest()
OPENHANDS_PATH_POLICY_RECOVERY_POLICY = "openhands_provider_path_policy_recovery_v1"
OPENHANDS_PATH_POLICY_RECOVERY_BUDGET = 1
OPENHANDS_PATH_POLICY_RECOVERY_MESSAGE = (
    "[Adapter path-policy feedback] The previous provider response was rejected before tool "
    "dispatch because one argument contained a host absolute path. Continue in this same "
    "session with exactly one typed tool call and no prose. Use only '.' or workspace-relative "
    "POSIX repository paths in every path, cwd, shell command, patch header, and summary. Do not "
    "mention, reconstruct, or reuse the rejected path."
)
OPENHANDS_PATH_POLICY_RECOVERY_MESSAGE_SHA256 = hashlib.sha256(
    OPENHANDS_PATH_POLICY_RECOVERY_MESSAGE.encode()
).hexdigest()
OPENHANDS_FORMAT_RECOVERY_EXHAUSTED_REASON = "format recovery budget exhausted"
OPENHANDS_FORMAT_RECOVERY_EXHAUSTED_REASON_SHA256 = hashlib.sha256(
    OPENHANDS_FORMAT_RECOVERY_EXHAUSTED_REASON.encode()
).hexdigest()

__all__ = [
    "OPENHANDS_FORMAT_RECOVERY_BUDGET",
    "OPENHANDS_FORMAT_RECOVERY_MESSAGE",
    "OPENHANDS_FORMAT_RECOVERY_MESSAGE_SHA256",
    "OPENHANDS_FORMAT_RECOVERY_POLICY",
    "OPENHANDS_FORMAT_RECOVERY_REASON",
    "OPENHANDS_FORMAT_RECOVERY_REASON_SHA256",
    "OPENHANDS_STOP_HOOK_PREFIX",
    "OPENHANDS_FORMAT_RECOVERY_EXHAUSTED_REASON",
    "OPENHANDS_FORMAT_RECOVERY_EXHAUSTED_REASON_SHA256",
    "OPENHANDS_SDK_STOP_CONTINUATION_BUDGET",
    "OPENHANDS_SDK_STOP_CONTINUATION_MESSAGE",
    "OPENHANDS_SDK_STOP_CONTINUATION_MESSAGE_SHA256",
    "OPENHANDS_SDK_STOP_CONTINUATION_POLICY",
    "OPENHANDS_PATH_POLICY_RECOVERY_BUDGET",
    "OPENHANDS_PATH_POLICY_RECOVERY_MESSAGE",
    "OPENHANDS_PATH_POLICY_RECOVERY_MESSAGE_SHA256",
    "OPENHANDS_PATH_POLICY_RECOVERY_POLICY",
]

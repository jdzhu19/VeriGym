#!/usr/bin/env python3
"""Run the frozen OpenHands v17 canary v4 without retries."""

from __future__ import annotations

import importlib
import json

from verigym_openhands import hwe_v17_canary_v4 as _policy

_runner = importlib.import_module(
    "scripts.collect_cva6_hwe_openhands_v17_canary_v3"
    if __package__
    else "collect_cva6_hwe_openhands_v17_canary_v3"
)

_POLICY_EXPORTS = (
    "OPENHANDS_V17_CANARY_AGENT_VERSION_ID",
    "OPENHANDS_V17_CANARY_API_KEY_ENV",
    "OPENHANDS_V17_CANARY_BASE_URL_ENV",
    "OPENHANDS_V17_CANARY_CAMPAIGN_ID",
    "OPENHANDS_V17_CANARY_GATE_FORMAT",
    "OPENHANDS_V17_CANARY_LITELLM_VERSION",
    "OPENHANDS_V17_CANARY_MODEL",
    "OPENHANDS_V17_CANARY_MODEL_IDENTITY",
    "OPENHANDS_V17_CANARY_OPT_IN_ENV",
    "OPENHANDS_V17_CANARY_REPORT_FORMAT",
    "OPENHANDS_V17_CANARY_SDK_VERSION",
    "OPENHANDS_V17_CANARY_TASKS",
    "OPENHANDS_V17_CANARY_TIKTOKEN_VERSION",
    "OPENHANDS_V17_CANARY_TOOL_CHOICE_POLICY",
    "build_v17_canary_agent_options",
    "build_v17_canary_agent_version",
    "derive_v17_v3_task_split",
    "evaluate_v17_canary_gate",
    "load_v17_canary_contract",
    "seal_v17_canary_report",
    "validate_v17_canary_source",
    "validate_v17_runtime_evidence",
)


def _install_v4_policy() -> None:
    """Bind the reviewed generic v3 runner body to the independent v4 policy module."""

    for name in _POLICY_EXPORTS:
        setattr(_runner, name, getattr(_policy, name))


def main() -> int:
    _install_v4_policy()
    report = _runner.collect(_runner._parser().parse_args())
    print(
        json.dumps(
            {
                "status": report["status"],
                "canary_passed": report["canary_passed"],
                "formal_collection_allowed": report["formal_collection_allowed"],
                "gate_failure_reason": report["gate_failure_reason"],
                "report_hash": report["report_hash"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["formal_collection_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

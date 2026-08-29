#!/usr/bin/env python3
"""Run the frozen two-task OpenHands v18 repaired-validator canary without retries."""

from __future__ import annotations

import importlib
import json

from verigym_openhands import hwe_v18_repair_canary as _policy

_runner = importlib.import_module(
    "scripts.collect_cva6_hwe_openhands_v17_canary_v3"
    if __package__
    else "collect_cva6_hwe_openhands_v17_canary_v3"
)

_POLICY_EXPORTS = {
    "OPENHANDS_V17_CANARY_AGENT_VERSION_ID": ("OPENHANDS_V18_REPAIR_CANARY_AGENT_VERSION_ID"),
    "OPENHANDS_V17_CANARY_API_KEY_ENV": "OPENHANDS_V18_REPAIR_CANARY_API_KEY_ENV",
    "OPENHANDS_V17_CANARY_BASE_URL_ENV": "OPENHANDS_V18_REPAIR_CANARY_BASE_URL_ENV",
    "OPENHANDS_V17_CANARY_CAMPAIGN_ID": "OPENHANDS_V18_REPAIR_CANARY_CAMPAIGN_ID",
    "OPENHANDS_V17_CANARY_GATE_FORMAT": "OPENHANDS_V18_REPAIR_CANARY_GATE_FORMAT",
    "OPENHANDS_V17_CANARY_IMAGE_LOCK_RECEIPT_FORMAT": (
        "OPENHANDS_V18_REPAIR_CANARY_IMAGE_LOCK_RECEIPT_FORMAT"
    ),
    "OPENHANDS_V17_CANARY_LITELLM_VERSION": "OPENHANDS_V18_REPAIR_CANARY_LITELLM_VERSION",
    "OPENHANDS_V17_CANARY_MODEL": "OPENHANDS_V18_REPAIR_CANARY_MODEL",
    "OPENHANDS_V17_CANARY_MODEL_IDENTITY": "OPENHANDS_V18_REPAIR_CANARY_MODEL_IDENTITY",
    "OPENHANDS_V17_CANARY_OPT_IN_ENV": "OPENHANDS_V18_REPAIR_CANARY_OPT_IN_ENV",
    "OPENHANDS_V17_CANARY_PREFLIGHT_PREFIX": "OPENHANDS_V18_REPAIR_CANARY_PREFLIGHT_PREFIX",
    "OPENHANDS_V17_CANARY_REPORT_FORMAT": "OPENHANDS_V18_REPAIR_CANARY_REPORT_FORMAT",
    "OPENHANDS_V17_CANARY_SDK_VERSION": "OPENHANDS_V18_REPAIR_CANARY_SDK_VERSION",
    "OPENHANDS_V17_CANARY_SECURITY_REPORT_PREFIX": (
        "OPENHANDS_V18_REPAIR_CANARY_SECURITY_REPORT_PREFIX"
    ),
    "OPENHANDS_V17_CANARY_TASKS": "OPENHANDS_V18_REPAIR_CANARY_TASKS",
    "OPENHANDS_V17_CANARY_TIKTOKEN_VERSION": "OPENHANDS_V18_REPAIR_CANARY_TIKTOKEN_VERSION",
    "OPENHANDS_V17_CANARY_TOOL_CHOICE_POLICY": ("OPENHANDS_V18_REPAIR_CANARY_TOOL_CHOICE_POLICY"),
    "build_v17_canary_agent_options": "build_v18_repair_canary_agent_options",
    "build_v17_canary_agent_version": "build_v18_repair_canary_agent_version",
    "derive_v17_v3_task_split": "derive_v18_repair_task_split",
    "evaluate_v17_canary_gate": "evaluate_v18_repair_canary_gate",
    "load_v17_canary_contract": "load_v18_repair_canary_contract",
    "seal_v17_canary_report": "seal_v18_repair_canary_report",
    "validate_v17_canary_source": "validate_v18_repair_canary_source",
    "validate_v17_runtime_evidence": "validate_v18_repair_runtime_evidence",
}


def _install_v18_policy() -> None:
    """Bind the reviewed runner body to the independent v18 policy module."""

    for runner_name, policy_name in _POLICY_EXPORTS.items():
        setattr(_runner, runner_name, getattr(_policy, policy_name))


def main() -> int:
    _install_v18_policy()
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

"""Provider-neutral HWE native-shell v2 evaluation contract for future rLLM runs.

The bridge deliberately stops at a zero-call conformance object.  A later evaluator may inject
an rLLM-compatible runner, but constructing this contract never starts a model, contacts a
provider, or invokes a verifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from verigym.core.hashing import content_hash
from verigym.hwe.profiles import (
    HWE_COLLECTION_PROFILE_V2_ID,
    HWE_TOOL_CONTRACT_V2_ID,
    hwe_tool_contract_hash,
    hwe_tool_definitions,
)

HWE_RLLM_BRIDGE_FORMAT = "verigym_hwe_native_shell_v2_rllm_eval_bridge_v1"
HWE_NATIVE_SHELL_TOOL_NAMES = (
    "list_files",
    "read_file",
    "apply_patch",
    "shell",
    "inspect_diff",
    "finish",
)


@dataclass(frozen=True)
class HweNativeShellV2RllmEvalBridge:
    """A hash-bound, zero-call description of the HWE evaluator boundary."""

    format_id: str
    provider_neutral: bool
    profile_id: str
    tool_contract_id: str
    tool_contract_hash: str
    tool_names: tuple[str, ...]
    verifier_binding: str
    security_boundary: dict[str, Any]
    call_count: int = 0
    bridge_hash: str = ""

    def __post_init__(self) -> None:
        if self.format_id != HWE_RLLM_BRIDGE_FORMAT or not self.provider_neutral:
            raise ValueError("HWE rLLM bridge identity is not provider-neutral")
        if self.profile_id != HWE_COLLECTION_PROFILE_V2_ID:
            raise ValueError("HWE rLLM bridge requires native-shell v2")
        if self.tool_contract_id != HWE_TOOL_CONTRACT_V2_ID:
            raise ValueError("HWE rLLM bridge tool contract is not native-shell v2")
        if self.tool_names != HWE_NATIVE_SHELL_TOOL_NAMES:
            raise ValueError("HWE rLLM bridge must expose exactly the six HWE tools")
        if self.call_count != 0:
            raise ValueError("HWE bridge conformance must not invoke tools")
        expected = hwe_tool_contract_hash(profile_id=HWE_COLLECTION_PROFILE_V2_ID)
        if self.tool_contract_hash != expected:
            raise ValueError("HWE rLLM bridge tool contract hash changed")
        if not self.security_boundary.get("network_disabled") or not self.security_boundary.get(
            "container_rootfs_read_only"
        ):
            raise ValueError("HWE rLLM bridge security boundary is incomplete")
        if not self.bridge_hash:
            object.__setattr__(self, "bridge_hash", content_hash(self.as_dict(False)))
        elif content_hash(self.as_dict(False)) != self.bridge_hash:
            raise ValueError("HWE rLLM bridge identity changed")

    def as_dict(self, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "format_id": self.format_id,
            "provider_neutral": self.provider_neutral,
            "profile_id": self.profile_id,
            "tool_contract_id": self.tool_contract_id,
            "tool_contract_hash": self.tool_contract_hash,
            "tool_names": list(self.tool_names),
            "verifier_binding": self.verifier_binding,
            "security_boundary": dict(self.security_boundary),
            "call_count": self.call_count,
        }
        if include_hash:
            value["bridge_hash"] = self.bridge_hash
        return value


def build_hwe_native_shell_v2_rllm_eval_bridge() -> HweNativeShellV2RllmEvalBridge:
    """Build the future-evaluation contract without importing or starting rLLM."""

    tools = hwe_tool_definitions(profile_id=HWE_COLLECTION_PROFILE_V2_ID)
    names = tuple(item["function"]["name"] for item in tools)
    if names != HWE_NATIVE_SHELL_TOOL_NAMES:
        raise ValueError("HWE native-shell tool registry is incomplete")
    return HweNativeShellV2RllmEvalBridge(
        format_id=HWE_RLLM_BRIDGE_FORMAT,
        provider_neutral=True,
        profile_id=HWE_COLLECTION_PROFILE_V2_ID,
        tool_contract_id=HWE_TOOL_CONTRACT_V2_ID,
        tool_contract_hash=hwe_tool_contract_hash(profile_id=HWE_COLLECTION_PROFILE_V2_ID),
        tool_names=names,
        verifier_binding="hwe_native_shell_v2_verifier_binding",
        security_boundary={
            "network_disabled": True,
            "container_rootfs_read_only": True,
            "candidate_write_scope": "/workspace/repository",
            "hidden_assets_exported": False,
            "reference_solution_exported": False,
            "credential_values_included": False,
            "raw_provider_events_exported": False,
            "verifier_calls": 0,
        },
    )


def zero_call_hwe_conformance() -> dict[str, Any]:
    """Return a serializable conformance result proving that no call was made."""

    bridge = build_hwe_native_shell_v2_rllm_eval_bridge()
    result = bridge.as_dict()
    result["conformance"] = "passed"
    result["zero_call"] = result["call_count"] == 0
    result["conformance_hash"] = content_hash(result)
    return result


__all__ = [
    "HWE_NATIVE_SHELL_TOOL_NAMES",
    "HWE_RLLM_BRIDGE_FORMAT",
    "HweNativeShellV2RllmEvalBridge",
    "build_hwe_native_shell_v2_rllm_eval_bridge",
    "zero_call_hwe_conformance",
]

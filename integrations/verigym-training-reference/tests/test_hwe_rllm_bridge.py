from __future__ import annotations

from verigym_training_reference.hwe_rllm_bridge import (
    HWE_NATIVE_SHELL_TOOL_NAMES,
    build_hwe_native_shell_v2_rllm_eval_bridge,
    zero_call_hwe_conformance,
)


def test_hwe_rllm_bridge_is_provider_neutral_and_zero_call() -> None:
    bridge = build_hwe_native_shell_v2_rllm_eval_bridge()
    assert bridge.tool_names == HWE_NATIVE_SHELL_TOOL_NAMES
    assert bridge.call_count == 0
    assert bridge.security_boundary["network_disabled"] is True
    assert bridge.security_boundary["verifier_calls"] == 0


def test_hwe_zero_call_conformance_is_hash_bound() -> None:
    result = zero_call_hwe_conformance()
    assert result["conformance"] == "passed"
    assert result["zero_call"] is True
    assert result["call_count"] == 0

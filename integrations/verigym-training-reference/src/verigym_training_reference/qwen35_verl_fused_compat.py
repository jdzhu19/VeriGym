"""Opt-in Qwen3.5 compatibility for verl's FSDP2 Torch-fused PPO head."""

from verigym_training_reference.qwen35_verl_compat import (
    QWEN35_CAUSAL_ADAPTER_COMPATIBILITY_ACTIVE,
    activate_fsdp2_fused_wrap_compatibility,
)

QWEN35_FSDP2_FUSED_WRAP_COMPATIBILITY_ACTIVE = activate_fsdp2_fused_wrap_compatibility()

__all__ = [
    "QWEN35_CAUSAL_ADAPTER_COMPATIBILITY_ACTIVE",
    "QWEN35_FSDP2_FUSED_WRAP_COMPATIBILITY_ACTIVE",
]

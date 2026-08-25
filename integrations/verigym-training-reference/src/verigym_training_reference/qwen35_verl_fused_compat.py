"""Opt-in Qwen3.5 compatibility for verl's FSDP2 Torch-fused PPO head."""

from verigym_training_reference.qwen35_verl_compat import (
    QWEN35_CAUSAL_ADAPTER_COMPATIBILITY_ACTIVE,
    activate_fsdp2_fused_head_compatibility,
    activate_qwen35_explicit_causal_model_compatibility,
)
from verigym_training_reference.verl_lora_dropout import install_verl_lora_dropout

install_verl_lora_dropout()
QWEN35_EXPLICIT_CAUSAL_MODEL_COMPATIBILITY_ACTIVE = (
    activate_qwen35_explicit_causal_model_compatibility()
)
QWEN35_FSDP2_FUSED_HEAD_COMPATIBILITY_ACTIVE = activate_fsdp2_fused_head_compatibility()

__all__ = [
    "QWEN35_CAUSAL_ADAPTER_COMPATIBILITY_ACTIVE",
    "QWEN35_EXPLICIT_CAUSAL_MODEL_COMPATIBILITY_ACTIVE",
    "QWEN35_FSDP2_FUSED_HEAD_COMPATIBILITY_ACTIVE",
]

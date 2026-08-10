"""Compatibility hook that keeps Qwen3.5 text adapters on the causal-LM class."""

from __future__ import annotations

from collections.abc import MutableMapping, Sequence
from typing import Any


def _remove_qwen35_image_mappings(auto_model: Any) -> bool:
    lazy_mapping = getattr(auto_model, "_model_mapping", None)
    model_names = getattr(lazy_mapping, "_model_mapping", None)
    if not isinstance(model_names, MutableMapping):
        return False
    expected = {
        "qwen3_5": "Qwen3_5ForConditionalGeneration",
        "qwen3_5_moe": "Qwen3_5MoeForConditionalGeneration",
    }
    removed = False
    for model_type, expected_class in expected.items():
        current = model_names.get(model_type)
        if current is None:
            continue
        if current != expected_class:
            raise RuntimeError(f"unexpected {model_type} image-text model mapping: {current}")
        del model_names[model_type]
        modules = getattr(lazy_mapping, "_modules", None)
        if isinstance(modules, MutableMapping):
            modules.pop(model_type, None)
        removed = True
    return removed


def activate_qwen35_causal_adapter_compatibility() -> bool:
    try:
        from transformers import AutoModelForImageTextToText  # type: ignore[import-not-found]
    except ImportError:
        return False
    return _remove_qwen35_image_mappings(AutoModelForImageTextToText)


def map_qwen35_causal_weight_name_for_vllm(name: str) -> str:
    """Map causal Qwen3.5 weight names onto vLLM's image-text wrapper."""

    if name.startswith("base_model.model.model."):
        suffix = name.removeprefix("base_model.model.model.")
        return f"base_model.model.model.language_model.{suffix}"
    if name.startswith(("model.", "lm_head.")):
        return f"language_model.{name}"
    return name


def expand_qwen35_gdn_lora_slices(
    lora_a: list[Any], lora_b: list[Any], output_sizes: Sequence[int]
) -> tuple[list[Any], list[Any]]:
    """Expand HF's combined QKV LoRA into vLLM's Q, K, V, and Z slices."""

    if len(lora_a) != 2 or len(lora_b) != 2 or len(output_sizes) != 4:
        raise RuntimeError("unexpected Qwen3.5 GDN LoRA slice layout")
    qkv_b, z_b = lora_b
    q_b, k_b, v_b = qkv_b.split(list(output_sizes[:3]), dim=0)
    qkv_a, z_a = lora_a
    return [qkv_a, qkv_a, qkv_a, z_a], [q_b, k_b, v_b, z_b]


QWEN35_CAUSAL_ADAPTER_COMPATIBILITY_ACTIVE = activate_qwen35_causal_adapter_compatibility()

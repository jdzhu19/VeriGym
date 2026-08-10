"""Compatibility hook that keeps Qwen3.5 text adapters on the causal-LM class."""

from __future__ import annotations

from collections.abc import MutableMapping
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


QWEN35_CAUSAL_ADAPTER_COMPATIBILITY_ACTIVE = activate_qwen35_causal_adapter_compatibility()

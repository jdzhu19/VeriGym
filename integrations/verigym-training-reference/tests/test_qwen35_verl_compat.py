from __future__ import annotations

from verigym_training_reference.qwen35_verl_compat import _remove_qwen35_image_mappings


class _FakeLazyMapping:
    def __init__(self) -> None:
        self._model_mapping = {
            "qwen3_5": "Qwen3_5ForConditionalGeneration",
            "qwen3_5_moe": "Qwen3_5MoeForConditionalGeneration",
            "keep": "KeepForConditionalGeneration",
        }
        self._modules = {"qwen3_5": object(), "keep": object()}


class _FakeAutoModel:
    _model_mapping = _FakeLazyMapping()


def test_qwen35_compatibility_removes_only_image_text_dispatch() -> None:
    assert _remove_qwen35_image_mappings(_FakeAutoModel) is True
    assert _FakeAutoModel._model_mapping._model_mapping == {"keep": "KeepForConditionalGeneration"}
    assert set(_FakeAutoModel._model_mapping._modules) == {"keep"}

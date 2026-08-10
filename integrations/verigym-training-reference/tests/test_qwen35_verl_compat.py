from __future__ import annotations

from verigym_training_reference.qwen35_verl_compat import (
    _remove_qwen35_image_mappings,
    expand_qwen35_gdn_lora_slices,
    map_qwen35_causal_weight_name_for_vllm,
)


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


class _FakeCombinedTensor:
    def split(self, sizes: list[int], *, dim: int) -> tuple[str, ...]:
        assert sizes == [128, 128, 256]
        assert dim == 0
        return ("q-b", "k-b", "v-b")


def test_qwen35_compatibility_removes_only_image_text_dispatch() -> None:
    assert _remove_qwen35_image_mappings(_FakeAutoModel) is True
    assert _FakeAutoModel._model_mapping._model_mapping == {"keep": "KeepForConditionalGeneration"}
    assert set(_FakeAutoModel._model_mapping._modules) == {"keep"}


def test_qwen35_compatibility_maps_causal_base_weights_to_vllm_wrapper() -> None:
    assert map_qwen35_causal_weight_name_for_vllm("model.embed_tokens.weight") == (
        "language_model.model.embed_tokens.weight"
    )
    assert map_qwen35_causal_weight_name_for_vllm("lm_head.weight") == (
        "language_model.lm_head.weight"
    )


def test_qwen35_compatibility_maps_causal_lora_weights_for_vllm_parser() -> None:
    name = "base_model.model.model.layers.0.self_attn.q_proj.lora_A.default.weight"
    assert map_qwen35_causal_weight_name_for_vllm(name) == (
        "base_model.model.model.language_model.layers.0.self_attn.q_proj.lora_A.default.weight"
    )
    assert map_qwen35_causal_weight_name_for_vllm("visual.patch_embed.weight") == (
        "visual.patch_embed.weight"
    )


def test_qwen35_compatibility_expands_combined_gdn_qkv_lora() -> None:
    expanded_a, expanded_b = expand_qwen35_gdn_lora_slices(
        ["qkv-a", "z-a"], [_FakeCombinedTensor(), "z-b"], [128, 128, 256, 256]
    )
    assert expanded_a == ["qkv-a", "qkv-a", "qkv-a", "z-a"]
    assert expanded_b == ["q-b", "k-b", "v-b", "z-b"]

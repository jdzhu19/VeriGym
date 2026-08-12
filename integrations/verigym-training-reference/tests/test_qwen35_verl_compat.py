from __future__ import annotations

from types import SimpleNamespace

from verigym_training_reference.qwen35_verl_compat import (
    _call_fused_head,
    _remove_qwen35_image_mappings,
    activate_fsdp2_fused_head_compatibility,
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


class _FakeHead:
    def __init__(self) -> None:
        self.weight = "weight"
        self.calls: list[tuple[object, ...]] = []

    def forward(self, *args: object) -> str:
        self.calls.append(("original", *args))
        return "original"

    def __call__(self, *args: object) -> object:
        self.calls.append(("hook", *args))
        return self.forward(*args)


class _FakeFusedLinear:
    def forward(self, **kwargs: object) -> tuple[object, object]:
        return kwargs["hidden_states"], kwargs["vocab_weights"]


class _FailingFusedLinear:
    def forward(self, **kwargs: object) -> tuple[object, object]:
        raise RuntimeError("projection failed")


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


def test_fused_head_call_runs_module_hook_and_restores_original_forward() -> None:
    head = _FakeHead()

    assert _call_fused_head(head, "hidden", "ids", 0.5, _FakeFusedLinear) == (
        "hidden",
        "weight",
    )
    assert head.calls == [("hook", "hidden", "ids", 0.5)]
    assert head("next") == "original"


def test_fused_head_call_restores_original_forward_after_failure() -> None:
    head = _FakeHead()

    try:
        _call_fused_head(head, "hidden", "ids", 0.5, _FailingFusedLinear)
    except RuntimeError as error:
        assert str(error) == "projection failed"
    else:
        raise AssertionError("failing fused projection did not propagate")

    assert head("next") == "original"


def test_fused_head_compatibility_is_idempotent_and_leaves_other_models_unchanged() -> None:
    calls: list[tuple[object, ...]] = []

    def original_forward(model: object, *args: object, **kwargs: object) -> str:
        calls.append((model, *args, kwargs))
        return "original"

    dense_common = SimpleNamespace(forward_with_torch_backend=original_forward)
    assert activate_fsdp2_fused_head_compatibility(dense_common) is True
    patched = dense_common.forward_with_torch_backend
    assert activate_fsdp2_fused_head_compatibility(dense_common) is True
    assert dense_common.forward_with_torch_backend is patched

    model = SimpleNamespace(config=SimpleNamespace(model_type="qwen2"))
    assert patched(model, input_ids="ids", temperature=0.5) == "original"
    assert calls == [
        (
            model,
            {
                "input_ids": "ids",
                "attention_mask": None,
                "position_ids": None,
                "past_key_values": None,
                "inputs_embeds": None,
                "labels": None,
                "use_cache": None,
                "output_attentions": None,
                "output_hidden_states": None,
                "return_dict": None,
                "cache_position": None,
                "logits_to_keep": 0,
                "temperature": 0.5,
            },
        )
    ]

"""Compatibility hooks for Qwen3.5 causal adapters and verl's FSDP2 path."""

from __future__ import annotations

import importlib
import types
from collections.abc import MutableMapping, Sequence
from typing import Any, cast

_FSDP2_FUSED_FORWARD_PATCH_MARKER = "_verigym_qwen35_fused_head_compatible"
_QWEN35_CAUSAL_MODEL_TYPES = {
    "qwen3_5",
    "qwen3_5_moe",
    "qwen3_5_moe_text",
    "qwen3_5_text",
}


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


def _call_fused_head(
    head: Any,
    hidden_states: Any,
    input_ids: Any,
    temperature: float,
    fused_linear_factory: Any,
) -> tuple[Any, Any]:
    """Run the bounded projection through the head's FSDP2 module hooks."""

    original_forward = head.forward

    def fused_forward(
        module: Any,
        head_hidden_states: Any,
        head_input_ids: Any,
        head_temperature: float,
    ) -> tuple[Any, Any]:
        return cast(
            tuple[Any, Any],
            fused_linear_factory().forward(
                hidden_states=head_hidden_states,
                vocab_weights=module.weight,
                input_ids=head_input_ids,
                temperature=head_temperature,
            ),
        )

    head.forward = types.MethodType(fused_forward, head)
    try:
        return cast(tuple[Any, Any], head(hidden_states, input_ids, temperature))
    finally:
        head.forward = original_forward


def activate_fsdp2_fused_head_compatibility(dense_common: Any | None = None) -> bool:
    """Route Qwen3.5's bounded fused projection through its FSDP2 head module.

    Verl reads ``lm_head.weight`` directly in its Torch fused PPO forward. An independently
    FSDP2-wrapped, CPU-offloaded head is therefore still a sharded DTensor. Calling the head
    module itself runs FSDP2's all-gather and reshard hooks around only the bounded projection,
    avoiding both mixed Tensor/DTensor operations and a full head resident during the backbone.
    """

    resolved_dense_common: Any = dense_common
    if resolved_dense_common is None:
        try:
            resolved_dense_common = importlib.import_module("verl.models.transformers.dense_common")
        except ModuleNotFoundError:
            return False
    original_forward = resolved_dense_common.forward_with_torch_backend
    if getattr(original_forward, _FSDP2_FUSED_FORWARD_PATCH_MARKER, False):
        return True

    def compatible_forward(
        model: Any,
        input_ids: Any = None,
        attention_mask: Any = None,
        position_ids: Any = None,
        past_key_values: Any = None,
        inputs_embeds: Any = None,
        labels: Any = None,
        use_cache: Any = None,
        output_attentions: Any = None,
        output_hidden_states: Any = None,
        return_dict: Any = None,
        cache_position: Any = None,
        logits_to_keep: Any = 0,
        temperature: float = 1.0,
        **loss_kwargs: Any,
    ) -> Any:
        if getattr(getattr(model, "config", None), "model_type", None) not in (
            _QWEN35_CAUSAL_MODEL_TYPES
        ):
            return original_forward(
                model,
                input_ids=input_ids,
                attention_mask=attention_mask,
                position_ids=position_ids,
                past_key_values=past_key_values,
                inputs_embeds=inputs_embeds,
                labels=labels,
                use_cache=use_cache,
                output_attentions=output_attentions,
                output_hidden_states=output_hidden_states,
                return_dict=return_dict,
                cache_position=cache_position,
                logits_to_keep=logits_to_keep,
                temperature=temperature,
                **loss_kwargs,
            )

        fsdp = importlib.import_module("torch.distributed.fsdp")
        torch = importlib.import_module("torch")
        torch_functional = importlib.import_module("verl.utils.experimental.torch_functional")

        if not isinstance(model.lm_head, fsdp.FSDPModule):
            raise RuntimeError("Qwen3.5 fused PPO compatibility requires an FSDP2 lm_head")
        outputs = resolved_dense_common.forward_base_model(
            model,
            input_ids=input_ids,
            attention_mask=attention_mask,
            position_ids=position_ids,
            past_key_values=past_key_values,
            inputs_embeds=inputs_embeds,
            use_cache=use_cache,
            output_attentions=output_attentions,
            output_hidden_states=output_hidden_states,
            cache_position=cache_position,
        )
        if not return_dict:
            raise NotImplementedError("Qwen3.5 fused PPO compatibility requires return_dict")
        if labels is not None:
            rolled_labels = torch.roll(labels, shifts=-1, dims=-1)
        elif input_ids is not None:
            rolled_labels = torch.roll(input_ids, shifts=-1, dims=-1)
        else:
            raise RuntimeError("Qwen3.5 fused PPO forward requires labels or input_ids")
        log_probs, entropy = _call_fused_head(
            model.lm_head,
            outputs[0],
            rolled_labels,
            temperature,
            torch_functional.FusedLinearForPPO,
        )
        return resolved_dense_common.CausalLMOutputForPPO(
            log_probs=log_probs,
            entropy=entropy,
            past_key_values=outputs.past_key_values,
            hidden_states=outputs.hidden_states,
            attentions=outputs.attentions,
        )

    setattr(compatible_forward, _FSDP2_FUSED_FORWARD_PATCH_MARKER, True)
    resolved_dense_common.forward_with_torch_backend = compatible_forward
    return True


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

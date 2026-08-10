"""vLLM worker extension for synchronizing causal Qwen3.5 training weights."""

from __future__ import annotations

from types import MethodType
from typing import Any

import torch  # type: ignore[import-not-found]
from verl.workers.rollout.vllm_rollout.utils import (  # type: ignore[import-not-found]
    vLLMColocateWorkerExtension,
)

from verigym_training_reference.qwen35_verl_compat import (
    expand_qwen35_gdn_lora_slices,
    map_qwen35_causal_weight_name_for_vllm,
)


class VeriGymQwen35WorkerExtension(vLLMColocateWorkerExtension):  # type: ignore[misc]
    """Translate causal-LM names before delegating to verl's weight loader."""

    def _install_gdn_lora_slice_bridge(self) -> None:
        lora_manager = getattr(self.model_runner, "lora_manager", None)
        adapter_manager = getattr(lora_manager, "_adapter_manager", None)
        modules = getattr(adapter_manager, "modules", {})
        for module_name, module in modules.items():
            if not module_name.endswith(".in_proj_qkvz"):
                continue
            if getattr(module, "_verigym_qwen35_gdn_slice_bridge", False):
                continue
            original_set_lora = module.set_lora

            def set_lora(
                module_self: Any,
                index: int,
                lora_a: torch.Tensor | list[torch.Tensor],
                lora_b: torch.Tensor | list[torch.Tensor],
                *,
                original: Any = original_set_lora,
            ) -> None:
                if not isinstance(lora_a, list) or not isinstance(lora_b, list):
                    raise RuntimeError("Qwen3.5 GDN LoRA weights were not packed")
                output_sizes = module_self.base_layer.output_sizes
                expanded_a, expanded_b = expand_qwen35_gdn_lora_slices(lora_a, lora_b, output_sizes)
                original(index, expanded_a, expanded_b)

            module.set_lora = MethodType(set_lora, module)
            module._verigym_qwen35_gdn_slice_bridge = True

    def _update_weights(
        self,
        weights: list[tuple[str, torch.Tensor]],
        peft_config: dict[str, Any] | None,
        base_sync_done: bool,
    ) -> None:
        model = self.model_runner.model
        if model.__class__.__name__ == "Qwen3_5ForConditionalGeneration":
            self._install_gdn_lora_slice_bridge()
            weights = [
                (map_qwen35_causal_weight_name_for_vllm(name), weight) for name, weight in weights
            ]
        super()._update_weights(weights, peft_config, base_sync_done)

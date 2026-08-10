"""vLLM worker extension for synchronizing causal Qwen3.5 training weights."""

from __future__ import annotations

from typing import Any

import torch  # type: ignore[import-not-found]
from verl.workers.rollout.vllm_rollout.utils import (  # type: ignore[import-not-found]
    vLLMColocateWorkerExtension,
)

from verigym_training_reference.qwen35_verl_compat import (
    map_qwen35_causal_weight_name_for_vllm,
)


class VeriGymQwen35WorkerExtension(vLLMColocateWorkerExtension):  # type: ignore[misc]
    """Translate causal-LM names before delegating to verl's weight loader."""

    def _update_weights(
        self,
        weights: list[tuple[str, torch.Tensor]],
        peft_config: dict[str, Any] | None,
        base_sync_done: bool,
    ) -> None:
        model = self.model_runner.model
        if model.__class__.__name__ == "Qwen3_5ForConditionalGeneration":
            weights = [
                (map_qwen35_causal_weight_name_for_vllm(name), weight) for name, weight in weights
            ]
        super()._update_weights(weights, peft_config, base_sync_done)

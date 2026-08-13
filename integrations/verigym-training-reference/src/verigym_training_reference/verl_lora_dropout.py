"""veRL 0.8.0 FSDP compatibility hook for the frozen SFT LoRA dropout.

veRL 0.8.0 exposes dropout in its Megatron LoRA subtree, but its Hugging Face
FSDP engine constructs ``peft.LoraConfig`` without forwarding a dropout value.
The frozen VeriGym run imports this module through ``model.external_lib`` before
the engine builds the PEFT model.  Keep this narrowly version-bound and fail if
another caller tries to supply a different value.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

LORA_DROPOUT = 0.05
_PATCH_MARKER = "__verigym_lora_dropout__"


def wrap_lora_config(factory: Callable[..., Any]) -> Callable[..., Any]:
    """Return a factory that injects the frozen dropout without hiding conflicts."""

    if getattr(factory, _PATCH_MARKER, None) == LORA_DROPOUT:
        return factory

    def configured_lora(*args: Any, **kwargs: Any) -> Any:
        supplied = float(kwargs.get("lora_dropout", LORA_DROPOUT))
        if supplied != LORA_DROPOUT:
            raise RuntimeError(f"VeriGym requires lora_dropout={LORA_DROPOUT}; received {supplied}")
        kwargs["lora_dropout"] = LORA_DROPOUT
        return factory(*args, **kwargs)

    setattr(configured_lora, _PATCH_MARKER, LORA_DROPOUT)
    return configured_lora


def install_verl_lora_dropout() -> None:
    """Patch only veRL's FSDP PEFT construction site."""

    from verl.workers.engine.fsdp import transformer_impl  # type: ignore[import-not-found]

    transformer_impl.LoraConfig = wrap_lora_config(transformer_impl.LoraConfig)


try:
    install_verl_lora_dropout()
except ModuleNotFoundError as exc:
    # Ordinary credential-free VeriGym tests do not install the GPU training stack.
    # In the opt-in training path the runtime pin check requires veRL before this
    # module is handed to ``model.external_lib``.
    if exc.name is None or not exc.name.startswith("verl"):
        raise

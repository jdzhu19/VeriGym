"""veRL dataset adapter for sealed OpenAI-style VeriGym tool transcripts."""

from __future__ import annotations

from rllm.trainer.verl.sft_dataset import RLLMSFTDataset  # type: ignore[import-not-found]

from .multiturn_sft_exporter import hf_template_tokens_and_loss_mask


class VeriGymHfTemplateSFTDataset(RLLMSFTDataset):  # type: ignore[misc]
    """Use Qwen-native rendering while preserving OpenAI records at rest."""

    def _tokenize_and_mask_hf_template(self, messages):  # type: ignore[no-untyped-def]
        return hf_template_tokens_and_loss_mask(self.tokenizer, messages)


__all__ = ["VeriGymHfTemplateSFTDataset"]

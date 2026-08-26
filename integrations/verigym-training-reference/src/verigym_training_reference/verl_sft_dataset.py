"""veRL dataset adapter for sealed OpenAI-style VeriGym tool transcripts."""

from __future__ import annotations

from pathlib import Path

import torch  # type: ignore[import-not-found]
from rllm.trainer.verl.sft_dataset import RLLMSFTDataset  # type: ignore[import-not-found]
from verigym.hwe.qwen_action_tokenizer import tokenizer_tree_hash
from verl.utils.dataset.dataset_utils import DatasetPadMode  # type: ignore[import-not-found]

from .hwe_decision_sft_64k import (
    DECISION_BALANCED_OBJECTIVE,
    TRAJECTORY_BALANCED_DECISION_OBJECTIVE,
    V4_MAX_LENGTH,
    decode_tool_aware_parquet_value,
    tool_aware_exact_final_decision_tokens,
    trajectory_balanced_decision_indices,
)
from .multiturn_sft_exporter import (
    hf_template_tokens_and_final_assistant_loss_mask,
    hf_template_tokens_and_loss_mask,
)


class VeriGymHfTemplateSFTDataset(RLLMSFTDataset):  # type: ignore[misc]
    """Use Qwen-native rendering while preserving OpenAI records at rest."""

    def _tokenize_and_mask_hf_template(self, messages):  # type: ignore[no-untyped-def]
        return hf_template_tokens_and_loss_mask(self.tokenizer, messages)


class VeriGymFinalAssistantHfTemplateSFTDataset(RLLMSFTDataset):  # type: ignore[misc]
    """Use Qwen-native rendering and supervise only the final assistant action."""

    def _tokenize_and_mask_hf_template(self, messages):  # type: ignore[no-untyped-def]
        return hf_template_tokens_and_final_assistant_loss_mask(self.tokenizer, messages)


class VeriGymCompleteAssistantDecisionHfTemplateSFTDataset(RLLMSFTDataset):  # type: ignore[misc]
    """Supervise the final public-text-plus-tool-calls assistant decision only."""

    def _tokenize_and_mask_hf_template(self, messages):  # type: ignore[no-untyped-def]
        return hf_template_tokens_and_final_assistant_loss_mask(self.tokenizer, messages)


class VeriGymHweDecisionSft64kDataset(RLLMSFTDataset):  # type: ignore[misc]
    """Require tools and exact receipts while supervising only the final decision."""

    objective_id = DECISION_BALANCED_OBJECTIVE

    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        config = kwargs.get("config")
        if config is None and len(args) >= 3:
            config = args[2]
        if config is None:
            raise ValueError("64K HWE dataset requires its frozen veRL config")
        if (
            config.get("pad_mode") != "no_padding"
            or config.get("truncation") != "error"
            or config.get("max_length") != V4_MAX_LENGTH
            or config.get("tools_key") != "tools"
            or config.get("exact_receipt_key") != "exact_token_receipt"
            or config.get("verigym_objective_id") != self.objective_id
        ):
            raise ValueError(
                "64K HWE dataset config permits padding, truncation, field loss, or objective drift"
            )
        tokenizer_root = Path(str(config.get("tokenizer_root", "")))
        self._verigym_tokenizer_id = str(config.get("tokenizer_id", ""))
        self._verigym_tokenizer_hash = tokenizer_tree_hash(tokenizer_root)
        if self._verigym_tokenizer_id != "Qwen3.5-9B/local-frozen-chat-template":
            raise ValueError("64K HWE dataset tokenizer identity changed")
        super().__init__(*args, **kwargs)
        if (
            self.tools is None  # type: ignore[has-type]
            or "exact_token_receipt" not in self.dataframe.columns
            or "sft_objective" not in self.dataframe.columns
        ):
            raise ValueError("64K HWE parquet lost tools, receipts, or its objective")
        self.messages = [
            decode_tool_aware_parquet_value(value, field="messages")
            for value in self.dataframe[self.messages_key].tolist()
        ]
        self.tools = [
            decode_tool_aware_parquet_value(value, field="tools")
            for value in self.dataframe[self.tools_key].tolist()
        ]
        self._verigym_receipts = [
            decode_tool_aware_parquet_value(value, field="exact_token_receipt")
            for value in self.dataframe["exact_token_receipt"].tolist()
        ]
        if self.dataframe["sft_objective"].tolist() != [DECISION_BALANCED_OBJECTIVE] * len(
            self.dataframe
        ):
            raise ValueError("64K HWE parquet objective changed")

    def __getitem__(self, item):  # type: ignore[no-untyped-def]
        exact = tool_aware_exact_final_decision_tokens(
            self.tokenizer,
            messages=self.messages[item],
            tools=self.tools[item],
            expected_receipt=self._verigym_receipts[item],
            tokenizer_id=self._verigym_tokenizer_id,
            tokenizer_hash=self._verigym_tokenizer_hash,
        )
        input_ids = torch.tensor(exact.input_ids, dtype=torch.long)
        loss_mask = torch.tensor(exact.loss_mask, dtype=torch.long)
        if int(loss_mask.sum().item()) != exact.receipt["target_tokens"]:
            raise ValueError("64K HWE supervised-token normalization changed")
        if self.pad_mode != DatasetPadMode.NO_PADDING:
            raise ValueError("64K HWE dataset must remain unpadded")
        if input_ids.shape[0] > self.max_length:
            raise ValueError("64K HWE sample is overlength; truncation is forbidden")
        return {
            "input_ids": input_ids,
            "position_ids": torch.arange(input_ids.shape[0], dtype=torch.long),
            "loss_mask": loss_mask,
        }


class VeriGymTrajectoryBalancedDecisionSft64kDataset(VeriGymHweDecisionSft64kDataset):
    """Balance trajectories while retaining exact decision-only target masks."""

    objective_id = TRAJECTORY_BALANCED_DECISION_OBJECTIVE

    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)  # type: ignore[no-untyped-call]
        required = {
            "transcript_hash",
            "decision_index",
            "trajectory_assistant_decision_count",
        }
        if not required.issubset(self.dataframe.columns):
            raise ValueError("trajectory-balanced SFT parquet lost trajectory metadata")
        self._verigym_schedule = trajectory_balanced_decision_indices(
            transcript_hashes=[str(value) for value in self.dataframe["transcript_hash"].tolist()],
            decision_indices=[int(value) for value in self.dataframe["decision_index"].tolist()],
            trajectory_decision_counts=[
                int(value)
                for value in self.dataframe["trajectory_assistant_decision_count"].tolist()
            ],
        )

    def __len__(self) -> int:
        if hasattr(self, "_verigym_schedule"):
            return len(self._verigym_schedule)
        return super().__len__()  # type: ignore[no-any-return]

    def __getitem__(self, item):  # type: ignore[no-untyped-def]
        return super().__getitem__(  # type: ignore[no-untyped-call]
            self._verigym_schedule[item]
        )


__all__ = [
    "VeriGymCompleteAssistantDecisionHfTemplateSFTDataset",
    "VeriGymFinalAssistantHfTemplateSFTDataset",
    "VeriGymHweDecisionSft64kDataset",
    "VeriGymTrajectoryBalancedDecisionSft64kDataset",
    "VeriGymHfTemplateSFTDataset",
]

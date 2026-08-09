"""Online completion-to-reward adapter for external RL frameworks."""

from __future__ import annotations

import json
from pathlib import Path

from verigym.api import PluginOrigin, RunConfig, VeriGym, build_registries
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.evolution.rewards import REPO_RTL_SPARSE_V1, reward_vector
from verigym.models.static import StaticModelClient
from verigym.schemas.common import InteractionMode
from verigym.schemas.options import JsonValue
from verigym.schemas.suite import SuiteSourceConfig

from .pipeline import validate_training_bundle
from .schemas import OnlineRewardResult

_MAX_CANDIDATE_BYTES = 4 * 1024 * 1024


class TrainingRewardOracle:
    """Score trainer completions through an ordinary, isolated VeriGym run."""

    def __init__(
        self,
        *,
        bundle: Path,
        source_dataset: Path,
        output_root: Path,
        runtime: str = "local",
        toolchain_profile: str | None = None,
        suite_source_root: Path | None = None,
        suite_variant: str | None = None,
    ) -> None:
        self.manifest = validate_training_bundle(bundle, source_dataset=source_dataset)
        root = output_root.expanduser()
        if root.exists() and (root.is_symlink() or not root.is_dir()):
            raise ConfigurationError("reward output root must be a real directory")
        root.mkdir(parents=True, exist_ok=True)
        self.output_root = root.resolve(strict=True)
        self.runtime = runtime
        self.toolchain_profile = toolchain_profile
        self.suite_source = (
            SuiteSourceConfig(source_root=suite_source_root, variant=suite_variant)
            if suite_source_root is not None
            else None
        )

    def task_prompt(self, task_id: str) -> list[dict[str, str]]:
        """Return a public ChatEval prompt for one frozen training task."""

        self._require_training_task(task_id)
        service = VeriGym(build_registries())
        _, task, _ = service.load_task(task_id, self.suite_source)
        if InteractionMode.CHAT not in task.interaction.supported_modes:
            raise ConfigurationError("training task does not support ChatEval prompting")
        if task.interaction.final_submission.kind == "line":
            return [
                {
                    "role": "system",
                    "content": (
                        "Complete the code prefix in the user message. Return exactly the single "
                        "source-code line that comes next and nothing else."
                    ),
                },
                {"role": "user", "content": task.description},
            ]
        payload = {
            "task_id": task.id,
            "title": task.title,
            "description": task.description,
            "entrypoints": sorted(task.workspace.entrypoints),
            "submission": {
                "kind": task.interaction.final_submission.kind,
                "content_format": "rtl_source",
            },
        }
        return [
            {
                "role": "system",
                "content": (
                    "You are completing a bounded RTL generation task. Return exactly one RTL "
                    "candidate for the declared entrypoint and do not request hidden assets."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
            },
        ]

    def _require_training_task(self, task_id: str) -> None:
        if task_id not in self.manifest.training_task_ids:
            raise ConfigurationError("reward oracle accepts only the frozen training split")

    def score(self, task_id: str, candidate: str) -> OnlineRewardResult:
        """Return only typed rewards; verifier assets and raw paths stay inside VeriGym."""

        self._require_training_task(task_id)
        candidate_bytes = candidate.encode("utf-8")
        if not candidate_bytes or len(candidate_bytes) > _MAX_CANDIDATE_BYTES:
            raise ConfigurationError("candidate must be non-empty and within the output bound")
        candidate_hash = hash_bytes(candidate_bytes)
        model_name = f"training-candidate-{candidate_hash[:16]}"
        registries = build_registries()
        registries.models.register(
            StaticModelClient(
                name=model_name,
                model_id="external-training-candidate",
                responses=[candidate],
            ),
            origin=PluginOrigin(
                package="verigym-training-reference",
                version="0.1.0",
                entry_point=None,
                registration="runtime",
            ),
        )
        service = VeriGym(registries)
        _, task, _ = service.load_task(task_id, self.suite_source)
        if InteractionMode.CHAT not in task.interaction.supported_modes:
            raise ConfigurationError("training task does not support single-turn ChatEval scoring")
        agent_options: dict[str, JsonValue] = (
            {"line_completion_prompt": "instructional-v1"}
            if task.interaction.final_submission.kind == "line"
            else {}
        )
        run = service.run(
            RunConfig(
                task_id=task_id,
                mode=InteractionMode.CHAT,
                agent="single-turn",
                model=model_name,
                agent_options=agent_options,
                suite_source=self.suite_source,
                runtime=self.runtime,
                toolchain_profile=self.toolchain_profile,
                output=self.output_root,
            )
        )
        reward = reward_vector(run.manifest, run.scorecard)
        scalar = REPO_RTL_SPARSE_V1.outcome_values[reward.outcome_kind]
        base = {
            "schema_version": "1.0",
            "interface_id": "verigym_online_reward_oracle_v1",
            "run_id": run.manifest.run_id,
            "task_id": task_id,
            "candidate_hash": candidate_hash,
            "outcome_kind": reward.outcome_kind,
            "reward": reward.model_dump(mode="json"),
            "reward_hash": content_hash(reward),
            "scalar_profile_id": "repo_rtl_sparse_v1",
            "scalar_reward": scalar,
            "infrastructure_valid": bool(reward.infrastructure_valid),
            "hidden_assets_exported": False,
            "reference_solution_exported": False,
        }
        return OnlineRewardResult.model_validate({**base, "result_hash": content_hash(base)})


__all__ = ["TrainingRewardOracle"]

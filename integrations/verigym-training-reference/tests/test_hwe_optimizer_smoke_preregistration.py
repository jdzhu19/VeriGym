from __future__ import annotations

from pathlib import Path

import pytest
from verigym.hwe.deepseek_harness_optimizer_smoke import (
    create_checkpoint_resume_qualification_authorization,
    create_optimizer_authorized_schedule_replay_authorization,
    create_optimizer_bf16_tolerance_replay_authorization,
    create_optimizer_diagnostic_replay_authorization,
    create_optimizer_full_smoke_bf16_tolerance_replay_authorization,
    create_optimizer_smoke_execution_authorization,
    load_optimizer_smoke_preregistration,
)

from verigym_training_reference.hwe_decision_sft_64k_checkpoint_resume_entry import (
    _checkpoint_manifest,
    _configure_exact_replay_determinism,
    _delete_temporary_checkpoint,
    _normalize_host_rng_at_step_boundary,
    _state_fingerprint,
    _verify_checkpoint_manifest,
)
from verigym_training_reference.hwe_decision_sft_64k_optimizer_smoke import (
    assert_authorized_optimizer_diagnostic_replay_config,
    assert_authorized_optimizer_smoke_config,
    assert_checkpoint_resume_branch_config,
    assert_optimizer_smoke_config,
    optimizer_diagnostic_clip_acceptance,
    optimizer_diagnostic_execution_identity,
    optimizer_smoke_clip_acceptance,
    prepare_authorized_optimizer_diagnostic_replay_config,
    prepare_authorized_optimizer_smoke_config,
    prepare_checkpoint_resume_branch_config,
    prepare_optimizer_smoke_config,
    run_optimizer_smoke,
    summarize_post_step_failure_diagnostics,
)
from verigym_training_reference.hwe_decision_sft_64k_optimizer_smoke_entry import (
    _authorized_execution_schedule,
    _post_step_diagnostics,
    _post_step_invariants,
    _write_post_step_diagnostics,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_CONFIG = _REPOSITORY_ROOT / "configs/training/qwen35_hwe_deepseek_harness_optimizer_smoke_v1.json"
_QUALIFICATION_ROOT = Path(
    "/data/jzhu484/Agent/experiments/cva6-hwe-deepseek-harness-v1/decision-sft-64k-v4"
)
_PREREGISTRATION_RECEIPT = Path(
    "/data/jzhu484/Agent/experiments/cva6-hwe-deepseek-harness-v1/optimizer-smoke-v1/"
    "preregistration-receipt.json"
)
_OPTIMIZER_SMOKE_ROOT = _PREREGISTRATION_RECEIPT.parent
_EXECUTION_AUTHORIZATION = _OPTIMIZER_SMOKE_ROOT / "execution-authorization.json"
_FAILED_EXECUTION_REPORT = _OPTIMIZER_SMOKE_ROOT / "execution-report.json"
_RETRY_AUTHORIZATION = _OPTIMIZER_SMOKE_ROOT / "execution-retry-authorization.json"
_RETRY_FAILURE_REPORT = _OPTIMIZER_SMOKE_ROOT / "execution-retry-report.json"
_DIAGNOSTIC_AUTHORIZATION = _OPTIMIZER_SMOKE_ROOT / "execution-diagnostic-authorization.json"
_DIAGNOSTIC_FAILURE_REPORT = _OPTIMIZER_SMOKE_ROOT / "execution-diagnostic-report.json"
_BF16_TOLERANCE_AUTHORIZATION = (
    _OPTIMIZER_SMOKE_ROOT / "execution-bf16-tolerance-authorization.json"
)
_BF16_TOLERANCE_FAILURE_REPORT = _OPTIMIZER_SMOKE_ROOT / "execution-bf16-tolerance-report.json"
_BF16_TOLERANCE_RANK_DIAGNOSTICS = tuple(
    _OPTIMIZER_SMOKE_ROOT
    / "bf16-tolerance-rank-evidence"
    / f"rank-{rank}-step-01-post-step-diagnostics.json"
    for rank in range(4)
)
_FULL_SMOKE_AUTHORIZATION = _OPTIMIZER_SMOKE_ROOT / "execution-full-smoke-authorization.json"
_FULL_SMOKE_FAILURE_REPORT = _OPTIMIZER_SMOKE_ROOT / "execution-full-smoke-report.json"
_FULL_SMOKE_RANK_DIAGNOSTICS = tuple(
    _OPTIMIZER_SMOKE_ROOT
    / "full-smoke-rank-evidence"
    / f"rank-{rank}-step-{step:02d}-post-step-diagnostics.json"
    for rank in range(4)
    for step in (1, 2)
)
_INSTRUMENTATION_SOURCE = (
    _REPOSITORY_ROOT / "integrations/verigym-training-reference/src/verigym_training_reference/"
    "hwe_decision_sft_64k_optimizer_smoke_entry.py"
)
_ATTEMPT_7_AUTHORIZATION = _OPTIMIZER_SMOKE_ROOT / "execution-full-smoke-bf16-authorization.json"
_ATTEMPT_7_PASS_REPORT = _OPTIMIZER_SMOKE_ROOT / "execution-full-smoke-bf16-report.json"
_ATTEMPT_7_SUMMARY = _OPTIMIZER_SMOKE_ROOT / "full-smoke-bf16-replay-summary.json"
_ATTEMPT_7_RANK_DIAGNOSTICS = tuple(
    _OPTIMIZER_SMOKE_ROOT
    / "full-smoke-bf16-rank-evidence"
    / f"rank-{rank}-step-{step:02d}-post-step-diagnostics.json"
    for rank in range(4)
    for step in range(1, 9)
)
_CHECKPOINT_RESUME_SOURCE = (
    _REPOSITORY_ROOT / "integrations/verigym-training-reference/src/verigym_training_reference/"
    "hwe_decision_sft_64k_checkpoint_resume_entry.py"
)


def _checkpoint_resume_artifacts_present() -> bool:
    return all(
        path.is_file()
        for path in (
            _PREREGISTRATION_RECEIPT,
            _ATTEMPT_7_AUTHORIZATION,
            _ATTEMPT_7_PASS_REPORT,
            _ATTEMPT_7_SUMMARY,
            *_ATTEMPT_7_RANK_DIAGNOSTICS,
        )
    )


def test_optimizer_smoke_resolved_config_freezes_optimizer_and_schedule() -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    qualification = {
        "model": {"path": "/frozen/model"},
        "data": {"train_files": "/frozen/train.parquet"},
        "trainer": {"default_local_dir": "/scratch/not-created"},
    }

    resolved = prepare_optimizer_smoke_config(qualification, plan)

    assert resolved["model"]["path"] == "/frozen/model"
    assert resolved["optim"]["optimizer"] == "AdamW"
    assert resolved["optim"]["optimizer_impl"] == "torch.optim"
    assert resolved["optim"]["lr"] == 1e-4
    assert resolved["optim"]["betas"] == [0.9, 0.999]
    assert resolved["optim"]["override_optimizer_config"]["eps"] == 1e-8
    assert resolved["optim"]["weight_decay"] == 0.0
    assert resolved["optim"]["lr_warmup_steps"] == 0
    assert resolved["optim"]["clip_grad"] == 1.0
    assert resolved["optim"]["total_training_steps"] == 8
    assert resolved["trainer"]["total_training_steps"] == 8
    assert resolved["checkpoint"]["save_contents"] == []
    assert resolved["checkpoint"]["load_contents"] == []
    assert resolved["verigym_optimizer_smoke"]["sample_indices"] == [
        62,
        76,
        20,
        61,
        41,
        43,
        53,
        61,
    ]
    assert resolved["verigym_optimizer_smoke"]["execution_authorized"] is False


def test_optimizer_smoke_resolved_config_rejects_drift_and_execution() -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    resolved = prepare_optimizer_smoke_config({}, plan)
    resolved["optim"]["lr"] = 1e-3

    with pytest.raises(ValueError, match="optim.lr changed"):
        assert_optimizer_smoke_config(resolved, preregistration=plan)
    with pytest.raises(RuntimeError, match="execution is not enabled"):
        run_optimizer_smoke()


def test_optimizer_smoke_post_step_diagnostics_name_and_persist_every_invariant(
    tmp_path: Path,
) -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    scheduled = plan.schedule[0]
    post_clip = {
        "finite": True,
        "nonzero_on_every_rank": True,
        "global_norm": 0.75,
        "local_tensor_count": 4,
        "global_tensor_count": 16,
    }
    passed = _post_step_invariants(
        actual_optimizer_steps=1,
        scheduled_step=1,
        engine_pre_clip_norm=2.0,
        post_clip=post_clip,
        post_clip_global_norm_limit=1.0,
        parameter_hash_before="a" * 64,
        parameter_hash_after="b" * 64,
        optimizer_state_steps=[1],
        optimizer_state_parameter_count=4,
        gradient_tensor_count=4,
    )
    assert len(passed) == 9
    assert all(passed.values())

    failed = _post_step_invariants(
        actual_optimizer_steps=2,
        scheduled_step=1,
        engine_pre_clip_norm=float("nan"),
        post_clip={**post_clip, "finite": False, "global_norm": 1.25},
        post_clip_global_norm_limit=1.0,
        parameter_hash_before="a" * 64,
        parameter_hash_after="a" * 64,
        optimizer_state_steps=[2],
        optimizer_state_parameter_count=3,
        gradient_tensor_count=4,
    )
    assert {name for name, value in failed.items() if not value} == {
        "optimizer_step_count_matches",
        "engine_pre_clip_norm_finite",
        "engine_pre_clip_norm_positive",
        "post_clip_gradients_finite",
        "post_clip_global_norm_within_limit",
        "trainable_parameter_hash_changed",
        "optimizer_state_step_matches",
        "optimizer_state_parameter_count_matches_gradient_count",
    }
    diagnostics = _post_step_diagnostics(
        rank=0,
        scheduled=scheduled,
        invariants=failed,
        actual_optimizer_steps=2,
        engine_pre_clip_norm=float("nan"),
        post_clip={**post_clip, "finite": False, "global_norm": 1.25},
        post_clip_global_norm_target=1.0,
        post_clip_global_norm_relative_tolerance=0.0,
        post_clip_global_norm_acceptance_limit=1.0,
        parameter_hash_before="a" * 64,
        parameter_hash_after="a" * 64,
        optimizer_state_steps=[2],
        optimizer_state_parameter_count=3,
        gradient_tensor_count=4,
        all_ranks_invariants_passed=False,
    )
    output = _write_post_step_diagnostics(tmp_path, diagnostics)
    assert output.name == "step-01-post-step-diagnostics.json"
    assert diagnostics["failed_local_invariants"] == sorted(
        name for name, value in failed.items() if not value
    )
    assert diagnostics["all_local_invariants_passed"] is False
    assert diagnostics["all_ranks_invariants_passed"] is False
    assert diagnostics["observed"]["engine_pre_clip_global_norm"] == "nan"
    assert diagnostics["observed"]["post_clip_global_norm_target"] == 1.0
    assert diagnostics["observed"]["post_clip_global_norm_acceptance_limit"] == 1.0
    assert output.is_file()
    with pytest.raises(RuntimeError, match="already exists"):
        _write_post_step_diagnostics(tmp_path, diagnostics)

    summary = summarize_post_step_failure_diagnostics(
        [
            {
                "rank": rank,
                "post_step_diagnostics": {**diagnostics, "rank": rank},
            }
            for rank in range(4)
        ],
        world_size=4,
    )
    assert summary["post_step_diagnostics_complete"] is True
    assert summary["failed_post_step_invariants"] == diagnostics["failed_local_invariants"]
    assert [item["rank"] for item in summary["post_step_diagnostics_by_rank"]] == [
        0,
        1,
        2,
        3,
    ]


def test_optimizer_smoke_bf16_tolerance_is_principled_and_bounded() -> None:
    post_clip = {
        "finite": True,
        "nonzero_on_every_rank": True,
        "global_norm": 1.0015633596301037,
    }
    within = _post_step_invariants(
        actual_optimizer_steps=1,
        scheduled_step=1,
        engine_pre_clip_norm=4.375,
        post_clip=post_clip,
        post_clip_global_norm_limit=1.0 * (1.0 + 2.0 * 0.0078125),
        parameter_hash_before="a" * 64,
        parameter_hash_after="b" * 64,
        optimizer_state_steps=[1],
        optimizer_state_parameter_count=496,
        gradient_tensor_count=496,
    )
    assert within["post_clip_global_norm_within_limit"] is True
    outside = _post_step_invariants(
        actual_optimizer_steps=1,
        scheduled_step=1,
        engine_pre_clip_norm=4.375,
        post_clip={**post_clip, "global_norm": 1.015626},
        post_clip_global_norm_limit=1.015625,
        parameter_hash_before="a" * 64,
        parameter_hash_after="b" * 64,
        optimizer_state_steps=[1],
        optimizer_state_parameter_count=496,
        gradient_tensor_count=496,
    )
    assert outside["post_clip_global_norm_within_limit"] is False


def test_optimizer_diagnostic_execution_schedule_cannot_reach_step_two() -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    diagnostic = _authorized_execution_schedule(
        plan.schedule,
        optimizer_steps_authorized=1,
    )
    full = _authorized_execution_schedule(
        plan.schedule,
        optimizer_steps_authorized=8,
    )

    assert [item.step for item in diagnostic] == [1]
    assert [item.step for item in full] == list(range(1, 9))
    with pytest.raises(RuntimeError, match="invalid step count"):
        _authorized_execution_schedule(plan.schedule, optimizer_steps_authorized=9)


def test_optimizer_smoke_post_step_summary_rejects_unbound_diagnostics() -> None:
    summary = summarize_post_step_failure_diagnostics(
        [
            {
                "rank": 0,
                "post_step_diagnostics": {
                    "format_id": "verigym_hwe_optimizer_smoke_post_step_diagnostics_v1",
                    "rank": 1,
                    "invariants": {"parameter_hash_changed": False},
                },
            }
        ],
        world_size=4,
    )
    assert summary == {
        "post_step_diagnostics_complete": False,
        "failed_post_step_invariants": [],
        "post_step_diagnostics_by_rank": [],
    }


@pytest.mark.skipif(
    not _PREREGISTRATION_RECEIPT.is_file(),
    reason="optimizer-smoke preregistration receipt is not installed",
)
def test_optimizer_smoke_authorized_config_requires_both_sealed_hashes() -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    authorization = create_optimizer_smoke_execution_authorization(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
    )
    resolved = prepare_authorized_optimizer_smoke_config(
        {"model": {"path": "/frozen/model"}},
        plan,
        authorization,
    )

    assert resolved["verigym_optimizer_smoke"]["execution_authorized"] is True
    assert (
        resolved["verigym_optimizer_smoke"]["authorization_hash"]
        == authorization.authorization_hash
    )
    assert_authorized_optimizer_smoke_config(
        resolved,
        preregistration=plan,
        authorization=authorization,
    )
    resolved["verigym_optimizer_smoke"]["authorization_hash"] = "0" * 64
    with pytest.raises(ValueError, match="authorization_hash changed"):
        assert_authorized_optimizer_smoke_config(
            resolved,
            preregistration=plan,
            authorization=authorization,
        )


@pytest.mark.skipif(
    not all(
        path.is_file()
        for path in (
            _PREREGISTRATION_RECEIPT,
            _EXECUTION_AUTHORIZATION,
            _FAILED_EXECUTION_REPORT,
            _RETRY_AUTHORIZATION,
            _RETRY_FAILURE_REPORT,
        )
    ),
    reason="optimizer diagnostic evidence is not installed",
)
def test_optimizer_diagnostic_config_allows_exactly_one_first_record_step() -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    authorization = create_optimizer_diagnostic_replay_authorization(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_authorization_path=_EXECUTION_AUTHORIZATION,
        prior_failure_report_path=_FAILED_EXECUTION_REPORT,
        prior_retry_authorization_path=_RETRY_AUTHORIZATION,
        prior_retry_failure_report_path=_RETRY_FAILURE_REPORT,
        instrumentation_source_path=_INSTRUMENTATION_SOURCE,
    )
    resolved = prepare_authorized_optimizer_diagnostic_replay_config(
        {"model": {"path": "/frozen/model"}},
        plan,
        authorization,
    )

    assert resolved["optim"]["total_training_steps"] == 1
    assert resolved["trainer"]["total_training_steps"] == 1
    metadata = resolved["verigym_optimizer_smoke"]
    assert metadata["diagnostic_replay"] is True
    assert metadata["optimizer_steps_authorized"] == 1
    assert metadata["diagnostic_record_index"] == 62
    assert metadata["diagnostic_record_hash"] == plan.schedule[0].source_v4_record_hash
    assert_authorized_optimizer_diagnostic_replay_config(
        resolved,
        preregistration=plan,
        authorization=authorization,
    )
    resolved["trainer"]["total_training_steps"] = 2
    with pytest.raises(ValueError, match="trainer step count changed"):
        assert_authorized_optimizer_diagnostic_replay_config(
            resolved,
            preregistration=plan,
            authorization=authorization,
        )


@pytest.mark.skipif(
    not all(path.is_file() for path in (_DIAGNOSTIC_AUTHORIZATION, _DIAGNOSTIC_FAILURE_REPORT)),
    reason="optimizer attempt-3 diagnostic evidence is not installed",
)
def test_optimizer_bf16_tolerance_config_is_exact_and_single_step() -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    authorization = create_optimizer_bf16_tolerance_replay_authorization(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_diagnostic_authorization_path=_DIAGNOSTIC_AUTHORIZATION,
        prior_diagnostic_failure_report_path=_DIAGNOSTIC_FAILURE_REPORT,
        implementation_source_path=_INSTRUMENTATION_SOURCE,
    )
    resolved = prepare_authorized_optimizer_diagnostic_replay_config({}, plan, authorization)
    metadata = resolved["verigym_optimizer_smoke"]

    assert optimizer_diagnostic_clip_acceptance(plan, authorization) == (
        1.0,
        0.015625,
        1.015625,
    )
    assert resolved["optim"]["total_training_steps"] == 1
    assert resolved["trainer"]["total_training_steps"] == 1
    assert metadata["bf16_tolerance_replay"] is True
    assert metadata["post_clip_global_norm_acceptance_lte"] == 1.015625
    assert_authorized_optimizer_diagnostic_replay_config(
        resolved,
        preregistration=plan,
        authorization=authorization,
    )


@pytest.mark.skipif(
    not all(
        path.is_file()
        for path in (
            _BF16_TOLERANCE_AUTHORIZATION,
            _BF16_TOLERANCE_FAILURE_REPORT,
            *_BF16_TOLERANCE_RANK_DIAGNOSTICS,
        )
    ),
    reason="optimizer attempt-4 schedule evidence is not installed",
)
def test_optimizer_authorized_schedule_config_has_unique_one_step_identity() -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    rank_0, rank_1, rank_2, rank_3 = _BF16_TOLERANCE_RANK_DIAGNOSTICS
    authorization = create_optimizer_authorized_schedule_replay_authorization(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_bf16_tolerance_authorization_path=_BF16_TOLERANCE_AUTHORIZATION,
        prior_bf16_tolerance_failure_report_path=_BF16_TOLERANCE_FAILURE_REPORT,
        prior_bf16_rank_diagnostic_paths=(rank_0, rank_1, rank_2, rank_3),
        implementation_source_path=_INSTRUMENTATION_SOURCE,
    )
    resolved = prepare_authorized_optimizer_diagnostic_replay_config({}, plan, authorization)

    assert optimizer_diagnostic_execution_identity(authorization) == (
        "verigym_hwe_decision_sft_64k_optimizer_authorized_schedule_replay_execution_v1",
        "single_record_single_optimizer_step_authorized_schedule",
    )
    assert resolved["optim"]["total_training_steps"] == 1
    assert resolved["trainer"]["total_training_steps"] == 1
    assert_authorized_optimizer_diagnostic_replay_config(
        resolved,
        preregistration=plan,
        authorization=authorization,
    )


@pytest.mark.skipif(
    not all(
        path.is_file()
        for path in (
            _FULL_SMOKE_AUTHORIZATION,
            _FULL_SMOKE_FAILURE_REPORT,
            *_FULL_SMOKE_RANK_DIAGNOSTICS,
        )
    ),
    reason="optimizer attempt-6 BF16-only failure evidence is not installed",
)
def test_optimizer_full_smoke_bf16_config_propagates_principled_tolerance() -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    diagnostics = tuple(_FULL_SMOKE_RANK_DIAGNOSTICS)
    authorization = create_optimizer_full_smoke_bf16_tolerance_replay_authorization(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_full_smoke_authorization_path=_FULL_SMOKE_AUTHORIZATION,
        prior_full_smoke_failure_report_path=_FULL_SMOKE_FAILURE_REPORT,
        prior_full_smoke_rank_diagnostic_paths=(
            diagnostics[0],
            diagnostics[1],
            diagnostics[2],
            diagnostics[3],
            diagnostics[4],
            diagnostics[5],
            diagnostics[6],
            diagnostics[7],
        ),
        implementation_source_path=_INSTRUMENTATION_SOURCE,
    )
    resolved = prepare_authorized_optimizer_smoke_config({}, plan, authorization)
    metadata = resolved["verigym_optimizer_smoke"]

    assert optimizer_smoke_clip_acceptance(plan, authorization) == (
        1.0,
        0.015625,
        1.015625,
    )
    assert resolved["optim"]["total_training_steps"] == 8
    assert resolved["trainer"]["total_training_steps"] == 8
    assert metadata["bf16_tolerance_replay"] is True
    assert metadata["gradient_clip_target"] == 1.0
    assert metadata["post_clip_global_norm_relative_tolerance"] == 0.015625
    assert metadata["post_clip_global_norm_acceptance_lte"] == 1.015625
    assert_authorized_optimizer_smoke_config(
        resolved,
        preregistration=plan,
        authorization=authorization,
    )


@pytest.mark.skipif(
    not _checkpoint_resume_artifacts_present(),
    reason="optimizer attempt-7 pass evidence is not installed",
)
def test_checkpoint_resume_branch_configs_are_disjoint_and_bounded() -> None:
    plan = load_optimizer_smoke_preregistration(_CONFIG)
    authorization = create_checkpoint_resume_qualification_authorization(
        plan,
        dataset_root=_QUALIFICATION_ROOT / "dataset",
        qualification_root=_QUALIFICATION_ROOT,
        config_path=_CONFIG,
        preregistration_receipt_path=_PREREGISTRATION_RECEIPT,
        prior_attempt_7_authorization_path=_ATTEMPT_7_AUTHORIZATION,
        prior_attempt_7_pass_report_path=_ATTEMPT_7_PASS_REPORT,
        prior_attempt_7_summary_path=_ATTEMPT_7_SUMMARY,
        prior_attempt_7_rank_diagnostic_paths=_ATTEMPT_7_RANK_DIAGNOSTICS,
        implementation_source_path=_CHECKPOINT_RESUME_SOURCE,
    )
    root = "/evidence/temporary-fsdp2-checkpoint"
    branches = {
        branch: prepare_checkpoint_resume_branch_config(
            {},
            plan,
            authorization,
            branch=branch,
            checkpoint_root=root,
        )
        for branch in ("control", "producer", "resume")
    }

    assert branches["control"]["checkpoint"]["save_contents"] == []
    assert branches["producer"]["checkpoint"]["save_contents"] == [
        "model",
        "optimizer",
        "extra",
    ]
    assert branches["resume"]["checkpoint"]["load_contents"] == [
        "model",
        "optimizer",
        "extra",
    ]
    assert branches["resume"]["trainer"]["resume_mode"] == "resume_path"
    assert branches["resume"]["trainer"]["resume_from_path"] == (
        "/evidence/temporary-fsdp2-checkpoint/global_step_2"
    )
    for branch, resolved in branches.items():
        assert_checkpoint_resume_branch_config(
            resolved,
            preregistration=plan,
            authorization=authorization,
            branch=branch,
            checkpoint_root=root,
        )
    branches["producer"]["trainer"]["max_ckpt_to_keep"] = 2
    with pytest.raises(ValueError, match="max_ckpt_to_keep changed"):
        assert_checkpoint_resume_branch_config(
            branches["producer"],
            preregistration=plan,
            authorization=authorization,
            branch="producer",
            checkpoint_root=root,
        )


def test_checkpoint_manifest_is_complete_hash_bound_and_temporarily_deleted(
    tmp_path: Path,
) -> None:
    root = tmp_path / "temporary-fsdp2-checkpoint"
    step = root / "global_step_2"
    step.mkdir(parents=True)
    for kind in ("model", "optim", "extra_state"):
        for rank in range(4):
            (step / f"{kind}_world_size_4_rank_{rank}.pt").write_bytes(f"{kind}-{rank}".encode())
    (step / "data_0.pt").write_bytes(b"dataloader")
    (step / "verigym_schedule_cursor.json").write_text("{}", encoding="utf-8")

    manifest = _checkpoint_manifest(root)
    assert manifest["file_count"] == 14
    _verify_checkpoint_manifest(root, manifest)
    (step / "data_0.pt").write_bytes(b"changed")
    with pytest.raises(Exception, match="identity changed"):
        _verify_checkpoint_manifest(root, manifest)
    assert _delete_temporary_checkpoint(root) is True
    assert not root.exists()


def test_checkpoint_state_fingerprint_accepts_scalar_optimizer_tensor() -> None:
    torch = pytest.importorskip("torch")

    fingerprint = _state_fingerprint(torch, {"step": torch.tensor(4.0)})

    assert len(fingerprint) == 64
    assert fingerprint == _state_fingerprint(torch, {"step": torch.tensor(4.0)})
    assert fingerprint != _state_fingerprint(torch, {"step": torch.tensor(5.0)})


def test_checkpoint_replay_determinism_is_explicit_and_fail_closed() -> None:
    class _Cudnn:
        benchmark = True
        deterministic = False

    class _Backends:
        cudnn = _Cudnn()

    class _Torch:
        backends = _Backends()
        enabled = False

        @classmethod
        def use_deterministic_algorithms(cls, enabled: bool) -> None:
            cls.enabled = enabled

        @classmethod
        def are_deterministic_algorithms_enabled(cls) -> bool:
            return cls.enabled

    environment: dict[str, str] = {}
    receipt = _configure_exact_replay_determinism(_Torch, environment)

    assert environment == {
        "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
        "FLASH_ATTENTION_DETERMINISTIC": "1",
    }
    assert receipt["flash_attention_deterministic"] is True
    assert receipt["torch_deterministic_algorithms"] is True
    assert receipt["host_rng_step_boundary_normalized"] is True
    assert _Torch.backends.cudnn.benchmark is False
    assert _Torch.backends.cudnn.deterministic is True

    with pytest.raises(RuntimeError, match="FLASH_ATTENTION_DETERMINISTIC conflicts"):
        _configure_exact_replay_determinism(
            _Torch,
            {"FLASH_ATTENTION_DETERMINISTIC": "0"},
        )


def test_checkpoint_replay_normalizes_only_host_rng_at_step_boundaries() -> None:
    class _Random:
        seed_value: int | None = None

        @classmethod
        def seed(cls, value: int) -> None:
            cls.seed_value = value

    class _NumpyRandom:
        seed_value: int | None = None

        @classmethod
        def seed(cls, value: int) -> None:
            cls.seed_value = value

    class _Numpy:
        random = _NumpyRandom()

    class _Generator:
        seed_value: int | None = None

        def __init__(self, *, device: str) -> None:
            assert device == "cpu"

        def manual_seed(self, value: int) -> None:
            self.seed_value = value

        def get_state(self) -> tuple[str, int | None]:
            return ("cpu", self.seed_value)

    class _Torch:
        Generator = _Generator
        cpu_state: object = None

        @classmethod
        def set_rng_state(cls, value: object) -> None:
            cls.cpu_state = value

    boundary_seed = _normalize_host_rng_at_step_boundary(
        engine_seed=484,
        global_step=2,
        random_module=_Random,
        numpy_module=_Numpy,
        torch_module=_Torch,
    )

    assert boundary_seed == 484 * 1_000_003 + 2
    assert _Random.seed_value == boundary_seed
    assert _Numpy.random.seed_value == boundary_seed % (2**32)
    assert _Torch.cpu_state == ("cpu", boundary_seed)

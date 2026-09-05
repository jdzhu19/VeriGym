from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from verigym_deepseek_harness import config as harness_config

from verigym.hwe.deepseek_harness_campaign import (
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
    DeepSeekHarnessV170OfficialMatrixManifest,
    load_v170_official_matrix_manifest,
    new_matrix_state,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

from scripts import collect_hwe_deepseek_harness_v170_official_matrix as runner  # noqa: E402
from scripts import launch_hwe_deepseek_harness_v170_official_matrix as launcher  # noqa: E402

_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v170_official_matrix_v1.json"
)


def test_checked_in_v170_manifest_is_fresh_and_preserves_the_frozen_protocol() -> None:
    manifest = load_v170_official_matrix_manifest(_MANIFEST)
    assert manifest.identity == runner.IDENTITY
    assert [item.pr_number for item in manifest.schedule] == [465, 1135, 1780, 2017, 2711]
    assert manifest.seed == 502
    assert manifest.sample_index == 18
    assert manifest.model == "deepseek-v4-flash"
    assert manifest.max_provider_calls_per_task == 64
    assert manifest.max_provider_tokens_per_task == 1_000_000
    assert manifest.max_context_tokens == 65_536
    assert manifest.max_output_tokens == 2_048
    assert manifest.temperature == 0
    assert manifest.provider_request_retries == 0
    assert manifest.whole_episode_retries == 0
    assert manifest.ordinary_tool_choice == "auto"
    assert manifest.provider_hidden_thinking == "disabled"
    assert manifest.provider_environment_boundary == "exact-two-name-child-v1"
    assert manifest.provider_environment_name_count == 2
    assert manifest.v158_data_volume_reopen_count_before == 4
    assert manifest.v158_data_volume_reopen_budget == 5
    assert manifest.v165_post_merge_main_run_id == 33971109229
    assert manifest.v167_post_merge_main_run_id == 33973532777
    assert manifest.v168_post_merge_main_run_id == 33974998196
    assert manifest.v169_post_merge_main_run_id == 33975720801
    assert manifest.dind_socket_volume == "verigym-deepseek-harness-v170-dind-socket"
    assert manifest.runtime_resource_owner == runner.IDENTITY
    assert manifest.requires_independent_v163_audit is False
    assert manifest.requires_independent_v165_audit is False
    assert manifest.requires_independent_v167_audit is False
    assert manifest.requires_independent_v169_audit is False
    assert manifest.requires_independent_v171_audit is True
    assert manifest.formal_collection_allowed is False
    assert manifest.formal_collection_started is False
    assert manifest.collection_started is False
    assert manifest.training_started is False
    assert manifest.production_training_ready is False


def test_v170_manifest_hash_rejects_policy_or_predecessor_mutation() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    value["v158_data_volume_reopen_count_before"] = 1
    with pytest.raises(ValueError):
        DeepSeekHarnessV170OfficialMatrixManifest.model_validate(value)


@pytest.mark.skipif(
    not runner.V158_ROOT.is_dir()
    or not runner.V162_ROOT.is_dir()
    or not runner.V164_ROOT.is_dir()
    or not runner.V166_ROOT.is_dir()
    or not runner.V168_ROOT.is_dir(),
    reason="sealed v158/v162/v164/v166/v168 evidence is not local",
)
def test_v170_checked_in_predecessors_and_task_bindings_are_exact() -> None:
    manifest = load_v170_official_matrix_manifest(_MANIFEST)
    runner._validate_predecessor(manifest, v158_root=runner.V158_ROOT)  # noqa: SLF001
    locks = runner._validate_task_bindings(manifest, v158_root=runner.V158_ROOT)  # noqa: SLF001
    assert list(locks) == [item.task_id for item in manifest.schedule]


def test_v170_authorization_binds_manifest_launcher_runner_and_v169_gate() -> None:
    authorization = (
        runner._REPOSITORY
        / "docs/audits/2026-09-05_deepseek-harness-v170-official-matrix-authorization.md"
    ).read_text(encoding="utf-8")
    assert hashlib.sha256(_MANIFEST.read_bytes()).hexdigest() in authorization
    assert hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest() in authorization
    assert hashlib.sha256(Path(launcher.__file__).read_bytes()).hexdigest() in authorization
    assert "33975720801" in authorization
    assert "c292325bad58d184537cc91a1673486df63eff95" in authorization


def test_v170_pre_provider_headroom_failure_preserves_cumulative_reopen_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "result"
    arguments = runner._parser().parse_args(["--post-merge-main-run-id", "1"])  # noqa: SLF001
    monkeypatch.setattr(runner, "_require_opt_in", lambda: None)
    monkeypatch.setattr(runner, "_require_clean_merged_main", lambda _manifest: "a" * 40)
    monkeypatch.setattr(runner, "_validate_predecessor", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner, "_validate_task_bindings", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(runner, "_load_exact_tokenizer", lambda *_args, **_kwargs: (object(), "1"))
    monkeypatch.setattr(runner, "_new_output", lambda _path: output)
    monkeypatch.setattr(
        runner,
        "_host_headroom_receipt",
        lambda _manifest: {
            "status": "rejected_insufficient_headroom",
            "receipt_hash": "b" * 64,
        },
    )
    monkeypatch.setattr(
        runner,
        "_validate_host_runtime",
        lambda _manifest: pytest.fail("Docker access crossed the headroom gate"),
    )
    monkeypatch.setenv(harness_config.API_KEY_ENV, "provider-key")
    monkeypatch.setenv(harness_config.BASE_URL_ENV, "https://provider.example.invalid")
    output.mkdir(mode=0o700)
    report = runner.collect(arguments)
    assert report["status"] == "stopped_pending_independent_v171_audit"
    assert report["provider_call_count"] == 0
    assert report["provider_episode_count"] == 0
    assert report["v158_data_volume_reopen_count"] == 4
    assert report["v158_data_volume_reopen_budget"] == 5
    assert report["requires_independent_v171_audit"] is True


def test_v170_final_report_keeps_training_and_import_closed() -> None:
    manifest = load_v170_official_matrix_manifest(_MANIFEST)
    state = new_matrix_state([item.task_id for item in manifest.schedule])
    report = runner._final_report(  # noqa: SLF001
        manifest,
        {
            "matrix_state": state.model_dump(mode="json"),
            "status": "stopped",
            "stop_reason": "campaign_infrastructure_failure",
            "dind_cleanup_confirmed": True,
        },
        [],
    )
    assert report["status"] == "stopped_pending_independent_v171_audit"
    assert report["candidate_sft_import_authorized"] is False
    assert report["formal_collection_allowed"] is False
    assert report["formal_collection_started"] is False
    assert report["collection_started"] is False
    assert report["training_started"] is False
    assert report["production_training_ready"] is False


class _GuardedEnvironment(dict[str, str]):
    def __getitem__(self, key: str) -> str:
        blocked_aliases = set(ZERO_PROVIDER_CONFIGURATION_ENV_NAMES) - {
            harness_config.API_KEY_ENV,
            harness_config.BASE_URL_ENV,
        }
        if key in blocked_aliases:
            raise AssertionError(f"blocked provider alias value read: {key}")
        return super().__getitem__(key)

    def get(self, key: str, default: str | None = None) -> str | None:
        return self[key] if key in self else default


def test_v170_launcher_passes_only_exact_provider_names_without_reading_aliases() -> None:
    source = _GuardedEnvironment(
        {
            "PATH": "/safe/bin",
            harness_config.API_KEY_ENV: "provider-key",
            harness_config.BASE_URL_ENV: "https://provider.example.invalid",
            "OPENAI_API_KEY": "must-not-read",
            "DOCKER_HOST": "must-not-read",
        }
    )
    child = launcher._sanitized_child_environment(source)  # noqa: SLF001
    present = {name for name in ZERO_PROVIDER_CONFIGURATION_ENV_NAMES if name in child}
    assert present == {harness_config.API_KEY_ENV, harness_config.BASE_URL_ENV}
    assert "DOCKER_HOST" not in child
    assert child[runner.CHILD_BOUNDARY_ENV] == "1"


def test_v170_manifest_does_not_persist_provider_environment_names() -> None:
    encoded = _MANIFEST.read_text(encoding="utf-8")
    assert harness_config.API_KEY_ENV not in encoded
    assert harness_config.BASE_URL_ENV not in encoded
    assert 'formal_collection_allowed": false' in encoded

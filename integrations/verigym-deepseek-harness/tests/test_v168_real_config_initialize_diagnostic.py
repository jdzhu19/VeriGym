from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest
from verigym_deepseek_harness.config import API_KEY_ENV, BASE_URL_ENV
from verigym_deepseek_harness.process import (
    DeepSeekHarnessProcessError,
    DeepSeekHarnessProcessResult,
)

from scripts import launch_hwe_deepseek_harness_v168_real_config_initialize_diagnostic as launcher
from scripts import run_hwe_deepseek_harness_v168_real_config_initialize_diagnostic as runner
from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness_campaign import (
    V164_CONTROLLER_DIAGNOSTIC_CATEGORIES,
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
    DeepSeekHarnessV168RealConfigInitializeDiagnosticManifest,
    load_v168_real_config_initialize_diagnostic_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v168_real_config_initialize_diagnostic_v1.json"
)
_AUTHORIZATION = _REPOSITORY_ROOT / (
    "docs/audits/2026-09-05_deepseek-harness-v168-real-config-diagnostic-authorization.md"
)


class _UnreadableBlockedAliases(Mapping[str, str]):
    def __init__(self, values: Mapping[str, str], unreadable: set[str]) -> None:
        self._values = dict(values)
        self._unreadable = unreadable

    def __getitem__(self, name: str) -> str:
        if name in self._unreadable:
            raise AssertionError("a blocked alias value was read")
        return self._values[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def _settings(manifest: object) -> SimpleNamespace:
    return SimpleNamespace(
        configuration_fingerprint="1" * 64,
        controller_image_id=manifest.controller_image_id,
        controller_image_provenance="audited_offline_canonical_tag_load_v1",
        controller_image_source_receipt_hash=manifest.controller_image_source_receipt_hash,
        docker_host=manifest.nested_docker_host,
    )


def _initialize_result(
    *, events: tuple[dict[str, object], ...] = ()
) -> DeepSeekHarnessProcessResult:
    return DeepSeekHarnessProcessResult(
        events=events,
        session_id="v166-zero-provider-preflight",
        finish_reason=None,
        final_response="",
        duration_s=0.1,
        helper_exit_code=0,
        stdout_bytes=32,
        stderr_bytes=0,
        format_repairs=(),
        run_interval_count=0,
        provider_request_started=False,
    )


def test_checked_in_v168_manifest_is_real_config_but_zero_request() -> None:
    manifest = load_v168_real_config_initialize_diagnostic_manifest(_MANIFEST)

    assert manifest.identity == runner.IDENTITY
    assert manifest.v167_post_merge_main_run_id == 33973532777
    assert manifest.v158_data_volume_reopen_budget == 4
    assert manifest.v158_data_volume_reopen_count_before == 3
    assert tuple(manifest.provider_environment_names) == ZERO_PROVIDER_CONFIGURATION_ENV_NAMES
    assert tuple(manifest.diagnostic_categories) == V164_CONTROLLER_DIAGNOSTIC_CATEGORIES
    assert manifest.synthetic_provider_values_only is False
    assert manifest.provider_credentials_available is True
    assert manifest.real_provider_configuration_required is True
    assert manifest.real_provider_environment_value_count == 2
    assert manifest.provider_request_allowed is False
    assert manifest.provider_call_count == 0
    assert manifest.task_execution_allowed is False
    assert manifest.base_reference_verification_allowed is False
    assert manifest.official_verifier_execution_allowed is False
    assert manifest.registry_access_allowed is False
    assert manifest.partial_archive_allowed is False
    assert manifest.requires_independent_v169_audit is True
    assert manifest.formal_collection_allowed is False
    assert manifest.formal_collection_started is False
    assert manifest.collection_started is False
    assert manifest.training_started is False
    assert manifest.production_training_ready is False


def test_v168_manifest_hash_rejects_any_request_policy_mutation() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    value["provider_request_allowed"] = True
    value["manifest_hash"] = content_hash(
        {key: item for key, item in value.items() if key != "manifest_hash"}
    )

    with pytest.raises(ValueError):
        DeepSeekHarnessV168RealConfigInitializeDiagnosticManifest.model_validate(value)


def test_v168_authorization_binds_manifest_launcher_runner_and_v167_gate() -> None:
    authorization = _AUTHORIZATION.read_text(encoding="utf-8")
    assert hashlib.sha256(_MANIFEST.read_bytes()).hexdigest() in authorization
    assert hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest() in authorization
    assert hashlib.sha256(Path(launcher.__file__).read_bytes()).hexdigest() in authorization
    assert "33973532777" in authorization


def test_v168_launcher_reads_only_the_two_required_blocked_values() -> None:
    aliases = set(ZERO_PROVIDER_CONFIGURATION_ENV_NAMES) - {API_KEY_ENV, BASE_URL_ENV}
    source = _UnreadableBlockedAliases(
        {
            "PATH": os.environ["PATH"],
            API_KEY_ENV: "real-key",
            BASE_URL_ENV: "https://provider.invalid/v1",
            "OPENAI_API_KEY": "must-not-be-read",
            "DOCKER_HOST": "must-not-be-read",
        },
        {"OPENAI_API_KEY", "DOCKER_HOST"},
    )

    child = launcher._sanitized_child_environment(source)  # noqa: SLF001

    assert child["PATH"] == os.environ["PATH"]
    assert child[API_KEY_ENV] == "real-key"
    assert child[BASE_URL_ENV] == "https://provider.invalid/v1"
    assert child[runner.OPT_IN_ENV] == "1"
    assert child[runner.CHILD_BOUNDARY_ENV] == "1"
    assert aliases.isdisjoint(child)
    assert "DOCKER_HOST" not in child


def test_v168_harness_probe_keeps_only_a_structured_error_category(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v168_real_config_initialize_diagnostic_manifest(_MANIFEST)
    monkeypatch.setattr(runner, "resolve_settings", lambda *_args, **_kwargs: _settings(manifest))

    def fail(*_args: object, **_kwargs: object) -> object:
        (tmp_path / "harness-session" / "private.json").write_text(
            "private controller diagnostic", encoding="utf-8"
        )
        raise DeepSeekHarnessProcessError(
            "sensitive lower-level diagnostic",
            category="helper_json_rpc_error",
        )

    monkeypatch.setattr(runner, "run_harness_helper", fail)
    diagnostic = runner._harness_initialize_probe(  # noqa: SLF001
        manifest,
        root=tmp_path,
        provider_values=("real-key", "https://provider.invalid/v1"),
    )

    assert diagnostic["helper_status"] == "failed"
    assert diagnostic["diagnostic_category"] == "helper_json_rpc_error"
    assert diagnostic["provider_calls"] == 0
    assert diagnostic["real_provider_configuration_used"] is True
    assert diagnostic["private_artifact_file_count_removed"] == 1
    assert not (tmp_path / "harness-session").exists()
    assert not (tmp_path / "harness-broker").exists()
    assert "sensitive lower-level diagnostic" not in json.dumps(diagnostic)
    assert "real-key" not in json.dumps(diagnostic)


def test_v168_harness_probe_rejects_a_provider_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v168_real_config_initialize_diagnostic_manifest(_MANIFEST)
    monkeypatch.setattr(runner, "resolve_settings", lambda *_args, **_kwargs: _settings(manifest))

    def marked(*_args: object, **_kwargs: object) -> DeepSeekHarnessProcessResult:
        (tmp_path / "harness-session" / "provider-request-started-v1.json").write_text(
            '{"format_id":"verigym_deepseek_harness_provider_request_started_v1",'
            '"provider_request_ordinal":1}',
            encoding="utf-8",
        )
        return _initialize_result()

    monkeypatch.setattr(runner, "run_harness_helper", marked)
    with pytest.raises(ConfigurationError, match="crossed the provider boundary"):
        runner._harness_initialize_probe(  # noqa: SLF001
            manifest,
            root=tmp_path,
            provider_values=("real-key", "https://provider.invalid/v1"),
        )
    assert not (tmp_path / "harness-session").exists()
    assert not (tmp_path / "harness-broker").exists()


def test_v168_harness_probe_rejects_nonempty_initialize_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v168_real_config_initialize_diagnostic_manifest(_MANIFEST)
    monkeypatch.setattr(runner, "resolve_settings", lambda *_args, **_kwargs: _settings(manifest))
    monkeypatch.setattr(
        runner,
        "run_harness_helper",
        lambda *_args, **_kwargs: _initialize_result(events=({"unexpected": True},)),
    )

    diagnostic = runner._harness_initialize_probe(  # noqa: SLF001
        manifest,
        root=tmp_path,
        provider_values=("real-key", "https://provider.invalid/v1"),
    )

    assert diagnostic["helper_status"] == "failed"
    assert diagnostic["diagnostic_category"] == "helper_result_identity_changed"
    assert diagnostic["provider_calls"] == 0


def test_v168_purge_rejects_and_removes_a_provider_value(tmp_path: Path) -> None:
    (tmp_path / "harness-session").mkdir()
    (tmp_path / "harness-session/private.json").write_text("contains-real-key", encoding="utf-8")
    (tmp_path / "harness-broker").mkdir()

    with pytest.raises(ConfigurationError, match="provider value reached private artifacts"):
        runner._purge_probe_roots(  # noqa: SLF001
            tmp_path,
            ("real-key", "https://provider.invalid/v1"),
            required=True,
        )
    assert not (tmp_path / "harness-session").exists()
    assert not (tmp_path / "harness-broker").exists()


def test_v168_source_has_no_task_verifier_or_provider_request_surface() -> None:
    source = Path(runner.__file__).read_text(encoding="utf-8")

    assert "run_hwe_task" not in source
    assert "verify_candidate" not in source
    assert 'mode="run"' not in source
    assert "import requests" not in source
    assert "from requests" not in source
    assert "urllib" not in source
    assert 'mode="initialize"' in source
    assert '"provider_calls": 0' in source
    assert '"replacement_provider_matrix_authorized": False' in source


def test_v168_final_report_keeps_all_training_and_collection_flags_closed() -> None:
    progress = {
        "status": "diagnosed",
        "diagnostic_category": "helper_json_rpc_error",
        "provider_calls": 0,
    }
    diagnostic = {"diagnostic_category": "helper_json_rpc_error"}

    report = runner._final_report(progress, diagnostic=diagnostic)  # noqa: SLF001

    assert report["status"] == "diagnosed_pending_independent_v169_audit"
    assert report["diagnosis_confirmed"] is True
    assert report["replacement_provider_matrix_authorized"] is False
    assert report["provider_calls"] == 0
    assert report["formal_collection_allowed"] is False
    assert report["formal_collection_started"] is False
    assert report["collection_started"] is False
    assert report["training_started"] is False
    assert report["production_training_ready"] is False

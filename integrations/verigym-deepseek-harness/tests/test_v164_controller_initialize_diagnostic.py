from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest
from verigym_deepseek_harness.process import (
    DeepSeekHarnessProcessError,
    DeepSeekHarnessProcessResult,
)

from scripts import launch_hwe_deepseek_harness_v164_controller_initialize_diagnostic as launcher
from scripts import run_hwe_deepseek_harness_v164_controller_initialize_diagnostic as runner
from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness_campaign import (
    V164_CONTROLLER_DIAGNOSTIC_CATEGORIES,
    ZERO_PROVIDER_CONFIGURATION_ENV_NAMES,
    DeepSeekHarnessV164ControllerInitializeDiagnosticManifest,
    load_v164_controller_initialize_diagnostic_manifest,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST = _REPOSITORY_ROOT / (
    "configs/training/qwen35_hwe_deepseek_harness_v164_controller_initialize_diagnostic_v1.json"
)
_AUTHORIZATION = _REPOSITORY_ROOT / (
    "docs/audits/2026-09-05_deepseek-harness-v164-controller-initialize-diagnostic-authorization.md"
)


class _UnreadableBlockedValues(Mapping[str, str]):
    def __init__(self, values: Mapping[str, str], blocked: set[str]) -> None:
        self._values = dict(values)
        self._blocked = blocked

    def __getitem__(self, name: str) -> str:
        if name in self._blocked:
            raise AssertionError("a blocked environment value was read")
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
        session_id="v164-controller-initialize-diagnostic",
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


def test_checked_in_v164_manifest_is_zero_provider_and_non_authorizing() -> None:
    manifest = load_v164_controller_initialize_diagnostic_manifest(_MANIFEST)

    assert manifest.identity == runner.IDENTITY
    assert manifest.v162_post_merge_main_run_id == 33967203488
    assert manifest.v163_post_merge_main_run_id == 33968340363
    assert manifest.v158_data_volume_reopen_budget == 2
    assert manifest.v158_data_volume_reopen_count_before == 1
    assert tuple(manifest.provider_environment_names) == ZERO_PROVIDER_CONFIGURATION_ENV_NAMES
    assert tuple(manifest.diagnostic_categories) == V164_CONTROLLER_DIAGNOSTIC_CATEGORIES
    assert manifest.synthetic_provider_values_only is True
    assert manifest.provider_credentials_available is False
    assert manifest.provider_request_allowed is False
    assert manifest.provider_call_count == 0
    assert manifest.task_execution_allowed is False
    assert manifest.base_reference_verification_allowed is False
    assert manifest.official_verifier_execution_allowed is False
    assert manifest.registry_access_allowed is False
    assert manifest.partial_archive_allowed is False
    assert manifest.requires_independent_v165_audit is True
    assert manifest.formal_collection_allowed is False
    assert manifest.formal_collection_started is False
    assert manifest.collection_started is False
    assert manifest.training_started is False
    assert manifest.production_training_ready is False


def test_v164_manifest_hash_rejects_any_policy_mutation() -> None:
    value = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    value["provider_request_allowed"] = True
    value["manifest_hash"] = content_hash(
        {key: item for key, item in value.items() if key != "manifest_hash"}
    )

    with pytest.raises(ValueError):
        DeepSeekHarnessV164ControllerInitializeDiagnosticManifest.model_validate(value)


def test_v164_authorization_binds_manifest_launcher_runner_and_v163_gate() -> None:
    authorization = _AUTHORIZATION.read_text(encoding="utf-8")
    assert hashlib.sha256(_MANIFEST.read_bytes()).hexdigest() in authorization
    assert hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest() in authorization
    assert hashlib.sha256(Path(launcher.__file__).read_bytes()).hexdigest() in authorization
    assert "33968340363" in authorization


def test_v164_launcher_does_not_read_blocked_values() -> None:
    blocked = set((*ZERO_PROVIDER_CONFIGURATION_ENV_NAMES, "DOCKER_HOST", "DOCKER_CONTEXT"))
    source = _UnreadableBlockedValues(
        {
            "PATH": os.environ["PATH"],
            "VERIGYM_DEEPSEEK_API_KEY": "must-not-be-read",
            "OPENAI_API_KEY": "must-not-be-read",
            "DOCKER_HOST": "must-not-be-read",
            "DOCKER_CONTEXT": "must-not-be-read",
        },
        blocked,
    )

    child = launcher._sanitized_child_environment(source)  # noqa: SLF001

    assert child["PATH"] == os.environ["PATH"]
    assert child[runner.OPT_IN_ENV] == "1"
    assert child[runner.CHILD_BOUNDARY_ENV] == "1"
    assert blocked.isdisjoint(child)


def test_v164_harness_probe_keeps_only_a_structured_error_category(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v164_controller_initialize_diagnostic_manifest(_MANIFEST)
    monkeypatch.setattr(runner, "resolve_settings", lambda *_args, **_kwargs: _settings(manifest))

    def fail(*_args: object, **_kwargs: object) -> object:
        (tmp_path / "harness-session" / "private.json").write_text(
            "private controller diagnostic", encoding="utf-8"
        )
        raise DeepSeekHarnessProcessError(
            "sensitive lower-level diagnostic",
            category="helper_transport_closed",
        )

    monkeypatch.setattr(runner, "run_harness_helper", fail)
    diagnostic = runner._harness_initialize_probe(  # noqa: SLF001
        manifest,
        root=tmp_path,
    )

    assert diagnostic["helper_status"] == "failed"
    assert diagnostic["diagnostic_category"] == "helper_transport_closed"
    assert diagnostic["provider_calls"] == 0
    assert diagnostic["private_artifact_file_count_removed"] == 1
    assert not (tmp_path / "harness-session").exists()
    assert not (tmp_path / "harness-broker").exists()
    assert "sensitive lower-level diagnostic" not in json.dumps(diagnostic)


def test_v164_harness_probe_rejects_nonempty_initialize_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v164_controller_initialize_diagnostic_manifest(_MANIFEST)
    monkeypatch.setattr(runner, "resolve_settings", lambda *_args, **_kwargs: _settings(manifest))
    monkeypatch.setattr(
        runner,
        "run_harness_helper",
        lambda *_args, **_kwargs: _initialize_result(events=({"unexpected": True},)),
    )

    diagnostic = runner._harness_initialize_probe(  # noqa: SLF001
        manifest,
        root=tmp_path,
    )

    assert diagnostic["helper_status"] == "failed"
    assert diagnostic["diagnostic_category"] == "helper_result_identity_changed"
    assert diagnostic["provider_calls"] == 0


def test_v164_purge_removes_nested_private_artifacts_deepest_first(tmp_path: Path) -> None:
    leaf = tmp_path / "harness-session/one/two"
    leaf.mkdir(parents=True)
    (leaf / "diagnostic.json").write_text("content", encoding="utf-8")
    (tmp_path / "harness-broker").mkdir()

    receipt = runner._purge_probe_roots(  # noqa: SLF001
        tmp_path,
        ("synthetic-key", "http://127.0.0.1:9/v1"),
        required=True,
    )

    assert receipt == {"file_count_removed": 1, "byte_count_removed": 7}
    assert not (tmp_path / "harness-session").exists()
    assert not (tmp_path / "harness-broker").exists()


def test_v164_direct_probe_accepts_normalized_no_new_privileges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_v164_controller_initialize_diagnostic_manifest(_MANIFEST)
    result = SimpleNamespace(
        exit_code=0,
        stdout="",
        stderr="",
        timed_out=False,
        output_truncated=False,
    )

    class _Engine:
        arguments: list[str] = []

        def __init__(self, *, docker_host: str) -> None:
            assert docker_host == manifest.nested_docker_host

        def create_container(self, arguments: list[str]) -> str:
            self.arguments = arguments
            return "container"

        def inspect_container(self, _container_id: str) -> dict[str, object]:
            return {
                "Config": {
                    "Image": manifest.controller_image_id,
                    "User": f"{os.getuid()}:{os.getgid()}",
                    "Env": ["PATH=/usr/local/bin:/usr/bin:/bin"],
                    "Labels": {
                        "org.verigym.managed": "true",
                        "verigym.owner": runner.IDENTITY,
                        "verigym.role": "controller-direct-probe",
                    },
                },
                "HostConfig": {
                    "ReadonlyRootfs": True,
                    "NetworkMode": manifest.provider_inner_network,
                    "CapDrop": ["ALL"],
                    "SecurityOpt": ["no-new-privileges:true"],
                    "PidMode": "",
                    "IpcMode": "private",
                    "PidsLimit": 512,
                    "Memory": 2 * 1024**3,
                    "NanoCpus": 2 * 10**9,
                    "Init": True,
                    "Tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=268435456,mode=1777"},
                },
                "Mounts": [
                    {
                        "Destination": destination,
                        "Source": source,
                        "RW": writable,
                    }
                    for destination, source, writable in (
                        ("/workspace", str(runner.DEEPSEEK_HARNESS_SOURCE_ROOT), False),
                        (
                            "/workspace/examples/jsonrpc-agent",
                            str(runner.PROCESS_MODULE.parent / "runtime"),
                            False,
                        ),
                        ("/sessions", str(tmp_path / "direct-session"), True),
                        ("/broker", str(tmp_path / "direct-broker"), True),
                    )
                ],
            }

        def start_container(self, _container_id: str) -> object:
            return result

        def wait_container(self, _container_id: str, *, timeout_s: int) -> object:
            assert timeout_s == manifest.direct_container_probe_timeout_seconds
            return SimpleNamespace(**{**result.__dict__, "stdout": "0\n"})

        def logs_container(self, _container_id: str, *, max_output_bytes: int) -> object:
            assert max_output_bytes == manifest.maximum_diagnostic_output_bytes
            return result

        def remove_container(self, _container_id: str) -> object:
            return result

        def close(self) -> None:
            return None

    monkeypatch.setattr(runner, "DockerCliEngine", _Engine)
    probe = runner._direct_container_probe(manifest, root=tmp_path)  # noqa: SLF001

    assert probe["status"] == "passed"
    assert probe["container_removed"] is True
    assert probe["provider_calls"] == 0


def test_v164_source_has_no_task_verifier_or_provider_request_surface() -> None:
    source = Path(runner.__file__).read_text(encoding="utf-8")

    assert "run_hwe_task" not in source
    assert "verify_candidate" not in source
    assert 'mode="run"' not in source
    assert "requests." not in source
    assert "urllib" not in source
    assert 'mode="initialize"' in source
    assert '"provider_calls": 0' in source
    assert '"replacement_provider_matrix_authorized": False' in source


def test_v164_final_report_keeps_all_training_and_collection_flags_closed() -> None:
    progress = {
        "status": "diagnosed",
        "diagnostic_category": "helper_transport_closed",
        "provider_calls": 0,
    }
    diagnostic = {"diagnostic_category": "helper_transport_closed"}

    report = runner._final_report(progress, diagnostic=diagnostic)  # noqa: SLF001

    assert report["status"] == "diagnosed_pending_independent_v165_audit"
    assert report["diagnosis_confirmed"] is True
    assert report["replacement_provider_matrix_authorized"] is False
    assert report["provider_calls"] == 0
    assert report["formal_collection_allowed"] is False
    assert report["formal_collection_started"] is False
    assert report["collection_started"] is False
    assert report["training_started"] is False
    assert report["production_training_ready"] is False

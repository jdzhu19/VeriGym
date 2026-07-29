from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from verigym.core.errors import ConfigurationError, PathPolicyError
from verigym.core.hashing import hash_bytes, hash_directory
from verigym.core.repository_candidate import (
    apply_repository_patch,
    build_repository_patch,
    freeze_repository_candidate,
    validate_repository_tree,
    verify_frozen_repository_candidate,
    verify_frozen_repository_candidate_offline,
)
from verigym.public_test_launcher import PublicTestError, execute_public_test, run_cli
from verigym.schemas.repository import (
    PublicTestCommand,
    RepositorySourceIdentity,
    RepositoryWorkspaceContract,
)
from verigym.schemas.suite import SuiteSourceConfig
from verigym.suites.repo_rtl.adapter import RepositoryRtlSuite


def _suite_records() -> list[tuple[RepositoryRtlSuite, object, object]]:
    suite = RepositoryRtlSuite()
    return [(suite, reference, suite.load_task(reference)) for reference in suite.discover()]


def test_packaged_repository_suite_is_frozen_licensed_and_hidden_separated() -> None:
    suite = RepositoryRtlSuite()
    assert suite.validate_source().valid
    references = list(suite.discover())
    assert [reference.id for reference in references] == [
        "repo-rtl/arbiter-reset-recovery",
        "repo-rtl/counter-wrap",
        "repo-rtl/pipeline-stall-backpressure",
    ]
    for reference in references:
        task = suite.load_task(reference)
        manifest = suite.repository_manifest(task)
        assets = suite.resolve_assets(task)
        visible = Path(assets.visible_root)
        assert manifest.source.license == "Apache-2.0"
        assert manifest.source.redistributable
        assert manifest.source.task_bundle_hash == hash_directory(
            suite._root_for(task.id),  # noqa: SLF001 - immutable fixture conformance
            excluded_names={"task.yaml"},
        )
        assert len(task.workspace.entrypoints) >= 3
        assert (visible / "TASK.md").is_file()
        assert (visible / "PUBLIC_TESTS.md").is_file()
        assert not (visible / "hidden").exists()
        assert not (visible / "reference").exists()
        assert not (visible / ".git").exists()
        assert len(assets.hidden_roots) == 1
        assert [mount.destination for mount in assets.read_only_mounts] == ["/verigym-public"]


def test_pipeline_reference_is_a_required_two_file_patch() -> None:
    suite = RepositoryRtlSuite()
    task = suite.load_task(
        next(reference for reference in suite.discover() if "pipeline-stall" in reference.id)
    )
    root = suite._root_for(task.id)  # noqa: SLF001 - fixture conformance
    patch = (root / "reference" / "reference.patch").read_text(encoding="utf-8")
    assert patch.count("--- a/") == 2
    assert "pipeline_stage.sv" in patch
    assert "pipeline_top.sv" in patch
    assert build_repository_patch(root / "repository", root / "reference" / "repository") == patch


def test_repository_source_and_workspace_schemas_fail_closed() -> None:
    valid = {
        "source_kind": "user_path",
        "repository_hash": "a" * 64,
        "task_bundle_hash": "b" * 64,
        "license": "Apache-2.0",
        "license_file": "LICENSE",
        "license_file_hash": "c" * 64,
        "attribution": "synthetic",
        "redistributable": True,
    }
    with pytest.raises(ValidationError, match="credential-free"):
        RepositorySourceIdentity.model_validate(
            {**valid, "upstream_url": "https://user:secret@example.test/repository"}
        )
    with pytest.raises(ValidationError, match="traverse"):
        RepositorySourceIdentity.model_validate({**valid, "license_file": "../LICENSE"})
    with pytest.raises(ValidationError, match="below repository"):
        RepositoryWorkspaceContract(
            editable_globs=["outside/**/*.sv"],
            read_only_globs=["repository/LICENSE"],
            forbidden_globs=[".git/**"],
            max_changed_files=1,
            max_patch_lines=10,
            max_candidate_bytes=1000,
            max_file_bytes=500,
        )
    with pytest.raises(ValidationError, match="overlap"):
        RepositoryWorkspaceContract(
            editable_globs=["repository/rtl/**/*.sv"],
            read_only_globs=["repository/LICENSE"],
            runtime_generated_globs=[".verigym_internal/**"],
            forbidden_globs=[".verigym_internal/**"],
            max_changed_files=1,
            max_patch_lines=10,
            max_candidate_bytes=1000,
            max_file_bytes=500,
        )
    with pytest.raises(ValidationError, match="Icarus"):
        PublicTestCommand(argv=["curl", "https://example.test"], timeout_s=1)
    with pytest.raises(ValidationError, match="absolute"):
        PublicTestCommand(argv=["iverilog", "/host/source.sv"], timeout_s=1)
    with pytest.raises(ValidationError, match="placeholder"):
        PublicTestCommand(argv=["iverilog", "{hidden}/testbench.sv"], timeout_s=1)
    for unsupported in ("allow_file_rename", "allow_mode_change", "allow_binary_files"):
        with pytest.raises(ValidationError):
            RepositoryWorkspaceContract(
                editable_globs=["repository/rtl/**/*.sv"],
                read_only_globs=["repository/LICENSE"],
                forbidden_globs=[".git/**"],
                max_changed_files=1,
                max_patch_lines=10,
                max_candidate_bytes=1000,
                max_file_bytes=500,
                **{unsupported: True},
            )


def test_candidate_freeze_is_canonical_and_replayable(tmp_path: Path) -> None:
    suite = RepositoryRtlSuite()
    task = suite.load_task(
        next(reference for reference in suite.discover() if "counter-wrap" in reference.id)
    )
    manifest = suite.repository_manifest(task)
    base = suite.base_repository(task)
    candidate = tmp_path / "candidate"
    shutil.copytree(base, candidate)
    source = candidate / "rtl" / "wrap_counter.sv"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            """            if (count == 4'hf) begin
                count <= 4'hf;
            end else begin
                count <= count + 4'h1;
            end""",
            "            count <= count + 4'h1;",
        ),
        encoding="utf-8",
    )
    run_root = tmp_path / "run"
    artifact_root = run_root / "artifacts"
    artifact_root.mkdir(parents=True)
    record = freeze_repository_candidate(
        task_id=task.id,
        base_repository=base,
        candidate_repository=candidate,
        contract=manifest.workspace,
        public_test_ids=["counter-wrap-public"],
        run_root=run_root,
        artifact_root=artifact_root,
    )
    expected = {
        "workspace_before.json",
        "workspace_after.json",
        "patch_summary.json",
        "repository_candidate.json",
    }
    assert {path.name for path in (artifact_root / "repository_candidate").iterdir()} == expected
    assert record.patch.reapply_exact
    assert record.patch.changed_files == ["rtl/wrap_counter.sv"]
    assert record.patch.patch_hash == hash_bytes((run_root / "repository.patch").read_bytes())
    verify_frozen_repository_candidate(
        base_repository=base,
        candidate_repository=candidate,
        patch_file=run_root / "repository.patch",
        record=record,
        contract=manifest.workspace,
    )
    verify_frozen_repository_candidate_offline(
        candidate_repository=candidate,
        patch_file=run_root / "repository.patch",
        record=record,
        contract=manifest.workspace,
    )


def test_offline_replay_supports_explicit_text_addition_and_deletion(
    tmp_path: Path,
) -> None:
    suite = RepositoryRtlSuite()
    task = suite.load_task(
        next(reference for reference in suite.discover() if "counter-wrap" in reference.id)
    )
    manifest = suite.repository_manifest(task)
    contract = manifest.workspace.model_copy(
        update={
            "allow_file_addition": True,
            "allow_file_deletion": True,
            "max_changed_files": 2,
        }
    )
    base = suite.base_repository(task)
    candidate = tmp_path / "candidate-add-delete"
    shutil.copytree(base, candidate)
    (candidate / "rtl" / "enable_gate.sv").unlink()
    (candidate / "rtl" / "replacement_gate.sv").write_text(
        "module replacement_gate(input logic value, output logic passed);\n"
        "    assign passed = value;\n"
        "endmodule\n",
        encoding="utf-8",
    )
    run_root = tmp_path / "run-add-delete"
    artifact_root = run_root / "artifacts"
    artifact_root.mkdir(parents=True)
    record = freeze_repository_candidate(
        task_id=task.id,
        base_repository=base,
        candidate_repository=candidate,
        contract=contract,
        public_test_ids=["counter-wrap-public"],
        run_root=run_root,
        artifact_root=artifact_root,
    )
    assert record.patch.added_files == ["rtl/replacement_gate.sv"]
    assert record.patch.deleted_files == ["rtl/enable_gate.sv"]
    verify_frozen_repository_candidate_offline(
        candidate_repository=candidate,
        patch_file=run_root / "repository.patch",
        record=record,
        contract=contract,
    )


@pytest.mark.parametrize(
    "patch",
    [
        "--- a/../../escape.sv\n+++ b/../../escape.sv\n@@ -1 +1 @@\n-x\n+y\n",
        "--- /tmp/source.sv\n+++ b/source.sv\n@@ -1 +1 @@\n-x\n+y\n",
        "--- a/source.sv\n+++ /workspace/elsewhere.sv\n@@ -1 +1 @@\n-x\n+y\n",
        "--- a/source.sv\t2026-01-01\n+++ b/source.sv\n@@ -1 +1 @@\n-x\n+y\n",
    ],
)
def test_patch_application_rejects_malicious_headers(tmp_path: Path, patch: str) -> None:
    (tmp_path / "source.sv").write_text("x\n", encoding="utf-8")
    with pytest.raises(PathPolicyError):
        apply_repository_patch(tmp_path, patch)
    assert not (tmp_path.parent / "escape.sv").exists()


def test_repository_tree_rejects_symlink_hardlink_git_and_case_collision(tmp_path: Path) -> None:
    suite = RepositoryRtlSuite()
    task = suite.load_task(next(iter(suite.discover())))
    contract = suite.repository_manifest(task).workspace
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    (unsafe / "one.sv").write_text("module one; endmodule\n", encoding="utf-8")
    (unsafe / "link.sv").symlink_to("one.sv")
    with pytest.raises(PathPolicyError, match="symlink"):
        validate_repository_tree(unsafe, contract)
    (unsafe / "link.sv").unlink()
    os.link(unsafe / "one.sv", unsafe / "two.sv")
    with pytest.raises(PathPolicyError, match="hardlink"):
        validate_repository_tree(unsafe, contract)
    (unsafe / "two.sv").unlink()
    (unsafe / ".git").mkdir()
    (unsafe / ".git" / "config").write_text("secret-shaped metadata\n", encoding="utf-8")
    with pytest.raises(PathPolicyError, match="forbidden"):
        validate_repository_tree(unsafe, contract)
    shutil.rmtree(unsafe / ".git")
    (unsafe / "ONE.sv").write_text("module other; endmodule\n", encoding="utf-8")
    with pytest.raises(PathPolicyError, match="case-colliding"):
        validate_repository_tree(unsafe, contract)
    (unsafe / "ONE.sv").unlink()
    os.mkfifo(unsafe / "pipe")
    with pytest.raises(PathPolicyError, match="special"):
        validate_repository_tree(unsafe, contract)


def test_candidate_changed_file_and_size_bounds_are_fail_closed(tmp_path: Path) -> None:
    suite = RepositoryRtlSuite()
    task = suite.load_task(
        next(reference for reference in suite.discover() if "counter-wrap" in reference.id)
    )
    manifest = suite.repository_manifest(task)
    base = suite.base_repository(task)
    candidate = tmp_path / "candidate"
    shutil.copytree(base, candidate)
    for name in ("counter_top.sv", "enable_gate.sv"):
        source = candidate / "rtl" / name
        source.write_text(
            source.read_text(encoding="utf-8") + "// candidate change\n",
            encoding="utf-8",
        )
    run = tmp_path / "run"
    (run / "artifacts").mkdir(parents=True)
    with pytest.raises(PathPolicyError, match="changes 2 files"):
        freeze_repository_candidate(
            task_id=task.id,
            base_repository=base,
            candidate_repository=candidate,
            contract=manifest.workspace,
            public_test_ids=["counter-wrap-public"],
            run_root=run,
            artifact_root=run / "artifacts",
        )
    oversized = tmp_path / "oversized"
    oversized.mkdir()
    with (oversized / "large.sv").open("wb") as stream:
        stream.truncate(manifest.workspace.max_file_bytes + 1)
    with pytest.raises(PathPolicyError, match="exceeds"):
        validate_repository_tree(oversized, manifest.workspace)


def test_public_launcher_lists_only_bound_ids_and_rejects_injection(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    suite = RepositoryRtlSuite()
    task = suite.load_task(
        next(reference for reference in suite.discover() if "counter-wrap" in reference.id)
    )
    root = suite._root_for(task.id)  # noqa: SLF001
    assets = suite.resolve_assets(task)
    public = root / "public"
    workspace = Path(assets.visible_root)
    exit_code, payload, _limit = execute_public_test(
        None,
        public_root=public,
        workspace_root=workspace,
    )
    assert exit_code == 0
    assert payload["tests"] == [
        {"id": "counter-wrap-public", "title": "Reset, wrap, and hold behavior"}
    ]
    for arguments in (
        ["run", "../hidden"],
        ["run", "counter-wrap-public", "extra"],
        ["run;cat", "TASK.md"],
        ["list", "unexpected"],
    ):
        assert run_cli(arguments, public_root=public, workspace_root=workspace) == 2
        assert "launcher_error" in capsys.readouterr().out
    with pytest.raises(PublicTestError, match="unknown"):
        execute_public_test(
            "undeclared",
            public_root=public,
            workspace_root=workspace,
        )
    altered_public = tmp_path / "public"
    shutil.copytree(public, altered_public)
    contract_path = altered_public / "test-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["tests"][0]["commands"][0]["argv"][0] = "bin/iverilog"
    contract_path.write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(PublicTestError, match="strict allowlist"):
        execute_public_test(
            "counter-wrap-public",
            public_root=altered_public,
            workspace_root=workspace,
        )


@pytest.mark.parametrize(
    ("program", "expected_category"),
    [
        ("print('x' * 4096)\n", "output_limit"),
        ("import time\ntime.sleep(2)\n", "timeout"),
    ],
)
def test_public_launcher_enforces_output_and_timeout_bounds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    program: str,
    expected_category: str,
) -> None:
    suite = RepositoryRtlSuite()
    task = suite.load_task(
        next(reference for reference in suite.discover() if "counter-wrap" in reference.id)
    )
    source_root = suite._root_for(task.id)  # noqa: SLF001
    public = tmp_path / "public"
    workspace = tmp_path / "workspace"
    shutil.copytree(source_root / "public", public)
    shutil.copytree(source_root / "repository", workspace / "repository")
    contract_path = public / "test-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["max_feedback_bytes"] = 1024
    contract["tests"][0]["commands"] = [
        {
            "argv": ["iverilog"],
            "cwd": "build",
            "timeout_s": 1,
            "expected_exit_code": 0,
        }
    ]
    contract_path.write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tools = tmp_path / "tools"
    tools.mkdir()
    executable = tools / "iverilog"
    executable.write_text(f"#!{sys.executable}\n{program}", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setattr(
        "verigym.public_test_launcher.TOOLCHAIN_PATH",
        f"{tools}:{os.defpath}",
    )
    exit_code, payload, _limit = execute_public_test(
        "counter-wrap-public",
        public_root=public,
        workspace_root=workspace,
    )
    assert exit_code == 1
    assert payload["category"] == expected_category
    assert payload["ephemeral_build_removed"] is True


def test_explicit_local_source_uses_same_generic_adapter(tmp_path: Path) -> None:
    packaged = RepositoryRtlSuite()
    source = tmp_path / "source" / "tasks" / "counter"
    shutil.copytree(
        packaged._root_for("repo-rtl/counter-wrap"),  # noqa: SLF001
        source,
    )
    task_path = source / "task.yaml"
    text = task_path.read_text(encoding="utf-8").replace(
        "source_kind: package_resource",
        "source_kind: user_path",
    )
    task_path.write_text(text, encoding="utf-8")
    from scripts.reseal_repo_rtl_assets import reseal

    reseal(source)
    suite = RepositoryRtlSuite(
        SuiteSourceConfig(
            source_root=tmp_path / "source",
            variant="repo-rtl-v1",
        )
    )
    assert suite.validate_source().valid
    assert [reference.id for reference in suite.discover()] == ["repo-rtl/counter-wrap"]
    snapshot = suite.source_snapshot()
    assert snapshot is not None
    assert snapshot.source_root == "<external-repo-rtl-source>"
    assert snapshot.dataset_content_hash == hash_directory(tmp_path / "source" / "tasks")


def test_external_bundle_rejects_symlinks_before_loading(tmp_path: Path) -> None:
    packaged = RepositoryRtlSuite()
    source = tmp_path / "source" / "tasks" / "counter"
    shutil.copytree(packaged._root_for("repo-rtl/counter-wrap"), source)  # noqa: SLF001
    (source / "leak").symlink_to("/etc/passwd")
    suite = RepositoryRtlSuite(SuiteSourceConfig(source_root=tmp_path / "source"))
    report = suite.validate_source()
    assert not report.valid
    assert any("symlinks" in error for error in report.errors)


def test_external_bundle_rejects_symlink_task_root(tmp_path: Path) -> None:
    packaged = RepositoryRtlSuite()
    actual = tmp_path / "actual-counter"
    shutil.copytree(packaged._root_for("repo-rtl/counter-wrap"), actual)  # noqa: SLF001
    tasks = tmp_path / "source" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "counter").symlink_to(actual, target_is_directory=True)
    with pytest.raises(ConfigurationError, match="symlink"):
        RepositoryRtlSuite(SuiteSourceConfig(source_root=tmp_path / "source"))


def test_external_bundle_rejects_oversized_assets(tmp_path: Path) -> None:
    packaged = RepositoryRtlSuite()
    source = tmp_path / "source" / "tasks" / "counter"
    shutil.copytree(packaged._root_for("repo-rtl/counter-wrap"), source)  # noqa: SLF001
    with (source / "hidden" / "oversized.bin").open("wb") as stream:
        stream.truncate(8 * 1024 * 1024 + 1)
    suite = RepositoryRtlSuite(SuiteSourceConfig(source_root=tmp_path / "source"))
    report = suite.validate_source()
    assert not report.valid
    assert any("asset limits" in error for error in report.errors)

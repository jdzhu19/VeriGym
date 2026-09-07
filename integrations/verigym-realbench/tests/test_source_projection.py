"""Synthetic sources exercise projection, not native RealBench correctness."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError
from verigym_cadence.protocol import bounded_read
from verigym_realbench.adapter import RealBenchSuite
from verigym_realbench.source import (
    LOCK_NAME,
    ModuleTask,
    SourceAsset,
    SourceLock,
    load_source,
)

from verigym.core.public_test_profiles import validate_required_public_test_profile
from verigym.core.repository_candidate import (
    repository_plan_identity,
    repository_workspace_contract,
)
from verigym.core.verifier_profiles import validate_required_verifier_profile
from verigym.plugin_api import ConfigurationError, PathPolicyError, hash_bytes
from verigym.schemas.suite import SuiteSourceConfig


def source_fixture(root: Path) -> SourceLock:
    (root / "LICENSE").write_text("Synthetic test license\n", encoding="utf-8")
    (root / "benchmark_info.py").write_text("raise RuntimeError('must not execute')\n")
    tasks = []
    for kind in ("combinational", "sequential", "hierarchical"):
        assets = []
        definitions = [
            (
                "spec",
                "spec.md",
                b"# Public specification\n![ports](ports.png)\n",
                "repository/spec/spec.md",
            ),
            (
                "image",
                "ports.png",
                b"\x89PNG\r\n\x1a\nSYNTHETIC_IMAGE",
                "repository/spec/ports.png",
            ),
            (
                "stub",
                "candidate.sv",
                b"module top(input a, output y); endmodule\n",
                "repository/rtl/top.sv",
            ),
            ("reference", "reference.sv", b"PRIVATE_GOLDEN_CANARY", None),
            ("verification", "testbench.sv", b"PRIVATE_TESTBENCH_CANARY", None),
            ("template", "sec.tcl", b"PRIVATE_TCL_CANARY", None),
        ]
        if kind == "hierarchical":
            definitions.append(
                ("stub", "child.sv", b"module child; endmodule\n", "repository/rtl/child.sv")
            )
        for role, name, data, destination in definitions:
            relative = f"{kind}/{name}"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            assets.append(
                SourceAsset.model_validate(
                    {
                        "path": relative,
                        "sha256": hash_bytes(data),
                        "role": role,
                        "destination": destination,
                    }
                )
            )
        tasks.append(ModuleTask(native_id=f"fixture/{kind}", top="top", kind=kind, assets=assets))
    lock = SourceLock(
        commit="0" * 40,
        license_path="LICENSE",
        license_sha256=hash_bytes(bounded_read(root / "LICENSE")),
        catalog_sha256=hash_bytes(bounded_read(root / "benchmark_info.py")),
        visibility_audit="Synthetic fixtures only; not official source qualification",
        synthetic_fixture=True,
        tasks=tasks,
    )
    (root / LOCK_NAME).write_text(lock.model_dump_json(), encoding="utf-8")
    return lock


def test_three_kinds_project_only_explicit_public_assets_and_bind_multifile(tmp_path: Path) -> None:
    lock = source_fixture(tmp_path)
    suite = RealBenchSuite().with_source(SuiteSourceConfig(source_root=tmp_path))
    assert suite.validate_source().valid
    refs = list(suite.discover())
    assert len(refs) == 3
    for ref, manifest in zip(refs, lock.tasks, strict=True):
        task = suite.load_task(ref)
        assets = suite.resolve_assets(task)
        visible = Path(assets.visible_root)
        assert not assets.hidden_assets and not assets.hidden_roots
        assert (visible / "repository/spec/ports.png").read_bytes().startswith(b"\x89PNG")
        combined = b"".join(path.read_bytes() for path in visible.rglob("*") if path.is_file())
        assert b"PRIVATE_GOLDEN_CANARY" not in combined
        assert b"PRIVATE_TESTBENCH_CANARY" not in combined
        assert b"PRIVATE_TCL_CANARY" not in combined
        assert task.metadata["benchmark_score_claimed"] is False
        assert task.metadata["partition"] == "module"
        assert task.metadata["module_kind"] == manifest.kind
        if manifest.kind == "hierarchical":
            assert len(task.workspace.editable_globs) == 2
            assert task.interaction.final_submission.kind == "workspace"
        # A missing profile must not silently select lint-only or skip final formal.
        with pytest.raises(ConfigurationError):
            validate_required_public_test_profile(task, None)
        with pytest.raises(ConfigurationError):
            validate_required_verifier_profile(task, None)
    assert suite.source_snapshot().synthetic_fixture
    assert suite.source_snapshot().dataset_content_hash == lock.identity


def test_source_and_task_identity_drift_fail_closed(tmp_path: Path) -> None:
    lock = source_fixture(tmp_path)
    suite = RealBenchSuite(SuiteSourceConfig(source_root=tmp_path))
    task = suite.load_task(next(iter(suite.discover())))
    path = tmp_path / lock.tasks[0].assets[0].path
    path.write_bytes(b"changed public spec")
    assert not suite.validate_source().valid
    with pytest.raises(ConfigurationError):
        suite.resolve_assets(task)


def test_hidden_alias_and_destination_conflicts_are_rejected(tmp_path: Path) -> None:
    lock = source_fixture(tmp_path)
    payload = lock.model_dump()
    payload["tasks"][0]["assets"][2]["sha256"] = payload["tasks"][0]["assets"][3]["sha256"]
    with pytest.raises(ValidationError, match="aliased"):
        SourceLock.model_validate(payload)
    payload = lock.model_dump()
    payload["tasks"][0]["assets"][3]["destination"] = "repository/reference.sv"
    with pytest.raises(ValidationError, match="explicitly public"):
        SourceLock.model_validate(payload)
    payload = lock.model_dump()
    payload["tasks"][0]["assets"][0]["destination"] = "../outside.md"
    with pytest.raises(ValidationError):
        SourceLock.model_validate(payload)


def test_absent_encrypted_and_symlinked_assets_never_trigger_download_or_decrypt(
    tmp_path: Path,
) -> None:
    suite = RealBenchSuite(SuiteSourceConfig(source_root=tmp_path))
    assert not suite.validate_source().valid
    lock = source_fixture(tmp_path)
    target = tmp_path / lock.tasks[0].assets[0].path
    encrypted = target.with_suffix(".gpg")
    target.rename(encrypted)
    assert not suite.validate_source().valid
    target.symlink_to(encrypted)
    with pytest.raises(ValueError, match="symlink"):
        load_source(tmp_path)


def test_draft_refuses_unreviewed_revision_or_more_than_three_tasks(tmp_path: Path) -> None:
    lock = source_fixture(tmp_path)
    payload = lock.model_dump()
    payload["synthetic_fixture"] = False
    with pytest.raises(ValidationError, match="pinned"):
        SourceLock.model_validate(payload)
    payload = lock.model_dump()
    payload["tasks"].append(payload["tasks"][0])
    with pytest.raises(ValidationError):
        SourceLock.model_validate(payload)


def test_multifile_freeze_and_offline_replay_preserve_readonly_images(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    source_fixture(source)
    suite = RealBenchSuite(SuiteSourceConfig(source_root=source))
    task = suite.load_task(list(suite.discover())[2])
    assets = suite.resolve_assets(task)
    run = tmp_path / "run"
    run.mkdir()
    candidate = run / "candidate"
    shutil.copytree(assets.visible_root, candidate)
    for relative in task.workspace.editable_globs:
        with (candidate / relative).open("a", encoding="utf-8") as output:
            output.write("// synthetic candidate edit\n")
    record = suite.freeze_repository_candidate(
        task=task, candidate_dir=candidate, run_root=run, artifact_root=run / "artifacts"
    )
    assert record.patch.reapply_exact
    assert record.patch.changed_files == ["rtl/child.sv", "rtl/top.sv"]
    assert (
        repository_plan_identity(task) is None
    )  # No invented golden patch identity for generation.
    assert repository_workspace_contract(task).editable_globs == sorted(
        task.workspace.editable_globs
    )
    assert not record.hidden_assets_present and not record.reference_patch_used
    # Replay intentionally uses an adapter with no external source configuration or EDA tools.
    RealBenchSuite().replay_repository_candidate(
        task=task, candidate_dir=candidate, run_root=run, record=record
    )
    image = candidate / "repository/spec/ports.png"
    image.write_bytes(b"tampered image")
    with pytest.raises(ValueError):
        RealBenchSuite().replay_repository_candidate(
            task=task, candidate_dir=candidate, run_root=run, record=record
        )
    rejected = tmp_path / "rejected"
    rejected.mkdir()
    for relative in task.workspace.editable_globs:
        shutil.copyfile(Path(assets.visible_root) / relative, candidate / relative)
    with pytest.raises(PathPolicyError, match="read-only"):
        suite.freeze_repository_candidate(
            task=task,
            candidate_dir=candidate,
            run_root=rejected,
            artifact_root=rejected / "artifacts",
        )


def test_functional_notice_is_hash_bound_and_final_verification_requires_submission(
    tmp_path: Path,
) -> None:
    source_fixture(tmp_path)
    suite = RealBenchSuite(SuiteSourceConfig(source_root=tmp_path))
    task = suite.load_task(next(iter(suite.discover())))
    assets = suite.resolve_assets(task)
    notice = (Path(assets.visible_root) / "PUBLIC_TESTS.md").read_bytes()
    assert b"both syntax and functional checks" in notice
    assert b"syntax/elaboration only" not in notice
    assert task.metadata["public_feedback_notice_sha256"] == hash_bytes(notice)
    assert task.metadata["verification_requires_final_submission"] is True

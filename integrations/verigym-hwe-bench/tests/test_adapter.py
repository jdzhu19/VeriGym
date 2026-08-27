from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
from verigym.plugin_api import (
    Candidate,
    SuiteSourceConfig,
    content_hash,
    hash_bytes,
    hash_directory,
)

from verigym_hwe_bench import HweBenchSuite
from verigym_hwe_bench import adapter as adapter_module
from verigym_hwe_bench.dataset import NATIVE_LAYOUT_V1, VARIANT, load_catalog
from verigym_hwe_bench.models import HweInstance, ImageLock, ImageLockEntry


def _source(tmp_path: Path) -> tuple[Path, HweInstance]:
    root = tmp_path / "source"
    repository = root / "workspaces" / "lowRISC__ibex__pr-1" / "repository"
    (repository / "rtl").mkdir(parents=True)
    (repository / "LICENSE").write_text("Apache-2.0\n", encoding="utf-8")
    (repository / "rtl" / "demo.sv").write_text("assign y = 1'b0;\n", encoding="utf-8")
    workspace = repository.parent
    (workspace / "TASK.md").write_text("# Repair\n", encoding="utf-8")
    (workspace / "PUBLIC_TESTS.md").write_text("# None\n", encoding="utf-8")
    instance = HweInstance(
        org="lowRISC",
        repo="ibex",
        number=1,
        title="Repair demo",
        problem_statement="Make the output follow the input.",
        base_commit="1" * 40,
        fix_patch=(
            "diff --git a/rtl/demo.sv b/rtl/demo.sv\n"
            "--- a/rtl/demo.sv\n"
            "+++ b/rtl/demo.sv\n"
            "@@ -1 +1 @@\n"
            "-assign y = 1'b0;\n"
            "+assign y = a;\n"
        ),
        tb_script="SECRET_TESTBENCH_CONTENT\n",
        modified_files=["rtl/demo.sv"],
        expected_test_ids=["secret_test"],
    )
    reference = Candidate(
        files={"repository/rtl/demo.sv": "assign y = a;\n"},
        label="official-reference-conformance-only",
    )
    repository_hash = hash_directory(repository)
    image_id = f"sha256:{'2' * 64}"
    digest = f"sha256:{'3' * 64}"
    runtime_base_commit = "a" * 40
    task_bundle_hash = content_hash(
        {
            "instance": instance,
            "repository_hash": repository_hash,
            "image_id": image_id,
            "manifest_digest": digest,
            "runtime_base_commit": runtime_base_commit,
        }
    )
    entry = ImageLockEntry(
        instance_id=instance.instance_id,
        slug=instance.slug,
        image_reference="ghcr.io/pku-liang/lowrisc_m_ibex:pr-1",
        manifest_digest=digest,
        image_id=image_id,
        repository_home="/home/ibex",
        base_commit=runtime_base_commit,
        repository_hash=repository_hash,
        reference_repository_hash="4" * 64,
        reference_candidate_hash=content_hash(reference),
        reference_patch_hash=hash_bytes(instance.fix_patch.encode()),
        verifier_payload_hash=content_hash(
            {
                "test_patch": "",
                "tb_script": instance.tb_script,
                "expected_test_ids": instance.expected_test_ids,
                "semantics": "all_tests_pass",
            }
        ),
        task_bundle_hash=task_bundle_hash,
        license_file_hash=hash_bytes((repository / "LICENSE").read_bytes()),
    )
    (root / "instances.jsonl").write_text(
        json.dumps(instance.model_dump(mode="json"), sort_keys=True) + "\n", encoding="utf-8"
    )
    (root / "image-lock.json").write_text(
        ImageLock(official_dataset_sha256="5" * 64, entries=[entry]).model_dump_json(indent=2)
        + "\n",
        encoding="utf-8",
    )
    return root, instance


def test_adapter_keeps_hidden_verifier_and_reference_out_of_task_and_workspace(
    tmp_path: Path,
) -> None:
    root, instance = _source(tmp_path)
    suite = HweBenchSuite().with_source(SuiteSourceConfig(source_root=root, variant=VARIANT))
    assert suite.validate_source().valid
    ref = list(suite.discover())[0]
    task = suite.load_task(ref)
    assets = suite.resolve_assets(task)
    serialized = task.model_dump_json()
    visible_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path(assets.visible_root).rglob("*")
        if path.is_file()
    )

    assert instance.tb_script not in serialized
    assert instance.fix_patch not in serialized
    assert task.workspace.entrypoints == []
    assert task.budget.max_model_calls == 128
    assert task.budget.max_tool_calls == 512
    assert task.budget.max_turns == 128
    assert "SECRET_TESTBENCH_CONTENT" not in visible_text
    assert task.metadata["repository_repair"]["hidden_verifier_hash"]
    assert suite.reference_solution(task) == Candidate(
        files={"repository/rtl/demo.sv": "assign y = a;\n"},
        label="official-reference-conformance-only",
    )


def test_adapter_preserves_canonical_modes_under_restrictive_umask(tmp_path: Path) -> None:
    root, _instance = _source(tmp_path)
    suite = HweBenchSuite().with_source(SuiteSourceConfig(source_root=root, variant=VARIANT))
    task = suite.load_task(list(suite.discover())[0])

    previous_umask = os.umask(0o077)
    try:
        assets = suite.resolve_assets(task)
        run_root = tmp_path / "run"
        artifact_root = run_root / "artifacts"
        artifact_root.mkdir(parents=True)
        record = suite.freeze_repository_candidate(
            task=task,
            candidate_dir=Path(assets.visible_root),
            run_root=run_root,
            artifact_root=artifact_root,
        )
    finally:
        os.umask(previous_umask)

    visible = Path(assets.visible_root)
    assert visible.joinpath("repository", "LICENSE").stat().st_mode & 0o7777 == 0o644
    assert visible.joinpath("repository", "rtl", "demo.sv").stat().st_mode & 0o7777 == 0o644
    assert record is not None
    assert record.patch.changed_files == []
    assert record.patch.mode_changed_files == []
    assert record.patch.reapply_exact


def test_v1_prepared_source_remains_loadable_with_compatible_task_id(tmp_path: Path) -> None:
    root, instance = _source(tmp_path)
    catalog = load_catalog(root)
    suite = HweBenchSuite().with_source(SuiteSourceConfig(source_root=root, variant=VARIANT))

    assert catalog.native_layout == NATIVE_LAYOUT_V1
    assert catalog.lock.format_id == "verigym_hwe_bench_source_v1"
    assert list(suite.discover())[0].id == f"hwe-bench/{VARIANT}/{instance.slug}"


def test_adapter_uses_configured_tempdir_instead_of_source_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _instance = _source(tmp_path / "sealed")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setenv("TMPDIR", str(scratch))
    monkeypatch.setattr(tempfile, "tempdir", None)
    original = tempfile.TemporaryDirectory
    requested_parents: list[object] = []

    def tracked_temporary_directory(*args: object, **kwargs: object) -> object:
        requested_parents.append(kwargs.get("dir"))
        return original(*args, **kwargs)

    monkeypatch.setattr(adapter_module.tempfile, "TemporaryDirectory", tracked_temporary_directory)
    suite = HweBenchSuite().with_source(SuiteSourceConfig(source_root=root, variant=VARIANT))
    task = suite.load_task(list(suite.discover())[0])

    assets = suite.resolve_assets(task)
    assert Path(assets.visible_root).parent == scratch.resolve()
    assert suite.reference_solution(task) is not None
    assert requested_parents == [None, None]

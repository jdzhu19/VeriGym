from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from verigym.plugin_api import ConfigurationError, hash_bytes

from verigym_hwe_bench import prepare
from verigym_hwe_bench.models import HweInstance, VerifierDependencyFile, repository_profile
from verigym_hwe_bench.prepare import (
    _apply_workspace_exclusions,
    _image_baseline,
    _materialize_internal_file_symlinks,
    _prepare_verifier_dependencies,
    _reference_candidate_files,
    _resolve_image_identity,
    reference_patch_compatibility,
)


def _patch_instance(*, patch: str, modified_files: list[str]) -> HweInstance:
    return HweInstance(
        org="openhwgroup",
        repo="cva6",
        number=1,
        title="fixture",
        problem_statement="fixture",
        base_commit="1" * 40,
        fix_patch=patch,
        tb_script="echo test\n",
        modified_files=modified_files,
        expected_test_ids=["test"],
        language="SystemVerilog",
        license_id="SHL-0.51",
    )


_TEXT_EDIT_PATCH = """diff --git a/rtl/a.sv b/rtl/a.sv
index 7898192..422c2b7 100644
--- a/rtl/a.sv
+++ b/rtl/a.sv
@@ -1 +1 @@
-a
+b
"""

_TEXT_ADD_PATCH = """diff --git a/rtl/new.sv b/rtl/new.sv
new file mode 100644
index 0000000..6178079
--- /dev/null
+++ b/rtl/new.sv
@@ -0,0 +1 @@
+new
"""

_TEXT_DELETE_PATCH = """diff --git a/rtl/old.sv b/rtl/old.sv
deleted file mode 100644
index 3367afd..0000000
--- a/rtl/old.sv
+++ /dev/null
@@ -1 +0,0 @@
-old
"""


def test_reference_patch_preflight_accepts_text_edits_and_additions() -> None:
    edit = reference_patch_compatibility(
        _patch_instance(patch=_TEXT_EDIT_PATCH, modified_files=["rtl/a.sv"])
    )
    addition = reference_patch_compatibility(
        _patch_instance(patch=_TEXT_ADD_PATCH, modified_files=["rtl/new.sv"])
    )

    assert edit.compatible is True
    assert edit.reason == "compatible"
    assert edit.created_file_count == 0
    assert addition.compatible is True
    assert addition.created_file_count == 1
    assert addition.raw_output_persisted is False
    assert addition.network_accessed is False
    assert addition.docker_accessed is False


@pytest.mark.parametrize(
    ("patch", "modified_files", "reason"),
    [
        (_TEXT_DELETE_PATCH, ["rtl/old.sv"], "deleted_file"),
        (
            """diff --git a/rtl/a.sv b/rtl/b.sv
similarity index 100%
rename from rtl/a.sv
rename to rtl/b.sv
""",
            ["rtl/b.sv"],
            "renamed_file",
        ),
        (
            """diff --git a/rtl/a.sv b/rtl/a.sv
old mode 100644
new mode 100755
""",
            ["rtl/a.sv"],
            "mode_change",
        ),
        (
            """diff --git a/rtl/a.sv b/rtl/b.sv
similarity index 100%
copy from rtl/a.sv
copy to rtl/b.sv
""",
            ["rtl/b.sv"],
            "copied_file",
        ),
        (
            """diff --git a/rtl/link.sv b/rtl/link.sv
new file mode 120000
index 0000000..945c9b4
--- /dev/null
+++ b/rtl/link.sv
@@ -0,0 +1 @@
+target.sv
\\ No newline at end of file
""",
            ["rtl/link.sv"],
            "non_regular_file_creation",
        ),
        (
            """diff --git a/rtl/blob b/rtl/blob
new file mode 100644
index 0000000..e69de29
Binary files /dev/null and b/rtl/blob differ
""",
            ["rtl/blob"],
            "binary_patch",
        ),
        (_TEXT_EDIT_PATCH, ["rtl/not-a.sv"], "modified_file_manifest_mismatch"),
        ("not a unified patch\n", ["rtl/a.sv"], "malformed_patch_metadata"),
    ],
)
def test_reference_patch_preflight_rejects_unrepresentable_shapes(
    patch: str, modified_files: list[str], reason: str
) -> None:
    result = reference_patch_compatibility(
        _patch_instance(patch=patch, modified_files=modified_files)
    )

    assert result.compatible is False
    assert result.reason == reason


def test_reference_candidate_files_materializes_text_addition(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    added = repository / "rtl" / "new.sv"
    added.parent.mkdir(parents=True)
    added.write_text("module new; endmodule\n", encoding="utf-8")

    assert _reference_candidate_files(repository, ["rtl/new.sv"]) == {
        "repository/rtl/new.sv": "module new; endmodule\n"
    }


def test_prepare_source_rejects_incompatible_patch_before_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("{}\n", encoding="utf-8")
    instance = _patch_instance(patch=_TEXT_DELETE_PATCH, modified_files=["rtl/old.sv"])
    monkeypatch.setattr(prepare, "_official_instances", lambda _dataset, _selected: [instance])
    monkeypatch.setattr(
        prepare,
        "_inspect_image",
        lambda *_args, **_kwargs: pytest.fail("Docker must not run before patch preflight"),
    )

    with pytest.raises(ConfigurationError, match="deleted_file"):
        prepare.prepare_source(
            dataset=dataset,
            output=tmp_path / "prepared",
            selected_tasks=[instance.instance_id],
        )

    assert not (tmp_path / "prepared").exists()


def test_materialize_internal_file_symlink(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    target = repository / "rtl" / "shared.sv"
    link = repository / "dv" / "shared.sv"
    target.parent.mkdir(parents=True)
    link.parent.mkdir(parents=True)
    target.write_text("module shared; endmodule\n", encoding="utf-8")
    link.symlink_to(Path("../rtl/shared.sv"))

    _materialize_internal_file_symlinks(repository)

    assert not link.is_symlink()
    assert link.read_bytes() == target.read_bytes()


def test_reject_escaping_file_symlink(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    outside = tmp_path / "outside.sv"
    outside.write_text("secret\n", encoding="utf-8")
    os.symlink(outside, repository / "escape.sv")

    with pytest.raises(ConfigurationError, match="escaping symlink"):
        _materialize_internal_file_symlinks(repository)


def test_materialize_dangling_internal_symlink_as_git_blob(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    link = repository / "missing.sv"
    link.symlink_to(Path("rtl/missing.sv"))

    _materialize_internal_file_symlinks(repository)

    assert not link.is_symlink()
    assert link.read_bytes() == b"rtl/missing.sv"


def test_profile_workspace_exclusion_is_exact_and_contained(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    build = repository / "vendor" / "tool" / "build"
    keep = repository / "vendor" / "tool" / "source.cc"
    build.mkdir(parents=True)
    keep.write_text("keep\n", encoding="utf-8")
    (build / "large.a").write_bytes(b"artifact")

    _apply_workspace_exclusions(repository, ["vendor/tool/build"])

    assert not build.exists()
    assert keep.read_text(encoding="utf-8") == "keep\n"


def test_profile_workspace_exclusion_rejects_symlink(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (repository / "build").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ConfigurationError, match="missing or unsafe"):
        _apply_workspace_exclusions(repository, ["build"])

    assert outside.is_dir()


def test_profile_workspace_exclusion_accepts_absent_generated_directory(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()

    _apply_workspace_exclusions(repository, ["vendor/tool/build"])

    assert list(repository.iterdir()) == []


def test_profile_workspace_exclusion_rejects_existing_regular_file(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    build = repository / "build"
    build.write_text("unexpected node\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="missing or unsafe"):
        _apply_workspace_exclusions(repository, ["build"])

    assert build.is_file()


def test_daemonless_import_binding_recovers_manifest_identity() -> None:
    image_id = "sha256:" + "1" * 64
    manifest = "sha256:" + "2" * 64

    assert _resolve_image_identity(
        reference="ghcr.io/example/image:task",
        image={"Id": image_id, "RepoDigests": []},
        imported_binding={"image_id": image_id, "manifest_digest": manifest},
    ) == (image_id, manifest)


def test_daemonless_import_binding_rejects_local_or_registry_drift() -> None:
    image_id = "sha256:" + "1" * 64
    manifest = "sha256:" + "2" * 64
    with pytest.raises(ConfigurationError, match="binding changed"):
        _resolve_image_identity(
            reference="ghcr.io/example/image:task",
            image={"Id": "sha256:" + "3" * 64, "RepoDigests": []},
            imported_binding={"image_id": image_id, "manifest_digest": manifest},
        )
    with pytest.raises(ConfigurationError, match="registry digest conflicts"):
        _resolve_image_identity(
            reference="ghcr.io/example/image:task",
            image={
                "Id": image_id,
                "RepoDigests": ["ghcr.io/example/image@sha256:" + "4" * 64],
            },
            imported_binding={"image_id": image_id, "manifest_digest": manifest},
        )


def test_synthetic_runtime_baseline_is_bound_to_official_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    official = "1" * 40
    runtime = "2" * 40

    def fake_command(
        argv: list[str],
        *,
        timeout_s: int = 300,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        del timeout_s, input_bytes
        path = argv[-1]
        payload = official if path.endswith("/.baseline_commit") else runtime
        return subprocess.CompletedProcess(argv, 0, f"{payload}\n".encode(), b"")

    monkeypatch.setattr(prepare, "_command", fake_command)

    assert (
        _image_baseline(
            image_id=f"sha256:{'3' * 64}",
            repository_home="/home/ibex",
            base_commit=official,
        )
        == runtime
    )


def test_digest_locked_runtime_marker_policy_accepts_official_image_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    official = "1" * 40
    runtime = "2" * 40

    def fake_command(
        argv: list[str],
        *,
        timeout_s: int = 300,
        input_bytes: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        del timeout_s, input_bytes
        if argv[-1].endswith("/.baseline_commit"):
            return subprocess.CompletedProcess(argv, 1, b"", b"missing")
        return subprocess.CompletedProcess(argv, 0, f"{runtime}\n".encode(), b"")

    monkeypatch.setattr(prepare, "_command", fake_command)

    assert (
        _image_baseline(
            image_id=f"sha256:{'3' * 64}",
            repository_home="/home/ibex",
            base_commit=official,
            marker="/home/ibex_base_commit.txt",
            baseline_identity_policy="digest_locked_runtime_marker",
        )
        == runtime
    )


def test_prepare_verifier_dependencies_copies_only_profile_locked_files(
    tmp_path: Path,
) -> None:
    payload = b"public offline dependency\n"
    dependency = VerifierDependencyFile(
        cache_path="https/repo1.maven.org/maven2/org/example/demo/1.0/demo-1.0.jar",
        sha256=hash_bytes(payload),
        size_bytes=len(payload),
    )
    profile = repository_profile("chipsalliance/rocket-chip").model_copy(
        update={"verifier_dependencies": [dependency]}, deep=True
    )
    instance = HweInstance(
        org="chipsalliance",
        repo="rocket-chip",
        number=3065,
        title="fixture",
        problem_statement="fixture",
        base_commit="1" * 40,
        fix_patch="diff --git a/demo.scala b/demo.scala\n",
        tb_script="echo test\n",
        modified_files=["demo.scala"],
        expected_test_ids=["test"],
        language="Chisel/Scala",
        license_id="BSD-3-Clause AND Apache-2.0",
    )
    cache = tmp_path / "cache"
    source = cache / dependency.cache_path
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    prepared = tmp_path / "prepared"
    prepared.mkdir()

    inventory = _prepare_verifier_dependencies(
        cache_root=cache,
        prepared_root=prepared,
        instance=instance,
        profile=profile,
    )

    copied = prepared / "verifier-dependencies" / instance.slug / dependency.cache_path
    assert inventory == [dependency]
    assert copied.read_bytes() == payload


def test_prepare_verifier_dependencies_rejects_missing_or_tampered_cache(
    tmp_path: Path,
) -> None:
    dependency = VerifierDependencyFile(
        cache_path="https/repo1.maven.org/maven2/org/example/demo/1.0/demo-1.0.jar",
        sha256="1" * 64,
        size_bytes=4,
    )
    profile = repository_profile("chipsalliance/rocket-chip").model_copy(
        update={"verifier_dependencies": [dependency]}, deep=True
    )
    instance = HweInstance(
        org="chipsalliance",
        repo="rocket-chip",
        number=3065,
        title="fixture",
        problem_statement="fixture",
        base_commit="1" * 40,
        fix_patch="diff --git a/demo.scala b/demo.scala\n",
        tb_script="echo test\n",
        modified_files=["demo.scala"],
        expected_test_ids=["test"],
        language="Chisel/Scala",
        license_id="BSD-3-Clause AND Apache-2.0",
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    prepared = tmp_path / "prepared"
    prepared.mkdir()

    with pytest.raises(ConfigurationError, match="lacks a required file"):
        _prepare_verifier_dependencies(
            cache_root=cache,
            prepared_root=prepared,
            instance=instance,
            profile=profile,
        )

    source = cache / dependency.cache_path
    source.parent.mkdir(parents=True)
    source.write_bytes(b"nope")
    with pytest.raises(ConfigurationError, match="differs from its profile"):
        _prepare_verifier_dependencies(
            cache_root=cache,
            prepared_root=prepared,
            instance=instance,
            profile=profile,
        )

    outside = tmp_path / "outside.jar"
    outside.write_bytes(b"nope")
    source.unlink()
    source.symlink_to(outside)
    with pytest.raises(ConfigurationError, match="differs from its profile"):
        _prepare_verifier_dependencies(
            cache_root=cache,
            prepared_root=prepared,
            instance=instance,
            profile=profile,
        )

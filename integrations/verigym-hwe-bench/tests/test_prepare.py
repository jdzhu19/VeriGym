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
    _resolve_image_identity,
)


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

from __future__ import annotations

import json
from pathlib import Path

import pytest
from verigym.plugin_api import (
    Candidate,
    ConfigurationError,
    SuiteSourceConfig,
    content_hash,
    hash_bytes,
    hash_directory,
)

from verigym_hwe_bench import HweBenchSuite
from verigym_hwe_bench import dataset as hwe_dataset
from verigym_hwe_bench.dataset import NATIVE_LAYOUT_V2, VARIANT, load_catalog
from verigym_hwe_bench.models import (
    HweInstance,
    ImageLockEntryV2,
    ImageLockV2,
    LicenseFileLock,
    RepositoryProfile,
    VerifierDependencyFile,
    repository_profile,
)
from verigym_hwe_bench.prepare import _official_instances


def _fixture_rocket_profile() -> tuple[RepositoryProfile, bytes]:
    base = repository_profile("chipsalliance/rocket-chip")
    payload = b"public verifier dependency fixture\n"
    dependency = VerifierDependencyFile(
        cache_path="https/repo1.maven.org/maven2/org/example/fixture/1.0/fixture-1.0.jar",
        sha256=hash_bytes(payload),
        size_bytes=len(payload),
    )
    identity = base.model_dump(mode="json")
    identity.pop("profile_hash")
    identity["verifier_dependencies"] = [dependency.model_dump(mode="json")]
    return (
        RepositoryProfile.model_validate({**identity, "profile_hash": content_hash(identity)}),
        payload,
    )


def _rocket_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "source"
    repository = root / "workspaces" / "chipsalliance__rocket-chip__pr-3065" / "repository"
    (repository / "src").mkdir(parents=True)
    for name in ("LICENSE.Berkeley", "LICENSE.SiFive", "LICENSE.jtag"):
        (repository / name).write_text(f"license fixture: {name}\n", encoding="utf-8")
    (repository / "src" / "Demo.scala").write_text("val enabled = false\n", encoding="utf-8")
    workspace = repository.parent
    (workspace / "TASK.md").write_text("# Repair\n", encoding="utf-8")
    (workspace / "PUBLIC_TESTS.md").write_text("# None\n", encoding="utf-8")
    instance = HweInstance(
        org="chipsalliance",
        repo="rocket-chip",
        number=3065,
        title="Repair Rocket Chip",
        problem_statement="Enable the required behavior.",
        base_commit="1" * 40,
        fix_patch=(
            "diff --git a/src/Demo.scala b/src/Demo.scala\n"
            "--- a/src/Demo.scala\n"
            "+++ b/src/Demo.scala\n"
            "@@ -1 +1 @@\n"
            "-val enabled = false\n"
            "+val enabled = true\n"
        ),
        tb_script="echo hidden\n",
        modified_files=["src/Demo.scala"],
        expected_test_ids=["rocket_test"],
        language="Chisel/Scala",
        license_id="BSD-3-Clause AND Apache-2.0",
    )
    profile, dependency_payload = _fixture_rocket_profile()
    monkeypatch.setattr(
        hwe_dataset,
        "repository_profile",
        lambda repository_id: (
            profile.model_copy(deep=True)
            if repository_id == instance.repository_id
            else repository_profile(repository_id)
        ),
    )
    inventory = [
        LicenseFileLock(path=name, sha256=hash_bytes((repository / name).read_bytes()))
        for name in profile.license_files
    ]
    reference = Candidate(
        files={"repository/src/Demo.scala": "val enabled = true\n"},
        label="official-reference-conformance-only",
    )
    repository_hash = hash_directory(repository)
    for dependency in profile.verifier_dependencies:
        dependency_path = root / "verifier-dependencies" / instance.slug / dependency.cache_path
        dependency_path.parent.mkdir(parents=True, exist_ok=True)
        dependency_path.write_bytes(dependency_payload)
    image_id = f"sha256:{'2' * 64}"
    digest = f"sha256:{'3' * 64}"
    bundle = {
        "instance": instance,
        "repository_hash": repository_hash,
        "image_id": image_id,
        "manifest_digest": digest,
        "repository_profile_hash": profile.profile_hash,
        "license_inventory": inventory,
        "verifier_dependencies": profile.verifier_dependencies,
    }
    entry = ImageLockEntryV2(
        instance_id=instance.instance_id,
        slug=instance.slug,
        image_reference="ghcr.io/pku-liang/chipsalliance_m_rocket-chip:pr-3065",
        manifest_digest=digest,
        image_id=image_id,
        repository_home=profile.repository_home,
        base_commit_marker=profile.base_commit_marker,
        base_commit=instance.base_commit,
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
        task_bundle_hash=content_hash(bundle),
        repository_profile_hash=profile.profile_hash,
        license_inventory=inventory,
        verifier_dependencies=profile.verifier_dependencies,
    )
    (root / "instances.jsonl").write_text(
        json.dumps(instance.model_dump(mode="json"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "image-lock.json").write_text(
        ImageLockV2(
            official_dataset_sha256="5" * 64,
            official_dataset_revision="6" * 40,
            entries=[entry],
        ).model_dump_json(indent=2)
        + "\n",
        encoding="utf-8",
    )
    return root


def test_repository_profiles_cover_cva6_and_rocket_semantics() -> None:
    cva6 = repository_profile("openhwgroup/cva6")
    rocket = repository_profile("chipsalliance/rocket-chip")

    assert cva6.license_expression == "SHL-0.51"
    assert cva6.baseline_identity_policy == "digest_locked_runtime_marker"
    assert cva6.workspace_excluded_paths == ["verif/core-v-verif/vendor/riscv/riscv-isa-sim/build"]
    assert rocket.repository_home == "/home/rocket-chip"
    assert rocket.base_commit_marker == "/home/base_commit.txt"
    assert rocket.language == "Chisel/Scala"
    assert rocket.license_expression == "BSD-3-Clause AND Apache-2.0"
    assert rocket.license_files == ["LICENSE.Berkeley", "LICENSE.SiFive", "LICENSE.jtag"]
    assert len(rocket.verifier_dependencies) == 3
    assert sum(item.size_bytes for item in rocket.verifier_dependencies) == 54_208


def test_v2_rocket_source_binds_profile_language_and_license_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _rocket_source(tmp_path, monkeypatch)
    catalog = load_catalog(root)
    suite = HweBenchSuite().with_source(SuiteSourceConfig(source_root=root, variant=VARIANT))
    task = suite.load_task(next(iter(suite.discover())))
    snapshot = suite.source_snapshot()

    assert catalog.native_layout == NATIVE_LAYOUT_V2
    assert catalog.lock.official_dataset_revision == "6" * 40
    assert task.metadata["language"] == "Chisel/Scala"
    assert task.source.license == "BSD-3-Clause AND Apache-2.0"
    assert task.metadata["repository_repair"]["base_commit_marker"] == "/home/base_commit.txt"
    assert task.metadata["repository_repair"]["repository_profile_hash"]
    assert (
        task.metadata["repository_repair"]["license_file_hash"]
        == task.metadata["repository_repair"]["license_inventory_hash"]
    )
    assert snapshot is not None
    assert snapshot.native_layout == NATIVE_LAYOUT_V2


def test_v2_source_rejects_profile_or_license_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _rocket_source(tmp_path, monkeypatch)
    lock_path = root / "image-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["entries"][0]["repository_profile_hash"] = "f" * 64
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="repository profile"):
        load_catalog(root)

    root = _rocket_source(tmp_path / "license-case", monkeypatch)
    license_path = (
        root / "workspaces" / "chipsalliance__rocket-chip__pr-3065" / "repository" / "LICENSE.jtag"
    )
    license_path.write_text("changed\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="repository hash changed|license changed"):
        load_catalog(root)

    root = _rocket_source(tmp_path / "dependency-case", monkeypatch)
    dependency = next((root / "verifier-dependencies").rglob("*.jar"))
    dependency.write_bytes(b"tampered\n")
    with pytest.raises(ConfigurationError, match="verifier dependency changed"):
        load_catalog(root)


@pytest.mark.parametrize("tamper", ["missing", "extra", "symlink"])
def test_v2_source_rejects_dependency_inventory_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    root = _rocket_source(tmp_path / tamper, monkeypatch)
    dependency_root = root / "verifier-dependencies" / "chipsalliance__rocket-chip__pr-3065"
    dependency = next(dependency_root.rglob("*.jar"))
    if tamper == "missing":
        dependency.unlink()
    elif tamper == "extra":
        (dependency.parent / "unexpected.jar").write_bytes(b"unexpected\n")
    else:
        outside = tmp_path / "outside.jar"
        outside.write_bytes(dependency.read_bytes())
        dependency.unlink()
        dependency.symlink_to(outside)

    with pytest.raises(
        ConfigurationError,
        match=(
            "verifier dependency inventory changed|verifier dependencies may not contain symlinks"
        ),
    ):
        load_catalog(root)


def test_selected_cva6_record_uses_profile_license(tmp_path: Path) -> None:
    dataset = tmp_path / "cva6.jsonl"
    row = {
        "org": "openhwgroup",
        "repo": "cva6",
        "number": 2945,
        "title": "fixture",
        "problem_statement": "repair fixture",
        "base": {"sha": "1" * 40},
        "f2p_tests": {"test": {}},
        "fix_patch_result": {"failed_count": 0, "skipped_count": 0, "passed_count": 1},
        "test_patch_result": {"failed_count": 1},
        "fix_patch": "diff --git a/demo.sv b/demo.sv\n",
        "test_patch": "",
        "tb_script": "echo test\n",
        "modified_files": ["demo.sv"],
    }
    dataset.write_text(json.dumps(row) + "\n", encoding="utf-8")

    instance = _official_instances(dataset, {"openhwgroup/cva6:pr-2945"})[0]

    assert instance.language == "SystemVerilog"
    assert instance.license_id == "SHL-0.51"

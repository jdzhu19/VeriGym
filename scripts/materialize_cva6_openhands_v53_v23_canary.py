#!/usr/bin/env python3
"""Materialize the v53 OpenHands v23 canary contract without calling a provider."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

_REPOSITORY = Path(__file__).resolve().parents[1]
_SOURCE_ROOTS = (
    _REPOSITORY,
    _REPOSITORY / "src",
    _REPOSITORY / "integrations/verigym-hwe-bench/src",
    _REPOSITORY / "integrations/verigym-openhands/src",
)
for _source_root in reversed(_SOURCE_ROOTS):
    if str(_source_root) not in sys.path:
        sys.path.insert(0, str(_source_root))

from verigym_openhands import hwe_v53_materialization as _v53  # noqa: E402

from scripts import materialize_cva6_openhands_v52_v23_canary as _v52_cli  # noqa: E402
from scripts import qualify_cva6_openhands_v51_pr2728_public_qualification as _v51  # noqa: E402
from verigym.core.errors import ConfigurationError  # noqa: E402
from verigym.core.hashing import content_hash, hash_bytes  # noqa: E402
from verigym.experiments.state import atomic_dump_json  # noqa: E402
from verigym.hwe.image_transfer import (  # noqa: E402
    ContentAddressedLayerCache,
    SingleCleanupArchive,
    redacted_transfer_failure,
    validate_registry_image_manifest,
)

_PLATFORM = "linux/amd64"
_PLATFORM_FLAG = f"--platform={_PLATFORM}"
_V52_FAILURE_PATH = Path(
    "/data/jzhu484/Agent/experiments/openhands-hwe-v52-v23-canary-materialization-v1.failure.json"
)
_REQUIRED_MERGED_PATHS = (
    "configs/training/qwen35_hwe_openhands_v53_v23_canary_materialization_v1.json",
    "docs/audits/2026-09-02_openhands-v52-v23-materialization-stopped.md",
    "docs/audits/2026-09-02_openhands-v53-v23-materialization-authorization.md",
    "integrations/verigym-openhands/src/verigym_openhands/hwe_v53_materialization.py",
    "integrations/verigym-openhands/tests/test_hwe_v53_materialization.py",
    "integrations/verigym-openhands/tests/test_hwe_v53_materialization_cli.py",
    "scripts/materialize_cva6_openhands_v53_v23_canary.py",
    "src/verigym/hwe/image_transfer.py",
    "tests/unit/test_hwe_image_transfer.py",
)
_BLOB_SCRIPT = 'umask 077; exec /tools/crane --platform=linux/amd64 blob "$1" > "$2"'


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--v33-root", type=Path, required=True)
    parser.add_argument("--v33-source-lock", type=Path, required=True)
    parser.add_argument("--rg-binary", type=Path, required=True)
    parser.add_argument("--rg-release-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def materialize(arguments: argparse.Namespace) -> dict[str, Any]:
    """Execute the one-shot, zero-provider v53 successor materialization."""

    if os.environ.get(_v53.OPENHANDS_V53_OPT_IN_ENV) != "1":
        raise ConfigurationError(f"{_v53.OPENHANDS_V53_OPT_IN_ENV}=1 is required")
    if os.getuid() == 0 or os.getgid() == 0:
        raise ConfigurationError("OpenHands v53 requires a non-root host identity")
    if any(name in os.environ for name in _v52_cli._CREDENTIAL_ENV_NAMES):
        raise ConfigurationError("OpenHands v53 refuses a provider credential environment")
    _require_clean_merged_main()
    authorization = _v53.validate_v53_authorization(
        _v52_cli._load_json(_v52_cli._safe_file(arguments.authorization))
    )
    _validate_v52_failure_receipt()
    context = _v52_cli._RunContext(
        authorization=authorization,
        dataset=_v52_cli._validated_dataset(arguments.dataset),
        v33_root=_v52_cli._safe_directory(arguments.v33_root),
        v33_source_lock=_v52_cli._safe_file(arguments.v33_source_lock),
        rg_binary=_v52_cli._validated_rg(
            arguments.rg_binary,
            executable=True,
            expected=_v52_cli._RG_SHA256,
        ),
        rg_archive=_v52_cli._validated_rg(
            arguments.rg_release_archive,
            executable=False,
            expected=_v52_cli._RG_ARCHIVE_SHA256,
        ),
    )
    output = arguments.output.expanduser()
    if output.parent.resolve(strict=True) != Path("/data/jzhu484/Agent/experiments"):
        raise ConfigurationError("OpenHands v53 output root changed")
    failure_path = output.with_name(f"{output.name}.failure.json")
    if failure_path.exists() or failure_path.is_symlink():
        raise ConfigurationError("OpenHands v53 identity is already frozen by a failure receipt")

    def wrap(
        stage: str,
        function: Callable[[_v52_cli._RunContext, Path], dict[str, Any]],
    ) -> Callable[[Path], dict[str, Any]]:
        def wrapped(root: Path) -> dict[str, Any]:
            context.active_stage = stage
            return function(context, root)

        return wrapped

    stages = _v53.V53Stages(
        pr2728_image_transfer=wrap("pr2728_image_transfer", _transfer_stage),
        pr2728_public_qualification=wrap("pr2728_public_qualification", _qualification_stage),
        pr2728_v2_security_scan=wrap("pr2728_v2_security_scan", _security_scan_stage),
        pr2728_command_image_lock=wrap("pr2728_command_image_lock", _command_lock_stage),
        pr3204_v33_lock_revalidation=wrap("pr3204_v33_lock_revalidation", _v33_revalidation_stage),
    )
    try:
        return _v53.run_v53_zero_provider(
            authorization=authorization,
            stages=stages,
            output=output,
        )
    except BaseException as exc:
        _publish_failure(failure_path, context=context, exc=exc)
        raise


def _transfer_stage(context: _v52_cli._RunContext, root: Path) -> dict[str, Any]:
    return _transfer_stage_for_identity(
        context,
        root,
        identity=_v53.OPENHANDS_V53_IDENTITY,
        version="v53",
        cache_root=_v53.OPENHANDS_V53_PERSISTENT_LAYER_CACHE,
    )


def _transfer_stage_for_identity(
    context: _v52_cli._RunContext,
    root: Path,
    *,
    identity: str,
    version: str,
    cache_root: Path,
) -> dict[str, Any]:
    _v51._validate_headroom()
    _v51._validate_network()
    execution = _v51._validate_local_image(_v52_cli._EXECUTION_IMAGE)
    tool_cache = _v52_cli._safe_directory(_v52_cli._TOOL_CACHE)
    crane = _v52_cli._safe_file(tool_cache / "crane")
    if not os.access(crane, os.X_OK) or hash_bytes(crane.read_bytes()) != _v52_cli._CRANE_SHA256:
        raise ConfigurationError(f"OpenHands {version} crane identity changed")
    if _v51._inspect_host_image(_v52_cli._REFERENCE) is not None:
        raise ConfigurationError(f"OpenHands {version} PR-2728 tag already exists")
    sentinel = _v51._sentinel_reference()
    if _v51._inspect_host_image(sentinel) is not None:
        raise ConfigurationError(f"OpenHands {version} transfer sentinel already exists")

    cache = ContentAddressedLayerCache(cache_root)
    download_staging = cache.task_staging(
        f"{version}-pr2728-download-{os.getpid()}-{secrets.token_hex(4)}"
    )
    assembly_staging: Path | None = None
    work = root / "private-transfer"
    work.mkdir(mode=0o700)
    archive = work / "candidate-image.tar"
    owner = SingleCleanupArchive(archive)
    inventory: list[dict[str, str | int | bool]] = []
    context.verified_layer_inventory = inventory
    try:
        digest_stdout, _ = _controlled(
            execution,
            tool_cache=tool_cache,
            network=_v52_cli._NETWORK,
            path="/tools/crane",
            arguments=[_PLATFORM_FLAG, "digest", _v52_cli._REFERENCE],
            role="candidate_digest",
            timeout=300,
            owner_identity=identity,
            name_version=version,
        )
        manifest_digest = digest_stdout.decode("ascii", errors="strict").strip()
        if _v52_cli._DIGEST.fullmatch(manifest_digest) is None:
            raise ConfigurationError(f"OpenHands {version} candidate manifest digest is malformed")
        repository = _v52_cli._REFERENCE.rsplit(":", 1)[0]
        immutable = f"{repository}@{manifest_digest}"
        manifest_stdout, _ = _controlled(
            execution,
            tool_cache=tool_cache,
            network=_v52_cli._NETWORK,
            path="/tools/crane",
            arguments=[_PLATFORM_FLAG, "manifest", immutable],
            role="candidate_manifest",
            timeout=300,
            owner_identity=identity,
            name_version=version,
        )
        manifest = validate_registry_image_manifest(
            manifest_stdout,
            expected_digest=manifest_digest,
            maximum_layers=512,
        )
        config_stdout, _ = _controlled(
            execution,
            tool_cache=tool_cache,
            network=_v52_cli._NETWORK,
            path="/tools/crane",
            arguments=[_PLATFORM_FLAG, "config", immutable],
            role="candidate_config",
            timeout=300,
            owner_identity=identity,
            name_version=version,
        )
        config_payload = _digest_qualified_payload(
            config_stdout,
            digest=manifest.config.digest,
            size=manifest.config.size,
            label="config",
            version=version,
        )
        image_id = manifest.config.digest

        for index, layer in enumerate(manifest.layers):
            cached = cache.bounded_inventory([layer.digest])[0]
            if cached["cache_hit"] is True:
                if cached["size"] != layer.size:
                    raise ConfigurationError(f"OpenHands {version} cached layer size changed")
                receipt = cached
            else:
                target = download_staging / layer.digest
                blob_reference = f"{repository}@{layer.digest}"
                stdout, _ = _controlled(
                    execution,
                    tool_cache=tool_cache,
                    cache_staging=download_staging,
                    network=_v52_cli._NETWORK,
                    path="/bin/sh",
                    arguments=[
                        "-ceu",
                        _BLOB_SCRIPT,
                        "verigym-v53-layer",
                        blob_reference,
                        f"/cache/{layer.digest}",
                    ],
                    role=f"layer_{index:03d}",
                    timeout=3_600,
                    owner_identity=identity,
                    name_version=version,
                )
                if stdout:
                    raise ConfigurationError(f"OpenHands {version} layer download emitted stdout")
                receipt = cache.commit(
                    target,
                    digest=layer.digest,
                    size=layer.size,
                ).safe_dict()
            inventory.append(receipt)
            context.verified_layer_inventory = copy.deepcopy(inventory)

        if len(inventory) != len(manifest.layers):
            raise ConfigurationError(f"OpenHands {version} layer inventory is incomplete")
        assembly_staging = cache.task_staging(
            f"{version}-pr2728-assembly-{os.getpid()}-{secrets.token_hex(4)}"
        )
        cache.seed_task_staging(
            assembly_staging,
            digests=[item.digest for item in manifest.layers],
        )
        with owner:
            pull_stdout, _ = _controlled(
                execution,
                tool_cache=tool_cache,
                work=work,
                cache_staging=assembly_staging,
                network=_v52_cli._NETWORK,
                path="/tools/crane",
                arguments=[
                    _PLATFORM_FLAG,
                    "pull",
                    immutable,
                    "/transfer/candidate-image.tar",
                    "--format=tarball",
                    "--cache_path=/cache",
                ],
                role="candidate_assembly",
                timeout=3_600,
                owner_identity=identity,
                name_version=version,
            )
            if pull_stdout:
                raise ConfigurationError(f"OpenHands {version} crane assembly emitted stdout")
            assembly_inventory = cache.promote_task_staging(assembly_staging)
            assembled = {item.digest: item.size for item in assembly_inventory}
            if assembled != {item.digest: item.size for item in manifest.layers}:
                raise ConfigurationError(f"OpenHands {version} assembly cache identity changed")
            _v51._validated_crane_tarball(
                archive,
                expected_image_id=image_id,
                expected_sentinel=sentinel,
            )
            loaded = _v52_cli._bounded_run(
                ["docker", "image", "load", "--input", str(archive)], timeout=3_600
            )
            if loaded.returncode != 0:
                raise _v52_cli._CommandFailure("candidate_load", loaded.stderr)
            observed_sentinel = _v51._inspect_host_image(sentinel)
            if observed_sentinel is None or observed_sentinel.get("Id") != image_id:
                raise ConfigurationError(f"OpenHands {version} loaded image identity changed")
            tagged = _v52_cli._bounded_run(
                ["docker", "image", "tag", image_id, _v52_cli._REFERENCE], timeout=60
            )
            if tagged.returncode != 0 or tagged.stdout or tagged.stderr:
                raise _v52_cli._CommandFailure("candidate_tag", tagged.stderr)
            imported = _v51._inspect_host_image(_v52_cli._REFERENCE)
            if imported is None or imported.get("Id") != image_id:
                raise ConfigurationError(f"OpenHands {version} candidate tag identity changed")
            removed = _v52_cli._bounded_run(["docker", "image", "rm", sentinel], timeout=60)
            if removed.returncode != 0 or _v51._inspect_host_image(sentinel) is not None:
                raise _v52_cli._CommandFailure("sentinel_cleanup", removed.stderr)
    finally:
        cleanup = [download_staging, work]
        if assembly_staging is not None:
            cleanup.insert(1, assembly_staging)
        _v52_cli._cleanup_directories(*cleanup)
    base = {
        "schema_version": "1.0",
        "format_id": f"verigym_openhands_hwe_{version}_pr2728_image_transfer_v1",
        "task_id": _v52_cli._TASK_ID,
        "platform": _PLATFORM,
        "verifier_image": image_id,
        "manifest_digest": manifest_digest,
        "manifest_size": manifest.manifest_size,
        "config_digest": manifest.config.digest,
        "config_size": len(config_payload),
        "layer_inventory": inventory,
        "layer_download_count": sum(item["cache_hit"] is False for item in inventory),
        "all_layers_verified_before_assembly": True,
        "assembly_source": "verified_content_addressed_cache",
        "temporary_archive_cleanup_count": owner.cleanup_count,
        "raw_stderr_persisted": False,
        "provider_calls": 0,
        "model_process_count": 0,
    }
    context.transfer = _v52_cli._sealed(base)
    return context.transfer


def _controlled(
    execution: dict[str, Any],
    *,
    tool_cache: Path,
    network: str,
    path: str,
    arguments: list[str],
    role: str,
    timeout: int,
    work: Path | None = None,
    cache_staging: Path | None = None,
    owner_identity: str = _v53.OPENHANDS_V53_IDENTITY,
    name_version: str = "v53",
) -> tuple[bytes, bytes]:
    return _v52_cli._run_controlled_container(
        image_id=str(execution["image_id"]),
        tool_cache=tool_cache,
        work=work,
        cache_staging=cache_staging,
        network=network,
        path=path,
        arguments=arguments,
        role=role,
        timeout=timeout,
        owner_identity=owner_identity,
        name_version=name_version,
    )


def _digest_qualified_payload(
    raw: bytes,
    *,
    digest: str,
    size: int,
    label: str,
    version: str = "v53",
) -> bytes:
    expected = digest.removeprefix("sha256:")
    candidates = (raw, raw[:-1]) if raw.endswith(b"\n") else (raw,)
    for candidate in candidates:
        if len(candidate) == size and hashlib.sha256(candidate).hexdigest() == expected:
            return candidate
    raise ConfigurationError(f"OpenHands {version} candidate {label} identity changed")


def _qualification_stage_for_version(
    context: _v52_cli._RunContext,
    root: Path,
    *,
    version: str,
) -> dict[str, Any]:
    receipt = _relabel(
        _v52_cli._qualification_stage(context, root),
        f"verigym_openhands_hwe_{version}_pr2728_public_qualification_v1",
    )
    context.qualification = receipt
    return receipt


def _qualification_stage(context: _v52_cli._RunContext, root: Path) -> dict[str, Any]:
    return _qualification_stage_for_version(context, root, version="v53")


def _security_scan_stage_for_identity(
    context: _v52_cli._RunContext,
    root: Path,
    *,
    identity: str,
    version: str,
) -> dict[str, Any]:
    return _v52_cli._security_scan_stage(
        context,
        root,
        image_tag=f"verigym/cva6-openhands-{version}-command-pr-2728:rg-15.2.0-v1",
        format_id=f"verigym_openhands_hwe_{version}_pr2728_v2_security_scan_v1",
        owner_identity=identity,
        name_version=version,
    )


def _security_scan_stage(context: _v52_cli._RunContext, root: Path) -> dict[str, Any]:
    return _security_scan_stage_for_identity(
        context,
        root,
        identity=_v53.OPENHANDS_V53_IDENTITY,
        version="v53",
    )


def _command_lock_stage_for_version(
    context: _v52_cli._RunContext,
    root: Path,
    *,
    version: str,
) -> dict[str, Any]:
    return _relabel(
        _v52_cli._command_lock_stage(context, root),
        f"verigym_openhands_hwe_{version}_pr2728_command_image_lock_v1",
    )


def _command_lock_stage(context: _v52_cli._RunContext, root: Path) -> dict[str, Any]:
    return _command_lock_stage_for_version(context, root, version="v53")


def _v33_revalidation_stage_for_version(
    context: _v52_cli._RunContext,
    root: Path,
    *,
    version: str,
) -> dict[str, Any]:
    return _relabel(
        _v52_cli._v33_revalidation_stage(context, root),
        f"verigym_openhands_hwe_{version}_pr3204_v33_lock_revalidation_v1",
    )


def _v33_revalidation_stage(context: _v52_cli._RunContext, root: Path) -> dict[str, Any]:
    return _v33_revalidation_stage_for_version(context, root, version="v53")


def _relabel(receipt: dict[str, Any], format_id: str) -> dict[str, Any]:
    base = {key: copy.deepcopy(value) for key, value in receipt.items() if key != "receipt_hash"}
    base["format_id"] = format_id
    return _v52_cli._sealed(base)


def _validate_v52_failure_receipt() -> None:
    path = _v52_cli._safe_file(_V52_FAILURE_PATH)
    expected = _v53._V52_FAILURE_BINDING
    value = _v52_cli._load_json(path)
    if (
        hash_bytes(path.read_bytes()) != expected["failure_file_sha256"]
        or value.get("identity") != expected["identity"]
        or value.get("status") != expected["status"]
        or value.get("failure_stage") != expected["failure_stage"]
        or value.get("failure_type") != expected["failure_type"]
        or value.get("receipt_hash") != expected["failure_receipt_hash"]
        or value.get("output_published") is not False
        or value.get("provider_calls") != 0
        or value.get("model_process_count") != 0
    ):
        raise ConfigurationError("OpenHands v52 frozen failure evidence changed")


def _publish_failure(
    path: Path,
    *,
    context: _v52_cli._RunContext,
    exc: BaseException,
) -> None:
    if path.exists() or path.is_symlink():
        return
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "format_id": "verigym_openhands_hwe_v53_materialization_failure_v1",
        "identity": _v53.OPENHANDS_V53_IDENTITY,
        "status": "frozen_zero_provider_materialization_failed",
        "authorization_hash": context.authorization["authorization_hash"],
        "failure_stage": context.active_stage or "preflight",
        "failure_type": type(exc).__name__,
        "output_published": False,
        "canary_contract_published": False,
        "provider_calls": 0,
        "model_process_count": 0,
        "raw_output_persisted": False,
        "formal_collection_allowed": False,
        "formal_collection_started": False,
        "collection_started": False,
        "training_started": False,
        "production_training_ready": False,
    }
    command_failure = _v52_cli._find_command_failure(exc)
    if command_failure is not None and context.active_stage == "pr2728_image_transfer":
        base["transfer_error"] = redacted_transfer_failure(
            command_failure,
            raw_stderr=command_failure.raw_stderr,
            stage=command_failure.stage,
        )
    inventory = context.verified_layer_inventory
    if context.active_stage == "pr2728_image_transfer" and inventory is not None:
        if len(inventory) > 512:
            raise ConfigurationError("OpenHands v53 failure inventory is unbounded")
        base["verified_layer_inventory"] = copy.deepcopy(inventory)
    atomic_dump_json(path, {**base, "receipt_hash": content_hash(base)})


def _require_clean_merged_main() -> str:
    for relative in _REQUIRED_MERGED_PATHS:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=_REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
        )
        if result.stdout.strip() != relative:
            raise ConfigurationError("OpenHands v53 required merged path changed")
    subprocess.run(["git", "diff", "--quiet", "--"], cwd=_REPOSITORY, check=True)
    subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=_REPOSITORY, check=True)
    head = _v52_cli._git_output("rev-parse", "HEAD")
    upstream = _v52_cli._git_output("rev-parse", "origin/main")
    if head != upstream or re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise ConfigurationError("OpenHands v53 requires the clean merged origin/main commit")
    return head


def main() -> int:
    result = materialize(_parser().parse_args())
    print(
        json.dumps(
            {
                "identity": result["identity"],
                "status": result["status"],
                "canary_contract_hash": result["canary_contract_hash"],
                "provider_calls": result["provider_calls"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

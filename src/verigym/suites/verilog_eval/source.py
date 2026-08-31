"""External source resolution and offline provenance extraction."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from verigym.core.errors import ConfigurationError
from verigym.core.hashing import content_hash, hash_bytes
from verigym.schemas.suite import SuiteSourceConfig, SuiteSourceSnapshot
from verigym.suites.verilog_eval.schemas import (
    VerilogEvalCatalog,
    VerilogEvalLayout,
    VerilogEvalVariant,
)

_DATASET_BY_VARIANT = {
    VerilogEvalVariant.V2_SPEC_TO_RTL: "dataset_spec-to-rtl",
    VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_V1: "dataset_spec-to-rtl",
    VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V1: "dataset_spec-to-rtl",
    VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V2: "dataset_spec-to-rtl",
    VerilogEvalVariant.V2_SPEC_TO_RTL_AGENT_EVAL_FUNCTIONAL_V3: "dataset_spec-to-rtl",
}
_KNOWN_DATASET_DIRECTORIES = {
    "dataset_spec-to-rtl": VerilogEvalVariant.V2_SPEC_TO_RTL,
    "dataset_code-complete-iccad2023": "v2-code-complete-iccad2023",
}


def resolve_layout(config: SuiteSourceConfig) -> VerilogEvalLayout:
    raw_root = config.source_root.expanduser()
    try:
        root = raw_root.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ConfigurationError(f"VerilogEval source path is unavailable: {raw_root}") from exc
    if not root.is_dir():
        raise ConfigurationError("VerilogEval source path must be a directory")

    variant_value = config.variant
    if variant_value is None and root.name in _KNOWN_DATASET_DIRECTORIES:
        inferred = _KNOWN_DATASET_DIRECTORIES[root.name]
        if isinstance(inferred, VerilogEvalVariant):
            variant_value = inferred.value
        else:
            raise ConfigurationError(f"unsupported VerilogEval variant: {inferred}")
    if variant_value is None:
        present = [name for name in _KNOWN_DATASET_DIRECTORIES if (root / name).is_dir()]
        if len(present) > 1:
            raise ConfigurationError(
                "VerilogEval source root is ambiguous; specify --variant v2-spec-to-rtl"
            )
        if present:
            inferred = _KNOWN_DATASET_DIRECTORIES[present[0]]
            if isinstance(inferred, VerilogEvalVariant):
                variant_value = inferred.value
            else:
                raise ConfigurationError(f"unsupported VerilogEval variant: {inferred}")
    if variant_value is None:
        if any(root.glob("*.jsonl")):
            raise ConfigurationError(
                "legacy VerilogEval V1 JSONL layout is unsupported; use V2 main-branch triplets"
            )
        raise ConfigurationError(
            "cannot locate dataset_spec-to-rtl under the supplied VerilogEval source"
        )
    try:
        variant = VerilogEvalVariant(variant_value)
    except ValueError as exc:
        raise ConfigurationError(f"unsupported VerilogEval variant: {variant_value}") from exc

    directory_name = _DATASET_BY_VARIANT[variant]
    dataset_root = root if root.name == directory_name else root / directory_name
    try:
        dataset_root = dataset_root.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ConfigurationError(
            f"VerilogEval source is missing required directory {directory_name}"
        ) from exc
    if not dataset_root.is_dir():
        raise ConfigurationError(f"{directory_name} is not a directory")
    approved_root = root if root.name != directory_name else root
    if not dataset_root.is_relative_to(approved_root):
        raise ConfigurationError("VerilogEval dataset path escapes the approved source root")
    return VerilogEvalLayout(
        source_root=root,
        dataset_root=dataset_root,
        variant=variant,
    )


def build_source_snapshot(
    config: SuiteSourceConfig,
    catalog: VerilogEvalCatalog,
) -> SuiteSourceSnapshot:
    layout = catalog.layout
    repository_root = _repository_root(layout)
    license_id, license_hash = _license_metadata(repository_root)
    git_commit, git_remote, git_available = _git_metadata(repository_root)
    marker_roots = {layout.source_root, layout.dataset_root.parent}
    synthetic = any((root / "VERIGYM_SYNTHETIC_FIXTURE").is_file() for root in marker_roots)
    safe_configuration = {
        "source_root": layout.source_root.as_posix(),
        "dataset_root": layout.dataset_root.as_posix(),
        "variant": layout.variant.value,
        "strict_compatibility": config.strict_compatibility,
        "dataset_content_hash": catalog.dataset_content_hash,
    }
    return SuiteSourceSnapshot(
        source_root=layout.source_root.as_posix(),
        dataset_root=layout.dataset_root.as_posix(),
        variant=layout.variant.value,
        native_layout=layout.native_layout,
        strict_compatibility=config.strict_compatibility,
        configuration_fingerprint=content_hash(safe_configuration),
        dataset_content_hash=catalog.dataset_content_hash,
        license_id=license_id,
        license_file_hash=license_hash,
        git_commit=git_commit,
        git_remote=git_remote,
        git_metadata_available=git_available,
        synthetic_fixture=synthetic,
    )


def _repository_root(layout: VerilogEvalLayout) -> Path:
    if (layout.source_root / ".git").exists() or (layout.source_root / "LICENSE").is_file():
        return layout.source_root
    parent = layout.dataset_root.parent
    if (parent / ".git").exists() or (parent / "LICENSE").is_file():
        return parent
    return layout.source_root


def _license_metadata(root: Path) -> tuple[str | None, str | None]:
    license_path = root / "LICENSE"
    if not license_path.is_file() or license_path.is_symlink():
        return None, None
    try:
        data = license_path.read_bytes()
    except OSError:
        return None, None
    text = data[:64_000].decode("utf-8", errors="ignore").lower()
    if "mit license" in text and "permission is hereby granted" in text:
        identifier = "MIT"
    elif "apache license" in text and "version 2.0" in text:
        identifier = "Apache-2.0"
    else:
        identifier = None
    return identifier, hash_bytes(data)


def _git_metadata(root: Path) -> tuple[str | None, str | None, bool]:
    if not (root / ".git").exists():
        return None, None, False
    commit = _git_read(root, ["rev-parse", "HEAD"])
    remote = _git_read(root, ["remote", "get-url", "origin"])
    return commit, _sanitize_remote(remote) if remote else None, commit is not None


def _git_read(root: Path, arguments: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else None


def _sanitize_remote(value: str) -> str | None:
    if re.match(r"^[^/@\s]+@[^/:\s]+:", value):
        _, host_path = value.split("@", 1)
        host, path = host_path.split(":", 1)
        return f"ssh://{host}/{path.lstrip('/')}"
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https", "ssh", "git"} and parsed.hostname:
        try:
            parsed_port = parsed.port
        except ValueError:
            return None
        port = f":{parsed_port}" if parsed_port else ""
        return urlunsplit((parsed.scheme, f"{parsed.hostname}{port}", parsed.path, "", ""))
    return None


__all__ = ["build_source_snapshot", "resolve_layout"]

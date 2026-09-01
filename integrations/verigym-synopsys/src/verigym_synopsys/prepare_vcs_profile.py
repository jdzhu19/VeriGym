"""Prepare one private, fixed VCS MCP server profile."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import yaml
from verigym.plugin_api import ConfigurationError, hash_bytes

from .vcs import probe_vcs
from .vcs_mcp_profile import VcsMcpAuxiliaryFile, VcsMcpServerProfile


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare a fixed VCS MCP server profile.")
    parser.add_argument("--id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--testbench", type=Path, required=True)
    parser.add_argument("--testbench-mount-path", default="verifier/testbench.v")
    parser.add_argument(
        "--auxiliary-file",
        action="append",
        default=[],
        metavar="MOUNT_PATH=SOURCE_PATH",
    )
    parser.add_argument("--top", required=True)
    parser.add_argument("--pass-marker", default="VERIGYM_PASS")
    parser.add_argument("--fail-marker", default="VERIGYM_FAIL")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--vcs", required=True)
    parser.add_argument("--environment", action="append", default=[])
    parser.add_argument("--output-profile", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    requested_testbench = arguments.testbench.expanduser()
    if requested_testbench.is_symlink() or not requested_testbench.is_file():
        raise ConfigurationError("VCS testbench must be a regular non-symlink file")
    testbench = requested_testbench.resolve(strict=True)
    health = probe_vcs(arguments.vcs)
    if not health.healthy or health.version is None or health.executable is None:
        raise ConfigurationError("VCS identity probe failed while preparing the profile")
    auxiliary_files: list[VcsMcpAuxiliaryFile] = []
    for value in arguments.auxiliary_file:
        mount_path, separator, source_value = value.partition("=")
        if not separator or not mount_path or not source_value:
            raise ConfigurationError("VCS auxiliary files require MOUNT_PATH=SOURCE_PATH")
        requested_source = Path(source_value).expanduser()
        if requested_source.is_symlink() or not requested_source.is_file():
            raise ConfigurationError("VCS auxiliary input must be a regular non-symlink file")
        source = requested_source.resolve(strict=True)
        auxiliary_files.append(
            VcsMcpAuxiliaryFile(
                path=str(source),
                mount_path=mount_path,
                sha256=hash_bytes(source.read_bytes()),
            )
        )
    profile = VcsMcpServerProfile(
        id=arguments.id,
        task_id=arguments.task_id,
        executable=str(Path(health.executable).resolve(strict=True)),
        accepted_tool_version=health.version,
        sources=arguments.source,
        testbench=str(testbench),
        testbench_mount_path=arguments.testbench_mount_path,
        testbench_sha256=hash_bytes(testbench.read_bytes()),
        auxiliary_files=auxiliary_files,
        top=arguments.top,
        pass_marker=arguments.pass_marker,
        fail_marker=arguments.fail_marker,
        timeout_s=arguments.timeout,
        environment_allowlist=arguments.environment,
    )
    output = arguments.output_profile.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    output.chmod(0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

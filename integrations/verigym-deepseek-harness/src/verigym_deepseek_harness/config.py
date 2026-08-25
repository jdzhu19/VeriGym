"""Frozen identity and execution settings for the DeepSeek Harness HWE pilot."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from verigym.core.hashing import content_hash
from verigym.hwe.deepseek_harness import (
    DEEPSEEK_HARNESS_MODEL,
    DEEPSEEK_HARNESS_REVISION,
)
from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_V2_ID

DEEPSEEK_HARNESS_SOURCE_ROOT = Path(
    "/data/jzhu484/Agent/datasets/deepseek-harness/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e"
)
DEEPSEEK_HARNESS_VERSION = "0.1.1-rc.2"
CONTROLLER_IMAGE_ID = "sha256:daa74c183f7d8c1ba55ed79c76e912f50be8782ca9d2da640645f906dce474b8"
CONTROLLER_IMAGE_REPO_DIGEST = (
    "node@sha256:4a4884e8a44826194dff92ba316264f392056cbe243dcc9fd3551e71cea02b90"
)
CONTROLLER_NETWORK = "verigym-hwe-net"
API_KEY_ENV = "VERIGYM_DEEPSEEK_API_KEY"
BASE_URL_ENV = "VERIGYM_DEEPSEEK_API_BASE_URL"


@dataclass(frozen=True)
class DeepSeekHarnessSettings:
    source_root: Path
    sdk_source_root: Path
    runtime_entry: Path
    runtime_assets: Path
    controller_image_id: str
    controller_image_repo_digest: str
    source_tree_hash: str
    runtime_entry_hash: str
    cordis_config_hash: str
    tool_plugin_hash: str
    configuration_fingerprint: str
    process_timeout_s: float
    max_output_bytes: int

    def harness_identity(self) -> dict[str, Any]:
        return {
            "revision": DEEPSEEK_HARNESS_REVISION,
            "version": DEEPSEEK_HARNESS_VERSION,
            "sdk_transport": "python_sdk_source_controller_container",
            "controller_network": CONTROLLER_NETWORK,
            "tool_transport": "owner_only_unix_socket",
            "source_tree_hash": self.source_tree_hash,
            "controller_image_id": self.controller_image_id.removeprefix("sha256:"),
            "controller_image_digest_hash": self.controller_image_repo_digest.rsplit("sha256:", 1)[
                -1
            ],
            "cordis_config_hash": self.cordis_config_hash,
            "tool_plugin_hash": self.tool_plugin_hash,
            "configuration_fingerprint": self.configuration_fingerprint,
        }


def resolve_settings(
    options: Any,
    *,
    task_wall_time_s: float,
    verify_controller: bool = True,
) -> DeepSeekHarnessSettings:
    if not isinstance(options, dict):
        options = dict(options)
    if options.get("collection_profile_id") != HWE_COLLECTION_PROFILE_V2_ID:
        raise ValueError("DeepSeek Harness HWE requires collection_profile_id=hwe_standard_v2")
    if options.get("model_id", DEEPSEEK_HARNESS_MODEL) != DEEPSEEK_HARNESS_MODEL:
        raise ValueError("DeepSeek Harness HWE model identity is frozen")
    source_root = Path(
        str(options.get("harness_source_root", DEEPSEEK_HARNESS_SOURCE_ROOT))
    ).resolve(strict=True)
    if source_root.name != DEEPSEEK_HARNESS_REVISION:
        raise ValueError("DeepSeek Harness source directory does not name the frozen revision")
    _verify_source_checkout(source_root)
    source_tree_hash = _tracked_tree_hash(source_root)
    package = _json(source_root / "package.json")
    if package.get("version") != DEEPSEEK_HARNESS_VERSION:
        raise ValueError("DeepSeek Harness package version changed")
    sdk_source = source_root / "python/sdk/src"
    runtime_entry = source_root / "packages/examples/jsonrpc-demo/src/bin.ts"
    if not sdk_source.is_dir() or not runtime_entry.is_file():
        raise ValueError("DeepSeek Harness SDK source runtime is incomplete")
    runtime_assets = Path(__file__).with_name("runtime").resolve(strict=True)
    cordis = runtime_assets / "cordis.yml"
    plugin = runtime_assets / "hwe-tools.mjs"
    controller_image_id = str(options.get("controller_image_id", CONTROLLER_IMAGE_ID))
    if controller_image_id != CONTROLLER_IMAGE_ID:
        raise ValueError("DeepSeek Harness controller image identity is frozen")
    if verify_controller:
        _verify_controller_image(controller_image_id)
    process_timeout_s = float(options.get("max_process_time_s", task_wall_time_s))
    if process_timeout_s <= 0 or process_timeout_s > min(task_wall_time_s, 3600):
        raise ValueError("DeepSeek Harness process timeout exceeds the task budget")
    max_output_bytes = int(options.get("max_output_bytes", 32 * 1024 * 1024))
    if max_output_bytes < 1024 or max_output_bytes > 32 * 1024 * 1024:
        raise ValueError("DeepSeek Harness output bound is outside the frozen range")
    identity = {
        "revision": DEEPSEEK_HARNESS_REVISION,
        "version": DEEPSEEK_HARNESS_VERSION,
        "source_tree_hash": source_tree_hash,
        "controller_image_id": CONTROLLER_IMAGE_ID,
        "controller_image_repo_digest": CONTROLLER_IMAGE_REPO_DIGEST,
        "runtime_entry_hash": _sha256_file(runtime_entry),
        "cordis_config_hash": _sha256_file(cordis),
        "tool_plugin_hash": _sha256_file(plugin),
        "provider": "deepseek-official",
        "model": DEEPSEEK_HARNESS_MODEL,
        "thinking": "disabled",
        "reasoning_effort": "off",
        "temperature": 0,
        "max_output_tokens": 2048,
        "max_parallel_tool_calls": 1,
        "provider_request_retries": 0,
        "whole_episode_retries": 0,
        "controller_network": CONTROLLER_NETWORK,
        "credential_environment_name": API_KEY_ENV,
        "base_url_environment_name": BASE_URL_ENV,
    }
    return DeepSeekHarnessSettings(
        source_root=source_root,
        sdk_source_root=sdk_source,
        runtime_entry=runtime_entry,
        runtime_assets=runtime_assets,
        controller_image_id=controller_image_id,
        controller_image_repo_digest=CONTROLLER_IMAGE_REPO_DIGEST,
        source_tree_hash=source_tree_hash,
        runtime_entry_hash=str(identity["runtime_entry_hash"]),
        cordis_config_hash=str(identity["cordis_config_hash"]),
        tool_plugin_hash=str(identity["tool_plugin_hash"]),
        configuration_fingerprint=content_hash(identity),
        process_timeout_s=process_timeout_s,
        max_output_bytes=max_output_bytes,
    )


def require_provider_environment() -> None:
    if not os.environ.get(API_KEY_ENV):
        raise ValueError(f"{API_KEY_ENV} is required")
    if not os.environ.get(BASE_URL_ENV):
        raise ValueError(f"{BASE_URL_ENV} is required")


def _verify_source_checkout(root: Path) -> None:
    revision = _git(root, "rev-parse", "HEAD").decode().strip()
    if revision != DEEPSEEK_HARNESS_REVISION:
        raise ValueError("DeepSeek Harness checkout revision changed")
    dirty = subprocess.run(
        ["git", "-C", str(root), "diff", "--quiet", "HEAD", "--"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if dirty.returncode != 0:
        raise ValueError("DeepSeek Harness tracked source tree is dirty")


def _tracked_tree_hash(root: Path) -> str:
    return hashlib.sha256(_git(root, "ls-tree", "-r", "--full-tree", "HEAD")).hexdigest()


def _git(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError("DeepSeek Harness git identity check failed")
    return completed.stdout


def _verify_controller_image(image_id: str) -> None:
    completed = subprocess.run(
        ["docker", "image", "inspect", image_id, "--format", "{{json .}}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise ValueError("DeepSeek Harness controller image is unavailable")
    value = json.loads(completed.stdout)
    if value.get("Id") != image_id or CONTROLLER_IMAGE_REPO_DIGEST not in value.get(
        "RepoDigests", []
    ):
        raise ValueError("DeepSeek Harness controller image digest changed")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return value


__all__ = [
    "API_KEY_ENV",
    "BASE_URL_ENV",
    "CONTROLLER_IMAGE_ID",
    "CONTROLLER_IMAGE_REPO_DIGEST",
    "CONTROLLER_NETWORK",
    "DEEPSEEK_HARNESS_SOURCE_ROOT",
    "DEEPSEEK_HARNESS_VERSION",
    "DeepSeekHarnessSettings",
    "require_provider_environment",
    "resolve_settings",
]

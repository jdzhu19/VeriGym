#!/usr/bin/env python3
"""Serve hash-bound online rollout requests through an evaluator-owned VeriGym process."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from verigym_training_reference.online_verifier import score_online_candidate

from verigym.core.hashing import content_hash

_MAX_REQUEST_BYTES = 2 * 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-manifest", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--broker-root", type=Path, required=True)
    parser.add_argument("--verifier-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--poll-interval-s", type=float, default=0.1)
    return parser


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _read_manifest(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    value = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    identity = dict(value)
    expected = identity.pop("manifest_hash", None)
    if (
        value.get("format_id") != "verigym_online_tasks_v1"
        or not isinstance(expected, str)
        or _canonical_hash(identity) != expected
    ):
        raise RuntimeError("online task manifest identity is invalid")
    bindings: dict[str, dict[str, Any]] = {}
    for binding in value.get("tasks", []):
        task_id = binding.get("task_id")
        public = binding.get("public_record")
        if (
            not isinstance(task_id, str)
            or task_id in bindings
            or not isinstance(public, dict)
            or public.get("task_id") != task_id
            or public.get("hidden_assets_included") is not False
            or public.get("record_hash") != binding.get("public_input_hash")
        ):
            raise RuntimeError("online task manifest has an invalid task binding")
        bindings[task_id] = binding
    if not bindings:
        raise RuntimeError("online task manifest has no task bindings")
    return value, bindings


def _read_request(path: Path) -> dict[str, Any]:
    metadata = os.lstat(path)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size <= 0
        or metadata.st_size > _MAX_REQUEST_BYTES
    ):
        raise RuntimeError("online verifier request is not a bounded regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    identity = dict(value)
    expected = identity.pop("request_hash", None)
    if (
        value.get("format_id") != "verigym_online_verifier_request_v1"
        or not isinstance(expected, str)
        or _canonical_hash(identity) != expected
        or path.name != f"{value.get('request_id')}.json"
    ):
        raise RuntimeError("online verifier request identity is invalid")
    return value


def _response(request: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_online_verifier_response_v1",
        "request_id": request["request_id"],
        "request_hash": request["request_hash"],
        **result,
    }
    return {**base, "response_hash": _canonical_hash(base)}


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    manifest, bindings = _read_manifest(arguments.task_manifest)
    broker = arguments.broker_root.resolve()
    requests = broker / "requests"
    responses = broker / "responses"
    requests.mkdir(parents=True, exist_ok=True)
    responses.mkdir(parents=True, exist_ok=True)
    output = arguments.verifier_output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    processed: list[dict[str, Any]] = []
    while True:
        pending = [
            path for path in sorted(requests.glob("*.json")) if not (responses / path.name).exists()
        ]
        for path in pending:
            request: dict[str, Any] = {}
            try:
                request = _read_request(path)
                binding = bindings.get(str(request.get("task_id")))
                if binding is None:
                    raise RuntimeError("online verifier request references an unbound task")
                evaluator_binding = {
                    **binding,
                    "source_root": str(arguments.source_root.resolve(strict=True)),
                }
                result = score_online_candidate(
                    binding=evaluator_binding, request=request, output=output
                )
            except Exception as exc:
                if not request:
                    raise
                result = {
                    "infrastructure_valid": False,
                    "resolved": None,
                    "compile_status": "error",
                    "task_hash": None,
                    "verifier_hash": None,
                    "candidate_hash": request.get("candidate_hash"),
                    "error_category": type(exc).__name__,
                }
            response = _response(request, result)
            _atomic_json(responses / path.name, response)
            processed.append(
                {
                    "request_hash": request["request_hash"],
                    "response_hash": response["response_hash"],
                    "task_id": request["task_id"],
                    "infrastructure_valid": result["infrastructure_valid"],
                    "resolved": result["resolved"],
                }
            )
        if (broker / "STOP").is_file() and not pending:
            break
        time.sleep(arguments.poll_interval_s)
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_online_verifier_broker_report_v1",
        "task_manifest_hash": manifest["manifest_hash"],
        "request_count": len(processed),
        "infrastructure_invalid_count": sum(
            item["infrastructure_valid"] is not True for item in processed
        ),
        "resolved_count": sum(item["resolved"] is True for item in processed),
        "requests": processed,
        "hidden_assets_exported_to_training_container": False,
        "docker_socket_exported_to_training_container": False,
        "credential_values_included": False,
    }
    _atomic_json(arguments.report, {**base, "report_hash": content_hash(base)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

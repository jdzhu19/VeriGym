#!/usr/bin/env python3
"""Serve online rLLM repository actions through host-owned VeriGym episodes."""

from __future__ import annotations

import argparse
import re
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from verigym_training_reference.online_repository import run_online_repository_session
from verigym_training_reference.repository_broker_protocol import (
    atomic_json,
    canonical_hash,
    hashed_message,
    read_hashed_message,
)

from verigym.core.hashing import content_hash

_SESSION_ID = re.compile(r"^[0-9a-f]{64}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-manifest", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--broker-root", type=Path, required=True)
    parser.add_argument("--verifier-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--poll-interval-s", type=float, default=0.1)
    return parser


def _read_manifest(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    value = read_hashed_message(path.resolve(strict=True), hash_field="manifest_hash")
    if value.get("format_id") != "verigym_online_tasks_v1":
        raise RuntimeError("online repository manifest format is unsupported")
    bindings: dict[str, dict[str, Any]] = {}
    for binding in value.get("tasks", []):
        if not isinstance(binding, dict):
            raise RuntimeError("online repository manifest contains a malformed binding")
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
            raise RuntimeError("online repository manifest has an invalid public task binding")
        bindings[task_id] = binding
    if not bindings:
        raise RuntimeError("online repository manifest has no task bindings")
    return value, bindings


def _failure_response(
    *,
    broker_root: Path,
    request: dict[str, Any],
    error_category: str,
) -> None:
    session_id = str(request["session_id"])
    request_root = broker_root / "requests" / session_id
    turns = sorted(request_root.glob("turn-*.json"))
    if turns:
        name = turns[-1].name
        turn = int(name.removeprefix("turn-").removesuffix(".json"))
    else:
        name = "initial.json"
        turn = None
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_online_repository_response_v1",
        "session_id": session_id,
        "task_id": request["task_id"],
        "public_input_hash": request["public_input_hash"],
        "turn": turn,
        "terminal": True,
        "observation": None,
        "observation_truncated": False,
        "infrastructure_valid": False,
        "resolved": None,
        "error_category": error_category,
        "protocol_error": None,
        "state": "awaiting_action",
    }
    response_root = broker_root / "responses" / session_id
    response_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    atomic_json(response_root / name, hashed_message(base, hash_field="response_hash"))


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    manifest, bindings = _read_manifest(arguments.task_manifest)
    source_root = arguments.source_root.resolve(strict=True)
    broker_root = arguments.broker_root.resolve()
    requests = broker_root / "requests"
    responses = broker_root / "responses"
    requests.mkdir(parents=True, exist_ok=True)
    responses.mkdir(parents=True, exist_ok=True)
    output = arguments.verifier_output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    threads: dict[str, threading.Thread] = {}
    results: list[dict[str, Any]] = []
    lock = threading.Lock()

    def run_session(binding: dict[str, Any], request: dict[str, Any]) -> None:
        try:
            result = run_online_repository_session(
                binding=binding,
                open_request=request,
                source_root=source_root,
                broker_root=broker_root,
                output=output,
            )
        except Exception as exc:
            _failure_response(
                broker_root=broker_root,
                request=request,
                error_category=type(exc).__name__,
            )
            result = {
                "session_id": request["session_id"],
                "task_id": request["task_id"],
                "run_id": None,
                "infrastructure_valid": False,
                "resolved": None,
                "terminal_hash": None,
                "error_category": type(exc).__name__,
            }
        with lock:
            results.append(result)

    while True:
        for path in sorted(requests.glob("*/open.json")):
            session_id = path.parent.name
            if session_id in threads:
                continue
            if not _SESSION_ID.fullmatch(session_id) or path.parent.is_symlink():
                raise RuntimeError("online repository request uses an unsafe session path")
            request = read_hashed_message(path, hash_field="request_hash")
            binding = bindings.get(str(request.get("task_id")))
            if (
                request.get("format_id") != "verigym_online_repository_open_v1"
                or request.get("session_id") != session_id
                or binding is None
                or request.get("public_input_hash") != binding.get("public_input_hash")
            ):
                raise RuntimeError("online repository open request identity is invalid")
            thread = threading.Thread(
                target=run_session,
                args=(binding, request),
                name=f"verigym-online-repository-{session_id[:12]}",
            )
            threads[session_id] = thread
            thread.start()
        if (broker_root / "STOP").is_file() and all(
            not thread.is_alive() for thread in threads.values()
        ):
            break
        time.sleep(arguments.poll_interval_s)
    for thread in threads.values():
        thread.join()
    ordered = sorted(results, key=lambda item: str(item["session_id"]))
    base = {
        "schema_version": "1.0",
        "format_id": "verigym_online_repository_broker_report_v1",
        "task_manifest_hash": manifest["manifest_hash"],
        "session_count": len(ordered),
        "infrastructure_invalid_count": sum(
            item.get("infrastructure_valid") is not True for item in ordered
        ),
        "resolved_count": sum(item.get("resolved") is True for item in ordered),
        "sessions": ordered,
        "hidden_assets_exported_to_training_container": False,
        "source_root_exported_to_training_container": False,
        "docker_socket_exported_to_training_container": False,
        "hidden_assets_exported_to_training_process": False,
        "source_root_exported_to_training_process": False,
        "docker_socket_exported_to_training_process": False,
        "credential_values_included": False,
        "broker_protocol_hash": content_hash(
            {
                "open": "verigym_online_repository_open_v1",
                "action": "verigym_online_repository_action_v1",
                "response": "verigym_online_repository_response_v1",
            }
        ),
    }
    report = {**base, "report_hash": canonical_hash(base)}
    atomic_json(arguments.report, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

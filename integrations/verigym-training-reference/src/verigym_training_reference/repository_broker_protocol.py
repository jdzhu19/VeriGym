"""Hash-bound filesystem protocol for online repository-agent rollouts."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

_MAX_MESSAGE_BYTES = 2 * 1024 * 1024


def canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
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


def hashed_message(base: dict[str, Any], *, hash_field: str) -> dict[str, Any]:
    return {**base, hash_field: canonical_hash(base)}


def read_hashed_message(path: Path, *, hash_field: str) -> dict[str, Any]:
    metadata = os.lstat(path)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or not 0 < metadata.st_size <= _MAX_MESSAGE_BYTES
    ):
        raise RuntimeError("repository broker message is not a bounded regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("repository broker message root is not an object")
    identity = dict(value)
    expected = identity.pop(hash_field, None)
    if not isinstance(expected, str) or canonical_hash(identity) != expected:
        raise RuntimeError("repository broker message identity changed")
    return value


class RepositoryBrokerClient:
    """Training-side client; it can see only public requests and bounded responses."""

    def __init__(
        self,
        root: str | Path,
        *,
        task_id: str,
        public_input_hash: str,
        uid: str,
        seed: int,
        sample_index: int,
        timeout_s: int,
        nonce: str | None = None,
    ) -> None:
        self.root = Path(root).resolve(strict=True)
        self.requests = (self.root / "requests").resolve(strict=True)
        self.responses = (self.root / "responses").resolve(strict=True)
        for path in (self.requests, self.responses):
            if not path.is_dir() or path.is_symlink():
                raise RuntimeError("repository broker endpoint is not a real directory")
        self.task_id = task_id
        self.public_input_hash = public_input_hash
        self.seed = seed
        self.sample_index = sample_index
        self.timeout_s = timeout_s
        session_nonce = nonce or uuid.uuid4().hex
        self.session_id = hashlib.sha256(
            f"{uid}:{task_id}:{public_input_hash}:{session_nonce}".encode()
        ).hexdigest()
        self.request_root = self.requests / self.session_id
        self.response_root = self.responses / self.session_id

    def open(self) -> dict[str, Any]:
        if self.request_root.exists():
            raise RuntimeError("repository broker session already exists")
        self.request_root.mkdir(mode=0o700)
        base = {
            "schema_version": "1.0",
            "format_id": "verigym_online_repository_open_v1",
            "session_id": self.session_id,
            "task_id": self.task_id,
            "public_input_hash": self.public_input_hash,
            "seed": self.seed,
            "sample_index": self.sample_index,
        }
        atomic_json(
            self.request_root / "open.json",
            hashed_message(base, hash_field="request_hash"),
        )
        return self._wait(self.response_root / "initial.json")

    def act(self, turn: int, raw_action: str) -> dict[str, Any]:
        if turn < 0:
            raise ValueError("repository broker turn must be non-negative")
        encoded = raw_action.encode("utf-8")
        if not encoded or len(encoded) > _MAX_MESSAGE_BYTES:
            raise RuntimeError("repository action is empty or exceeds the broker request bound")
        base = {
            "schema_version": "1.0",
            "format_id": "verigym_online_repository_action_v1",
            "session_id": self.session_id,
            "task_id": self.task_id,
            "public_input_hash": self.public_input_hash,
            "turn": turn,
            "raw_action": raw_action,
            "raw_action_sha256": hashlib.sha256(encoded).hexdigest(),
        }
        name = f"turn-{turn:04d}.json"
        atomic_json(self.request_root / name, hashed_message(base, hash_field="request_hash"))
        return self._wait(self.response_root / name)

    def _wait(self, path: Path) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_s
        while not path.is_file():
            if (self.root / "STOP").is_file():
                raise RuntimeError("repository broker stopped before returning a response")
            if time.monotonic() >= deadline:
                raise RuntimeError("repository broker response timed out")
            time.sleep(0.05)
        response = read_hashed_message(path, hash_field="response_hash")
        if (
            response.get("format_id") != "verigym_online_repository_response_v1"
            or response.get("session_id") != self.session_id
            or response.get("task_id") != self.task_id
            or response.get("public_input_hash") != self.public_input_hash
        ):
            raise RuntimeError("repository broker returned a response for another session")
        return response


__all__ = [
    "RepositoryBrokerClient",
    "atomic_json",
    "canonical_hash",
    "hashed_message",
    "read_hashed_message",
]

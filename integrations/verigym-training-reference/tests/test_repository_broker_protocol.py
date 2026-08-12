from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from verigym_training_reference.repository_broker_protocol import (
    RepositoryBrokerClient,
    atomic_json,
    hashed_message,
    read_hashed_message,
)


def test_repository_broker_client_binds_session_turn_and_action_hash(tmp_path: Path) -> None:
    root = tmp_path / "broker"
    requests = root / "requests"
    responses = root / "responses"
    requests.mkdir(parents=True)
    responses.mkdir()
    client = RepositoryBrokerClient(
        root,
        task_id="suite/repository-task",
        public_input_hash="a" * 64,
        uid="rollout-1",
        seed=3,
        sample_index=0,
        timeout_s=5,
        nonce="fixed-nonce",
    )

    def serve() -> None:
        open_path = requests / client.session_id / "open.json"
        while not open_path.is_file():
            time.sleep(0.01)
        opened = read_hashed_message(open_path, hash_field="request_hash")
        initial = {
            "schema_version": "1.0",
            "format_id": "verigym_online_repository_response_v1",
            "session_id": client.session_id,
            "task_id": opened["task_id"],
            "public_input_hash": opened["public_input_hash"],
            "turn": None,
            "terminal": False,
            "observation": {"task_description": "repair it"},
            "observation_truncated": False,
            "prompt_contract": {"protocol": "repository_action.v2"},
            "public_test_ids": [],
            "public_test_required": False,
            "max_completion_calls": 3,
        }
        response_root = responses / client.session_id
        response_root.mkdir()
        atomic_json(
            response_root / "initial.json",
            hashed_message(initial, hash_field="response_hash"),
        )
        action_path = requests / client.session_id / "turn-0000.json"
        while not action_path.is_file():
            time.sleep(0.01)
        action = read_hashed_message(action_path, hash_field="request_hash")
        assert action["turn"] == 0
        assert action["raw_action_sha256"]
        terminal = {
            "schema_version": "1.0",
            "format_id": "verigym_online_repository_response_v1",
            "session_id": client.session_id,
            "task_id": action["task_id"],
            "public_input_hash": action["public_input_hash"],
            "turn": 0,
            "terminal": True,
            "observation": None,
            "observation_truncated": False,
            "infrastructure_valid": True,
            "resolved": False,
            "termination_reason": "model_output_invalid",
        }
        atomic_json(
            response_root / "turn-0000.json",
            hashed_message(terminal, hash_field="response_hash"),
        )

    thread = threading.Thread(target=serve)
    thread.start()
    initial = client.open()
    raw = json.dumps(
        {"protocol": "repository_action.v2", "action": "finish", "arguments": {"message": "x"}}
    )
    terminal = client.act(0, raw)
    thread.join(timeout=2)

    assert initial["max_completion_calls"] == 3
    assert terminal["terminal"] is True
    assert terminal["resolved"] is False
    assert not thread.is_alive()


def test_repository_broker_client_rejects_response_for_another_task(tmp_path: Path) -> None:
    root = tmp_path / "broker"
    (root / "requests").mkdir(parents=True)
    (root / "responses").mkdir()
    client = RepositoryBrokerClient(
        root,
        task_id="suite/repository-task",
        public_input_hash="a" * 64,
        uid="rollout-1",
        seed=3,
        sample_index=0,
        timeout_s=5,
        nonce="fixed-nonce",
    )

    def serve_wrong_task() -> None:
        open_path = root / "requests" / client.session_id / "open.json"
        while not open_path.is_file():
            time.sleep(0.01)
        response_root = root / "responses" / client.session_id
        response_root.mkdir()
        base = {
            "schema_version": "1.0",
            "format_id": "verigym_online_repository_response_v1",
            "session_id": client.session_id,
            "task_id": "suite/other-task",
            "public_input_hash": "a" * 64,
            "turn": None,
            "terminal": False,
        }
        atomic_json(
            response_root / "initial.json",
            hashed_message(base, hash_field="response_hash"),
        )

    thread = threading.Thread(target=serve_wrong_task)
    thread.start()
    try:
        try:
            client.open()
        except RuntimeError as exc:
            assert "another session" in str(exc)
        else:  # pragma: no cover - defensive assertion
            raise AssertionError("cross-task response was accepted")
    finally:
        thread.join(timeout=2)

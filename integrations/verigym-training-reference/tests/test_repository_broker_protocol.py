from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest

from verigym_training_reference.repository_broker_protocol import (
    RepositoryBrokerClient,
    atomic_json,
    atomic_json_new,
    await_model_or_terminal,
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
            response_root / "terminal.json",
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


def test_repository_broker_terminal_does_not_replace_a_turn_response(tmp_path: Path) -> None:
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
    publish_terminal = threading.Event()

    def response(*, turn: int | None, terminal: bool) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "format_id": "verigym_online_repository_response_v1",
            "session_id": client.session_id,
            "task_id": "suite/repository-task",
            "public_input_hash": "a" * 64,
            "turn": turn,
            "terminal": terminal,
            "observation": None,
            "observation_truncated": False,
        }

    def serve() -> None:
        open_path = requests / client.session_id / "open.json"
        while not open_path.is_file():
            time.sleep(0.01)
        response_root = responses / client.session_id
        response_root.mkdir()
        initial = {
            **response(turn=None, terminal=False),
            "prompt_contract": {"protocol": "repository_action.v2"},
            "public_test_ids": [],
            "public_test_required": False,
            "max_completion_calls": 3,
        }
        atomic_json(
            response_root / "initial.json",
            hashed_message(initial, hash_field="response_hash"),
        )
        action_path = requests / client.session_id / "turn-0000.json"
        while not action_path.is_file():
            time.sleep(0.01)
        nonterminal = {
            **response(turn=0, terminal=False),
            "accepted": True,
            "action_name": "read_file",
            "state": "awaiting_action",
        }
        atomic_json(
            response_root / "turn-0000.json",
            hashed_message(nonterminal, hash_field="response_hash"),
        )
        assert publish_terminal.wait(timeout=2)
        terminal = {
            **response(turn=0, terminal=True),
            "infrastructure_valid": True,
            "resolved": False,
            "termination_reason": "wall_time_exhausted",
        }
        atomic_json_new(
            response_root / "terminal.json",
            hashed_message(terminal, hash_field="response_hash"),
        )

    thread = threading.Thread(target=serve)
    thread.start()
    client.open()
    raw = json.dumps({"protocol": "repository_action.v2", "action": "read_file", "arguments": {}})
    first = client.act(0, raw)
    publish_terminal.set()
    deadline = time.monotonic() + 2
    while client.poll_terminal() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    terminal = client.act(1, raw)
    thread.join(timeout=2)

    persisted = read_hashed_message(
        responses / client.session_id / "turn-0000.json", hash_field="response_hash"
    )
    assert first["terminal"] is False
    assert persisted["terminal"] is False
    assert terminal["terminal"] is True
    assert not (requests / client.session_id / "turn-0001.json").exists()
    assert not thread.is_alive()


def test_atomic_json_new_rejects_terminal_replacement(tmp_path: Path) -> None:
    path = tmp_path / "terminal.json"
    atomic_json_new(path, {"terminal": True, "value": 1})

    with pytest.raises(FileExistsError):
        atomic_json_new(path, {"terminal": True, "value": 2})

    assert json.loads(path.read_text(encoding="utf-8"))["value"] == 1


def test_terminal_cancels_an_obsolete_model_response() -> None:
    async def exercise() -> None:
        cancelled = asyncio.Event()

        async def generate() -> str:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        async def terminal() -> dict[str, object]:
            await asyncio.sleep(0.01)
            return {"terminal": True, "resolved": False}

        terminal_task = asyncio.create_task(terminal())
        model, outcome = await await_model_or_terminal(generate(), terminal_task)
        assert model is None
        assert outcome == {"terminal": True, "resolved": False}
        assert cancelled.is_set()

    asyncio.run(exercise())


def test_model_response_keeps_terminal_wait_alive_for_the_next_turn() -> None:
    async def exercise() -> None:
        release_terminal = asyncio.Event()

        async def generate() -> str:
            return "next action"

        async def terminal() -> dict[str, object]:
            await release_terminal.wait()
            return {"terminal": True, "resolved": False}

        terminal_task = asyncio.create_task(terminal())
        model, outcome = await await_model_or_terminal(generate(), terminal_task)
        assert model == "next action"
        assert outcome is None
        assert not terminal_task.done()
        release_terminal.set()
        assert await terminal_task == {"terminal": True, "resolved": False}

    asyncio.run(exercise())


def test_four_terminal_futures_all_recover_without_waiting_for_generation() -> None:
    async def exercise_one(index: int) -> tuple[int, bool]:
        cancelled = asyncio.Event()

        async def generate() -> str:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        async def terminal() -> dict[str, object]:
            await asyncio.sleep(0.01 + index * 0.005)
            return {"terminal": True, "session": index}

        model, outcome = await await_model_or_terminal(generate(), asyncio.create_task(terminal()))
        assert model is None
        assert outcome == {"terminal": True, "session": index}
        return index, cancelled.is_set()

    async def exercise_group() -> list[tuple[int, bool]]:
        return await asyncio.gather(*(exercise_one(index) for index in range(4)))

    assert asyncio.run(exercise_group()) == [(0, True), (1, True), (2, True), (3, True)]

from __future__ import annotations

from pathlib import Path

from verigym_openhands import hwe_stop_hook
from verigym_openhands._recovery import (
    OPENHANDS_FORMAT_RECOVERY_MESSAGE_SHA256,
    OPENHANDS_FORMAT_RECOVERY_REASON,
)


def test_stop_hook_allows_only_broker_typed_finish(monkeypatch, tmp_path: Path) -> None:
    assert (
        hwe_stop_hook.OPENHANDS_FORMAT_RECOVERY_MESSAGE_SHA256
        == OPENHANDS_FORMAT_RECOVERY_MESSAGE_SHA256
    )
    state = tmp_path / "format-recovery.json"
    monkeypatch.setattr(
        hwe_stop_hook,
        "query_terminal_status",
        lambda _path: {
            "finished": True,
            "policy_failed": False,
            "infrastructure_failed": False,
        },
    )

    exit_code, result = hwe_stop_hook.evaluate_stop(tmp_path / "broker.sock", state)

    assert exit_code == 0
    assert result == {"decision": "allow", "reason": "broker typed finish observed"}
    assert not state.exists()


def test_stop_hook_recovers_once_then_exhausts_budget(monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "format-recovery.json"
    monkeypatch.setattr(
        hwe_stop_hook,
        "query_terminal_status",
        lambda _path: {
            "finished": False,
            "policy_failed": False,
            "infrastructure_failed": False,
        },
    )

    first_code, first = hwe_stop_hook.evaluate_stop(tmp_path / "broker.sock", state)
    second_code, second = hwe_stop_hook.evaluate_stop(tmp_path / "broker.sock", state)

    assert first_code == 2
    assert first == {"decision": "deny", "reason": OPENHANDS_FORMAT_RECOVERY_REASON}
    assert hwe_stop_hook.read_recovery_count(state) == 1
    assert second_code == 0
    assert second == {"decision": "allow", "reason": "format recovery budget exhausted"}


def test_stop_hook_does_not_recover_terminal_broker_failure(monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "format-recovery.json"
    monkeypatch.setattr(
        hwe_stop_hook,
        "query_terminal_status",
        lambda _path: {
            "finished": False,
            "policy_failed": True,
            "infrastructure_failed": False,
        },
    )

    exit_code, result = hwe_stop_hook.evaluate_stop(tmp_path / "broker.sock", state)

    assert exit_code == 0
    assert result == {"decision": "allow", "reason": "broker terminal failure observed"}
    assert not state.exists()

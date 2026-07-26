from __future__ import annotations

import os
from pathlib import Path

import pytest
from verigym_codex_cli.capabilities import discover_capabilities

pytestmark = [
    pytest.mark.codex_cli,
    pytest.mark.codex_cli_readonly_agent,
    pytest.mark.codex_cli_agent,
]


def test_real_codex_prerequisites_are_explicit_and_discovery_is_zero_call() -> None:
    if os.environ.get("VERIGYM_RUN_CODEX_CLI_TESTS") != "1":
        pytest.skip("real Codex CLI tests require explicit opt-in")
    missing = [
        name
        for name in (
            "VERIGYM_CODEX_BINARY",
            "VERIGYM_CODEX_MODEL",
            "VERIGYM_CODEX_AUTH_MODE",
        )
        if not os.environ.get(name, "").strip()
    ]
    assert not missing, f"opted-in real Codex test is missing: {', '.join(missing)}"
    binary = Path(os.environ["VERIGYM_CODEX_BINARY"])
    assert binary.is_absolute(), "VERIGYM_CODEX_BINARY must be an explicit absolute path"
    _identity, report = discover_capabilities(force=True)
    assert report.model_call_count == 0
    assert report.diagnostic_process_count == 3

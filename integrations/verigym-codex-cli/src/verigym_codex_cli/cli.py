"""Zero-call diagnostics for the Codex CLI integration."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .capabilities import discover_capabilities
from .preflight import run_auth_preflight
from .util import atomic_json


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="verigym-codex")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser(
        "doctor",
        help="Discover Codex CLI capabilities without making a model request.",
    )
    doctor.add_argument("--json", type=Path, required=True, dest="json_path")
    auth_preflight = commands.add_parser(
        "auth-preflight",
        help="Check existing authentication without a model call or login flow.",
    )
    auth_preflight.add_argument("--json", type=Path, required=True, dest="json_path")
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    if arguments.command == "doctor":
        try:
            _executable, report = discover_capabilities(force=True)
            atomic_json(arguments.json_path, report.safe_dict())
        except Exception as exc:
            print(f"verigym-codex doctor: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        print(arguments.json_path)
    elif arguments.command == "auth-preflight":
        try:
            result = run_auth_preflight()
            atomic_json(arguments.json_path, result.safe_dict())
        except Exception as exc:
            print(f"verigym-codex auth-preflight: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        if result.auth_resolution_message is not None:
            print(result.auth_resolution_message)
        print(arguments.json_path)
        if not result.external_prerequisite_satisfied:
            raise SystemExit(3)


if __name__ == "__main__":  # pragma: no cover
    main()

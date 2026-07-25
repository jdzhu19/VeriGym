"""Zero-call diagnostics for the Codex CLI integration."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .capabilities import discover_capabilities
from .util import atomic_json


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="verigym-codex")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser(
        "doctor",
        help="Discover Codex CLI capabilities without making a model request.",
    )
    doctor.add_argument("--json", type=Path, required=True, dest="json_path")
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    if arguments.command == "doctor":
        try:
            _executable, report = discover_capabilities(force=True)
            atomic_json(arguments.json_path, report.safe_dict())
        except Exception as exc:
            print(f"verigym-codex doctor: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        print(arguments.json_path)


if __name__ == "__main__":  # pragma: no cover
    main()

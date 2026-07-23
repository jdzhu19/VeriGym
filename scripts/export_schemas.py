"""Export or check the committed persistent JSON Schemas."""

from __future__ import annotations

import argparse
from pathlib import Path

from verigym.schema_export import export_schemas


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/schemas"),
    )
    arguments = parser.parse_args()
    drift = export_schemas(arguments.output, check=arguments.check)
    if arguments.check and drift:
        print("schema drift: " + ", ".join(drift))
        return 1
    print(f"{'checked' if arguments.check else 'exported'} {len(drift)} changed schema file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


@pytest.fixture
def synthetic_source(tmp_path: Path) -> Path:
    root = tmp_path / "rtl-repo"
    data = root / "data"
    data.mkdir(parents=True)
    (root / "LICENSE").write_text(
        "Apache License\nVersion 2.0, January 2004\n",
        encoding="utf-8",
    )
    (root / "VERIGYM_SYNTHETIC_FIXTURE").write_text(
        "Synthetic layout fixture; not benchmark data.\n",
        encoding="utf-8",
    )
    pq.write_table(pa.Table.from_pylist([_row("train", 0, "|")]), data / "train-demo.parquet")
    pq.write_table(
        pa.Table.from_pylist(
            [
                _row("test", 10, "&"),
                _row("test", 11, "^"),
            ]
        ),
        data / "test-demo.parquet",
    )
    return root


def _row(split: str, index: int, operator: str) -> dict[str, object]:
    file_path = f"rtl/{split}_{index}.v"
    cropped = "module demo(input a, input b, output y);\n"
    target = f"assign y = a {operator} b;"
    return {
        "repo_name": "verigym/synthetic-rtl",
        "file_path": file_path,
        "next_line": target,
        "context": [
            {
                "path": "rtl/helper.v",
                "snippet": "module helper;\nendmodule\n",
            }
        ],
        "created_at": "2024-01-01T00:00:00Z",
        "all_code": f"{cropped}{target}\nendmodule\n",
        "cropped_code": cropped,
        "level": 1,
        "__index_level_0__": index,
    }

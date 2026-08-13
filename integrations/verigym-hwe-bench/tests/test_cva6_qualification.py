from __future__ import annotations

import json
from pathlib import Path

from verigym_hwe_bench import cva6_qualification
from verigym_hwe_bench.cva6_qualification import select_cva6_candidates


def _row(number: int, files: int = 1, lines: int = 2) -> dict[str, object]:
    patch_lines = ["--- a/a.sv", "+++ b/a.sv"]
    for index in range(lines // 2):
        patch_lines.extend([f"-old_{index}", f"+new_{index}"])
    return {
        "org": "openhwgroup",
        "repo": "cva6",
        "number": number,
        "modified_files": [f"rtl/file_{index}.sv" for index in range(files)],
        "fix_patch": "\n".join(patch_lines),
    }


def test_cva6_selection_uses_fixed_preference_then_ascending_fallback(tmp_path: Path) -> None:
    preferred = [2032, 2248, 2282, 2468, 2469, 2549, 2589, 2802, 2916, 2944, 3168, 3191]
    rows = [_row(number) for number in preferred]
    rows.extend([_row(100, files=2), _row(99, files=2), _row(97), _row(3171), _row(98, files=3)])
    dataset = tmp_path / "cva6.jsonl"
    dataset.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    selected = select_cva6_candidates(dataset)

    assert [candidate.number for candidate in selected[:12]] == preferred
    assert [candidate.number for candidate in selected[12:]] == [99, 100]
    assert all(candidate.number != 97 for candidate in selected)
    assert all(candidate.number != 3171 for candidate in selected)


def test_cva6_selection_rejects_over_twenty_changed_lines_from_fallback(
    tmp_path: Path,
) -> None:
    rows = [_row(number, files=2) for number in range(1, 14)]
    rows.append(_row(50, files=2, lines=22))
    dataset = tmp_path / "cva6.jsonl"
    dataset.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    selected = select_cva6_candidates(dataset)

    assert all(candidate.number != 50 for candidate in selected)


def test_cva6_qualification_never_opens_untrusted_local_runtime() -> None:
    source = Path(cva6_qualification.__file__).read_text(encoding="utf-8")

    assert 'runtime="local"' not in source
    assert "_zero_model_smoke" in source
    assert "suite.verify_candidate" in source
    assert "normalize_relative_path(relative)" in source


def test_cva6_qualification_treats_empty_verifier_results_as_infrastructure_invalid() -> None:
    assert not cva6_qualification._infrastructure_valid(  # noqa: SLF001
        {
            "base_infrastructure_error": False,
            "base_verifier_results": [],
            "verifier_results": [],
        }
    )

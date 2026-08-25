from __future__ import annotations

import pytest

from verigym.core.integrity import write_run_artifact_manifest
from verigym.core.repository_observation import (
    BOUNDED_REPOSITORY_OBSERVATION_POLICY,
    OMISSION_MARKER,
    RawObservationAuditWriter,
    audit_record,
    bounded_read_view,
    bounded_text_with_marker,
    compact_tool_result,
    list_workspace_entries,
)
from verigym.schemas.common import ErrorCategory
from verigym.schemas.tool import ToolResult


def test_bounded_listing_is_shallow_capped_and_does_not_ignore_vendor_content(
    tmp_path,
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "secret").write_text("private", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.js").write_text("private", encoding="utf-8")
    (tmp_path / "vendor" / "nested").mkdir(parents=True)
    (tmp_path / "vendor" / "nested" / "library.py").write_text("x = 1", encoding="utf-8")

    output, metadata = list_workspace_entries(
        tmp_path,
        relative_path=".",
        recursive=True,
        policy=BOUNDED_REPOSITORY_OBSERVATION_POLICY,
        is_excluded=lambda _path: False,
        workspace_root=tmp_path,
    )

    assert "vendor/" in output
    assert "vendor/nested/" in output
    assert ".git" not in output
    assert "node_modules" not in output
    assert metadata["max_depth"] == 2

    capped, capped_metadata = list_workspace_entries(
        tmp_path,
        relative_path=".",
        recursive=True,
        requested_max_entries=1,
        policy=BOUNDED_REPOSITORY_OBSERVATION_POLICY,
        is_excluded=lambda _path: False,
        workspace_root=tmp_path,
    )
    assert OMISSION_MARKER.split("{", 1)[0] in capped
    assert capped_metadata["omitted_entries"] > 0


def test_read_views_preserve_line_numbers_and_mark_omissions() -> None:
    rtl = "\n".join(
        [
            "module counter(input logic clk);",
            *[f"// implementation detail {index}" for index in range(1, 240)],
            "assign out = clk;",
            "endmodule",
        ]
    )
    concise, metadata = bounded_read_view(
        rtl,
        "rtl/counter.sv",
        policy=BOUNDED_REPOSITORY_OBSERVATION_POLICY,
    )
    assert metadata["view_mode"] == "concise"
    assert "1: module counter" in concise
    assert "[verigym omission:" in concise

    ranged, ranged_metadata = bounded_read_view(
        rtl,
        "rtl/counter.sv",
        start_line=120,
        end_line=122,
        policy=BOUNDED_REPOSITORY_OBSERVATION_POLICY,
    )
    assert ranged_metadata["view_mode"] == "ranged"
    assert "120: // implementation detail 119" in ranged
    assert "119:" not in ranged

    python_view, python_metadata = bounded_read_view(
        "import os\n\ndef repair(value):\n    return value\n",
        "repair.py",
        concise=True,
        policy=BOUNDED_REPOSITORY_OBSERVATION_POLICY,
    )
    assert python_metadata["view_mode"] == "concise"
    assert "3: def repair" in python_view

    with pytest.raises(ValueError, match="outside"):
        bounded_read_view(
            "one line\n",
            "README.md",
            start_line=3,
            policy=BOUNDED_REPOSITORY_OBSERVATION_POLICY,
        )


def test_compact_result_separates_bounded_observation_from_raw_audit(tmp_path) -> None:
    raw_text = "x" * (16 * 1024 + 100)
    result = ToolResult(
        tool="file.read",
        success=True,
        category=ErrorCategory.SUCCESS,
        stdout=raw_text,
    )
    audit_path = tmp_path / "raw-observations.ndjson"
    writer = RawObservationAuditWriter(audit_path, max_bytes=64 * 1024)
    writer(
        audit_record(
            result,
            request={"path": "README.md"},
            policy=BOUNDED_REPOSITORY_OBSERVATION_POLICY,
        )
    )
    compact = compact_tool_result(result, policy=BOUNDED_REPOSITORY_OBSERVATION_POLICY)

    assert compact.output_truncated is True
    assert "[verigym omission:" in compact.stdout
    assert len(compact.stdout.encode("utf-8")) <= 16 * 1024
    assert raw_text in audit_path.read_text(encoding="utf-8")
    manifest = writer.finalize()
    assert manifest["record_count"] == 1
    assert audit_path.stat().st_mode & 0o777 == 0o600
    assert audit_path.with_name("raw-observations-manifest.json").is_file()

    with pytest.raises(ValueError, match="secret scan"):
        writer({"result": {"stdout": "api_key=abcdefgh"}})


def test_private_audit_tree_is_not_added_to_public_run_manifest(tmp_path) -> None:
    for relative in (
        "run_manifest.json",
        "task_snapshot.json",
        "trace.jsonl",
        "scorecard.json",
        "workspace_diff.patch",
    ):
        (tmp_path / relative).write_text("{}", encoding="utf-8")
    for directory in ("candidate", "logs", "artifacts"):
        (tmp_path / directory).mkdir()
    private = tmp_path / "private-audit"
    private.mkdir(mode=0o700)
    (private / "raw-observations.ndjson").write_text(
        '{"secret":"must remain outside the public manifest"}\n', encoding="utf-8"
    )

    manifest = write_run_artifact_manifest(tmp_path, "run-id")

    paths = {entry.relative_path for entry in manifest.entries}
    assert "private-audit/raw-observations.ndjson" not in paths
    assert "private-audit" not in paths


def test_text_bound_is_utf8_safe_and_explicit() -> None:
    bounded, truncated = bounded_text_with_marker("🙂" * 500, 128, description="unicode")
    assert truncated is True
    assert len(bounded.encode("utf-8")) <= 128
    bounded.encode("utf-8").decode("utf-8")


def test_legacy_search_public_test_and_diff_bounds_are_fixed() -> None:
    limits = {
        "file.search": 8 * 1024,
        "repository.public_test": 16 * 1024,
        "file.diff": 32 * 1024,
    }
    for tool, limit in limits.items():
        result = ToolResult(
            tool=tool,
            success=True,
            category=ErrorCategory.SUCCESS,
            stdout="x" * (limit + 1),
        )
        compact = compact_tool_result(result, policy=None)
        assert compact.output_truncated is True
        assert len(compact.stdout.encode("utf-8")) <= limit
        assert "[verigym omission:" in compact.stdout

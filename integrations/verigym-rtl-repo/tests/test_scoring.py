from __future__ import annotations

from pathlib import Path

from verigym.runtimes.local import LocalRuntime
from verigym.schemas.runtime import SessionSpec
from verigym.tools.base import ToolContext

from verigym_rtl_repo.scoring import (
    METRIC_PROFILE,
    RtlRepoScoreTool,
    official_edit_similarity,
    official_postprocess,
)


def test_official_postprocess_selects_first_noncomment_or_last_comment() -> None:
    assert official_postprocess("// explanation\n\nassign y = a;\nignored") == "assign y = a;"
    assert official_postprocess("// first\n// last\n") == "// last"
    assert official_postprocess("\n") == ""


def test_official_edit_similarity_has_percent_scale() -> None:
    assert official_edit_similarity("assign y = a;", "assign y = a;") == 100
    assert 0 < official_edit_similarity("assign y = a;", "assign y = b;") < 100


def test_score_tool_emits_native_metrics_without_text(tmp_path: Path) -> None:
    source = tmp_path / "session-source"
    source.mkdir()
    (source / "completion.txt").write_text(
        "// explanation\nassign y = a & b;\nignored\n",
        encoding="utf-8",
    )
    verifier = source / "verifier"
    verifier.mkdir()
    (verifier / "target.txt").write_text("assign y = a & b;", encoding="utf-8")
    session = LocalRuntime().create_session(
        SessionSpec(source_dir=str(source), label="rtl-repo-score", max_output_bytes=64_000)
    )
    try:
        result = RtlRepoScoreTool().execute(
            {
                "candidate": "completion.txt",
                "target": "verifier/target.txt",
                "metric_profile": METRIC_PROFILE,
                "split": "test",
            },
            ToolContext(session=session),
        )
    finally:
        session.close()

    assert result.success
    assert result.metadata["exact_match"] is True
    assert result.metadata["edit_similarity"] == 100.0
    assert result.metadata["benchmark_metrics"] == {
        "exact_match": 100.0,
        "edit_similarity": 100.0,
    }
    assert "assign y" not in result.model_dump_json()

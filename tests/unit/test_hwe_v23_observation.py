from __future__ import annotations

import hashlib

from verigym.hwe.observation import HweObservationCompactor
from verigym.hwe.profiles import HWE_COLLECTION_PROFILE_V2_ID


class _CharacterCounter:
    tokenizer_id = "tiktoken-0.7.0/o200k_base"
    tokenizer_hash = hashlib.sha256(b"tiktoken==0.7.0\x00o200k_base").hexdigest()

    def count(self, text: str) -> int:
        return len(text)


class _FiveBytesPerTokenCounter(_CharacterCounter):
    def count(self, text: str) -> int:
        return (len(text.encode("utf-8")) + 4) // 5


def _compactor(*, stream_sized: bool = False) -> HweObservationCompactor:
    return HweObservationCompactor(
        _FiveBytesPerTokenCounter() if stream_sized else _CharacterCounter(),
        profile_id=HWE_COLLECTION_PROFILE_V2_ID,
        v23_bounded_projection=True,
    )


def test_v23_read_projection_is_deterministic_and_never_exceeds_400_visible_lines() -> None:
    source = "\n".join(f"line-{index:04d}" for index in range(700))

    first = _compactor().compact("read", source, path="rtl/core.sv")
    second = _compactor().compact("read", source, path="rtl/core.sv")

    assert first.text == second.text
    assert len(first.text.splitlines()) <= 400
    assert first.omitted is True
    assert first.raw_sha256 == hashlib.sha256(source.encode()).hexdigest()
    projection = first.metadata
    assert projection["projection_policy"] == "read_head_tail_400_lines_128k_v23"
    assert projection["omitted_lines"] == 301
    assert projection["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert "line-0000" in first.text
    assert "line-0699" in first.text


def test_v23_read_checkpoint_preserves_the_400_line_limit() -> None:
    source = "\n".join(f"x{index}" for index in range(700))
    compact = _compactor().compact("read", source, path="rtl/core.sv")

    noticed = _compactor().append_fixed_notice(
        compact,
        "[Progress checkpoint] Make one focused edit.",
        notice_id="test-checkpoint",
    )

    assert len(noticed.text.splitlines()) <= 400
    assert noticed.text.endswith("[Progress checkpoint] Make one focused edit.")
    assert noticed.metadata["fixed_notice_line_compaction"] is True


def test_v23_shell_streams_bind_raw_hashes_and_omitted_byte_counts() -> None:
    stdout = "H" * (64 * 1024) + "MIDDLE" * 20_000 + "T" * (64 * 1024)
    stderr = "E" * (64 * 1024) + "PRIVATE-MIDDLE" * 12_000 + "R" * (64 * 1024)

    compact = _compactor(stream_sized=True).compact(
        "shell",
        stdout,
        stderr=stderr,
        command="make test",
        cwd=".",
        exit_code=1,
    )

    stdout_projection = compact.metadata["stdout_projection"]
    stderr_projection = compact.metadata["stderr_projection"]
    assert stdout_projection["raw_sha256"] == hashlib.sha256(stdout.encode()).hexdigest()
    assert stderr_projection["raw_sha256"] == hashlib.sha256(stderr.encode()).hexdigest()
    assert stdout_projection["omitted_bytes"] == len("MIDDLE" * 20_000)
    assert stderr_projection["omitted_bytes"] == len("PRIVATE-MIDDLE" * 12_000)
    assert stdout_projection["model_visible_projection_bytes"] > 128 * 1024
    assert stderr_projection["model_visible_projection_bytes"] > 128 * 1024
    assert compact.omitted is True
    assert "H" * (64 * 1024) in compact.text
    assert "T" * (64 * 1024) in compact.text
    assert "E" * (64 * 1024) in compact.text
    assert "R" * (64 * 1024) in compact.text
    assert compact.metadata["view"] == "stream_head_tail"
    assert (
        compact.raw_sha256 == hashlib.sha256(f"{stdout}\n[stderr]\n{stderr}".encode()).hexdigest()
    )


def test_v23_shell_projection_fails_closed_instead_of_dropping_exact_head_tail() -> None:
    stdout = "A" * (256 * 1024)

    try:
        _compactor().compact("shell", stdout)
    except RuntimeError as exc:
        assert "exact head/tail stream projection" in str(exc)
    else:
        raise AssertionError("an over-context exact stream projection was silently shortened")


def test_v23_read_model_visible_result_never_exceeds_128_kib() -> None:
    source = "x" * (256 * 1024)

    compact = _compactor(stream_sized=True).compact("read", source, path="rtl/core.sv")

    assert len(compact.text.encode("utf-8")) <= 128 * 1024
    assert compact.metadata["model_visible_bytes_including_result_header_limit"] == 128 * 1024


def test_v23_projection_records_terminal_cleanup_without_losing_raw_identity() -> None:
    stdout = "\x1b[31merror\x1b[0m\r\n"

    compact = _compactor().compact("shell", stdout)

    projection = compact.metadata["stdout_projection"]
    assert projection["terminal_cleanup_changed"] is True
    assert projection["raw_sha256"] == hashlib.sha256(stdout.encode()).hexdigest()
    assert projection["cleaned_sha256"] != projection["raw_sha256"]
    assert compact.omitted is True

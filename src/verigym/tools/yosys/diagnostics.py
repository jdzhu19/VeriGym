"""Small bounded diagnostic normalizers for Yosys logs."""

from __future__ import annotations

from verigym.schemas.synthesis import SynthesisDiagnostic


def diagnostics_from_log(
    log: str, *, limit: int = 100
) -> tuple[list[SynthesisDiagnostic], list[SynthesisDiagnostic]]:
    warnings: list[SynthesisDiagnostic] = []
    unsupported: list[SynthesisDiagnostic] = []
    for line in log.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if stripped.startswith("Warning:"):
            warnings.append(
                SynthesisDiagnostic(
                    severity="warning",
                    code="yosys_warning",
                    message=stripped[:1000],
                )
            )
        if "unsupported" in lowered or "not supported" in lowered:
            unsupported.append(
                SynthesisDiagnostic(
                    severity="warning",
                    code="unsupported_construct",
                    message=stripped[:1000],
                )
            )
        if len(warnings) + len(unsupported) >= limit:
            break
    return warnings, unsupported


__all__ = ["diagnostics_from_log"]

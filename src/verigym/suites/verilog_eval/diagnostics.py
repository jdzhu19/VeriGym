"""Bounded, versioned diagnostic taxonomy for VerilogEval tool failures."""

from __future__ import annotations

import re

from verigym.schemas.tool import CompletedCommand
from verigym.suites.verilog_eval.schemas import VerilogEvalDiagnosticCode

_COMPILE_PATTERNS: tuple[tuple[VerilogEvalDiagnosticCode, re.Pattern[str]], ...] = (
    (
        VerilogEvalDiagnosticCode.COMPILE_EXPLICIT_CAST_REQUIRED,
        re.compile(r"explicit cast|requires an explicit cast", re.IGNORECASE),
    ),
    (
        VerilogEvalDiagnosticCode.COMPILE_ZERO_WIDTH_CONSTANT,
        re.compile(r"zero[- ](?:width|sized)|sized constant.*zero", re.IGNORECASE),
    ),
    (
        VerilogEvalDiagnosticCode.COMPILE_MISSING_SENSITIVITY,
        re.compile(r"no sensitiv(?:e|ity)|always process has no sensitiv", re.IGNORECASE),
    ),
    (
        VerilogEvalDiagnosticCode.COMPILE_WIRE_ASSIGNMENT,
        re.compile(r"(?:wire|net).*(?:cannot|must not).*(?:assign|procedural)", re.IGNORECASE),
    ),
    (
        VerilogEvalDiagnosticCode.COMPILE_UNKNOWN_MODULE,
        re.compile(r"unknown module|unable to bind.*module", re.IGNORECASE),
    ),
    (
        VerilogEvalDiagnosticCode.COMPILE_PORT_BINDING,
        re.compile(r"(?:port|pin).*(?:not found|not a port|expects|mismatch)", re.IGNORECASE),
    ),
    (
        VerilogEvalDiagnosticCode.COMPILE_SYNTAX_ERROR,
        re.compile(r"syntax error|malformed statement|invalid module item", re.IGNORECASE),
    ),
)


def classify_compile_diagnostic(completed: CompletedCommand) -> VerilogEvalDiagnosticCode:
    """Map compiler text to a stable subtype without retaining additional log content."""

    text = f"{completed.stdout}\n{completed.stderr}"
    for code, pattern in _COMPILE_PATTERNS:
        if pattern.search(text) is not None:
            return code
    return VerilogEvalDiagnosticCode.COMPILE_OTHER


__all__ = ["classify_compile_diagnostic"]

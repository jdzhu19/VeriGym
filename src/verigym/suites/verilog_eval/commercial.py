"""Stable construction helpers for private commercial-verifier assets."""

from __future__ import annotations

import re

_TIMESCALE = re.compile(r"(?m)^[ \t]*`timescale[^\r\n]*")
VCS_MCP_EXCLUSIONS = {
    "Prob099_m2014_q6c": "reference_testbench_port_contract_mismatch",
}


def combined_reference_testbench(reference: str, testbench: str) -> str:
    """Combine official bodies with a VCS-compatible copy of the testbench timescale."""

    separator = "" if reference.endswith(("\n", "\r")) else "\n"
    timescale = _TIMESCALE.search(testbench)
    prelude = (
        f"{timescale.group(0)}\n"
        if timescale is not None and _TIMESCALE.search(reference) is None
        else ""
    )
    return f"{prelude}{reference}{separator}{testbench}"


__all__ = ["VCS_MCP_EXCLUSIONS", "combined_reference_testbench"]

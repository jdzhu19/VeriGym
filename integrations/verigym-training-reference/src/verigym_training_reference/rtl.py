"""Small dependency-free RTL response normalization helpers."""

from __future__ import annotations

import re

_VERILOG_BLOCK = re.compile(r"<verilog>\s*(.*?)\s*</verilog>", re.DOTALL | re.IGNORECASE)
_FENCED_BLOCK = re.compile(r"```(?:system)?verilog\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_rtl_candidate(response: str) -> tuple[str, str]:
    tagged = _VERILOG_BLOCK.search(response)
    if tagged is not None:
        return tagged.group(1).strip() + "\n", "verilog_tags"
    fenced = _FENCED_BLOCK.search(response)
    if fenced is not None:
        return fenced.group(1).strip() + "\n", "markdown_fence_fallback"
    return response.strip() + "\n", "full_response_fallback"


__all__ = ["extract_rtl_candidate"]

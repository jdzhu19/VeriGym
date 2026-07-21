"""Conservative SystemVerilog declaration parsing and reference transformation."""

from __future__ import annotations

import re

from verigym.core.errors import ConfigurationError

_MODULE_DECLARATION = re.compile(
    r"\bmodule\s+(?:(?:automatic|static)\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_$]*)\b"
)


def mask_comments_and_strings(source: str) -> str:
    """Mask comments and strings with spaces while retaining offsets and newlines."""

    output = list(source)
    index = 0
    state = "code"
    while index < len(source):
        current = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            if current == "/" and following == "/":
                output[index] = output[index + 1] = " "
                index += 2
                state = "line_comment"
                continue
            if current == "/" and following == "*":
                output[index] = output[index + 1] = " "
                index += 2
                state = "block_comment"
                continue
            if current == '"':
                output[index] = " "
                index += 1
                state = "string"
                continue
        elif state == "line_comment":
            if current == "\n":
                state = "code"
            else:
                output[index] = " "
            index += 1
            continue
        elif state == "block_comment":
            if current == "*" and following == "/":
                output[index] = output[index + 1] = " "
                index += 2
                state = "code"
                continue
            if current != "\n":
                output[index] = " "
            index += 1
            continue
        elif state == "string":
            if current == "\\" and following:
                output[index] = " "
                if following != "\n":
                    output[index + 1] = " "
                index += 2
                continue
            if current == '"':
                output[index] = " "
                state = "code"
            elif current != "\n":
                output[index] = " "
            index += 1
            continue
        index += 1
    return "".join(output)


def declared_modules(source: str) -> list[str]:
    masked = mask_comments_and_strings(source)
    return [match.group("name") for match in _MODULE_DECLARATION.finditer(masked)]


def transform_reference_candidate(source: str) -> str:
    """Rename exactly one RefModule declaration without replacing other occurrences."""

    masked = mask_comments_and_strings(source)
    matches = [
        match
        for match in _MODULE_DECLARATION.finditer(masked)
        if match.group("name") == "RefModule"
    ]
    if len(matches) != 1:
        raise ConfigurationError(
            "reference transform requires exactly one top-level RefModule declaration"
        )
    match = matches[0]
    start, end = match.span("name")
    transformed = source[:start] + "TopModule" + source[end:]
    if declared_modules(transformed).count("TopModule") != 1:
        raise ConfigurationError("reference transform produced an ambiguous TopModule")
    return transformed


__all__ = ["declared_modules", "mask_comments_and_strings", "transform_reference_candidate"]

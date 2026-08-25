"""Frozen HWE collection, observation, and native-shell tool profiles."""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any, Literal

from verigym.core.hashing import content_hash

HWE_COLLECTION_PROFILE_ID = "hwe_standard_v1"
HWE_OBSERVATION_POLICY_ID = "hwe_repository_observation_v1"
HWE_TOOL_CONTRACT_ID = "hwe_native_shell_v1"
HWE_COLLECTION_PROFILE_V2_ID = "hwe_standard_v2"
HWE_OBSERVATION_POLICY_V2_ID = "hwe_repository_observation_v2"
HWE_TOOL_CONTRACT_V2_ID = "hwe_native_shell_v2"
HWE_CURRENT_COLLECTION_PROFILE_ID = HWE_COLLECTION_PROFILE_V2_ID
HWE_TOKENIZER_ID = "tiktoken-0.7.0/o200k_base"

_ENV_ASSIGNMENT_WORD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_LOCAL_EXIT_STATUS_CAPTURE = re.compile(
    r"(?:^|[;\n]|&&|\|\|)[ \t]*(?P<name>[a-z][a-z0-9_]*)=\$\?"
    r"(?=[ \t]*(?:;|\n|&&|\|\||$))"
)
_HEREDOC_DECLARATION = re.compile(
    r"(?<!<)<<(?P<strip>-?)[ \t]*(?P<quote>['\"]?)(?P<delimiter>[A-Za-z_]"
    r"[A-Za-z0-9_]*)(?P=quote)(?![A-Za-z0-9_])"
)
_ENV_NAME_START = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_")
_ENV_NAME_CONTINUE = _ENV_NAME_START | frozenset("0123456789")
_SAFE_V2_ENV_EXPANSIONS = ("PWD", "RISCV", "VERILATOR_ROOT")


class HweShellCommandPolicyError(ValueError):
    """A stable, non-secret reason for rejecting one HWE shell command."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class HweCollectionProfile:
    """Complete production limits for the first CVA6 native-shell collector."""

    profile_id: str = HWE_COLLECTION_PROFILE_ID
    observation_policy_id: str = HWE_OBSERVATION_POLICY_ID
    tool_contract_id: str = HWE_TOOL_CONTRACT_ID
    tokenizer_id: str = HWE_TOKENIZER_ID
    decision_steps_soft: int = 80
    decision_steps_hard: int = 200
    mutation_actions_soft: int = 16
    mutation_actions_hard: int = 32
    raw_command_bytes: int = 32 * 1024 * 1024
    raw_episode_bytes: int = 256 * 1024 * 1024
    primary_token_limit: int = 32 * 1024
    long_context_token_limit: int = 64 * 1024
    enable_long_context_bucket: bool = False
    memory_bytes: int = 16 * 1024**3
    cpus: float = 4.0
    pids_limit: int = 4096
    episode_wall_time_s: int = 3600
    ordinary_command_timeout_s: int = 60
    compile_command_timeout_s: int = 600
    simulation_command_timeout_s: int = 900

    def __post_init__(self) -> None:
        identities = {
            HWE_COLLECTION_PROFILE_ID: (
                HWE_OBSERVATION_POLICY_ID,
                HWE_TOOL_CONTRACT_ID,
            ),
            HWE_COLLECTION_PROFILE_V2_ID: (
                HWE_OBSERVATION_POLICY_V2_ID,
                HWE_TOOL_CONTRACT_V2_ID,
            ),
        }
        expected = identities.get(self.profile_id)
        if (
            expected is None
            or (
                self.observation_policy_id,
                self.tool_contract_id,
            )
            != expected
        ):
            raise ValueError("HWE collection profile identities are inconsistent")
        canonical = HweCollectionProfile._canonical_identity(self.profile_id, *expected)
        if asdict(self) != canonical:
            raise ValueError(f"{self.profile_id} has fixed production limits")

    @classmethod
    def _canonical_identity(
        cls,
        profile_id: str,
        observation_policy_id: str,
        tool_contract_id: str,
    ) -> dict[str, Any]:
        value = {name: field.default for name, field in cls.__dataclass_fields__.items()}
        value.update(
            {
                "profile_id": profile_id,
                "observation_policy_id": observation_policy_id,
                "tool_contract_id": tool_contract_id,
            }
        )
        return value

    def identity(self) -> dict[str, Any]:
        return asdict(self)


HWE_STANDARD_V1 = HweCollectionProfile()
HWE_STANDARD_V2 = HweCollectionProfile(
    profile_id=HWE_COLLECTION_PROFILE_V2_ID,
    observation_policy_id=HWE_OBSERVATION_POLICY_V2_ID,
    tool_contract_id=HWE_TOOL_CONTRACT_V2_ID,
)


def resolve_hwe_collection_profile(value: object) -> HweCollectionProfile:
    """Resolve only the frozen profile; ad-hoc limits are intentionally unsupported."""

    if value == HWE_COLLECTION_PROFILE_ID:
        return HWE_STANDARD_V1
    if value == HWE_COLLECTION_PROFILE_V2_ID:
        return HWE_STANDARD_V2
    raise ValueError(f"unsupported HWE collection profile: {value!r}")


def hwe_tool_definitions(
    *,
    dialect: Literal["openai", "mcp"] = "openai",
    profile_id: str = HWE_COLLECTION_PROFILE_ID,
) -> list[dict[str, Any]]:
    """Return the isolated six-tool HWE contract without touching the strict registry."""

    profile = resolve_hwe_collection_profile(profile_id)
    shell_description = (
        "Run one bounded shell command with container-native read access; only workspace "
        "changes become the candidate."
        if profile.profile_id == HWE_COLLECTION_PROFILE_V2_ID
        else "Run one bounded shell command in the visible workspace."
    )

    schemas: list[tuple[str, str, dict[str, Any]]] = [
        (
            "list_files",
            "List a bounded, shallow workspace-relative tree.",
            _object_schema({"path": {"type": "string", "default": "."}}),
        ),
        (
            "read_file",
            "Read a bounded workspace-relative file or line range.",
            _object_schema(
                {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                },
                required=["path"],
            ),
        ),
        (
            "apply_patch",
            "Apply one workspace-relative unified diff.",
            _object_schema({"patch": {"type": "string"}}, required=["patch"]),
        ),
        (
            "shell",
            shell_description,
            _object_schema(
                {
                    "command": {"type": "string"},
                    "cwd": {"type": "string"},
                },
                required=["command"],
            ),
        ),
        (
            "inspect_diff",
            "Inspect the bounded candidate diff.",
            _object_schema({}),
        ),
        (
            "finish",
            "Finish after validation and diff inspection.",
            _object_schema({"summary": {"type": "string"}}, required=["summary"]),
        ),
    ]
    if dialect == "mcp":
        return [
            {"name": name, "description": description, "inputSchema": schema}
            for name, description, schema in schemas
        ]
    if dialect != "openai":
        raise ValueError(f"unsupported HWE tool dialect: {dialect}")
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": schema,
            },
        }
        for name, description, schema in schemas
    ]


def hwe_tool_contract_hash(*, profile_id: str = HWE_COLLECTION_PROFILE_ID) -> str:
    profile = resolve_hwe_collection_profile(profile_id)
    return content_hash(
        {
            "tool_contract_id": profile.tool_contract_id,
            "protocol": "repository_action.v2",
            "tools": hwe_tool_definitions(profile_id=profile_id),
        }
    )


def canonical_hwe_action_json(
    name: str,
    arguments: Mapping[str, Any],
    *,
    profile_id: str = HWE_COLLECTION_PROFILE_ID,
) -> str:
    """Validate and serialize one HWE action in the repository_action.v2 envelope."""

    validated = validate_hwe_action(name, arguments, profile_id=profile_id)
    return json.dumps(
        {"protocol": "repository_action.v2", "action": name, "arguments": validated},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def validate_hwe_action(
    name: str,
    arguments: Mapping[str, Any],
    *,
    profile_id: str = HWE_COLLECTION_PROFILE_ID,
) -> dict[str, Any]:
    resolve_hwe_collection_profile(profile_id)
    if name not in {"list_files", "read_file", "apply_patch", "shell", "inspect_diff", "finish"}:
        raise ValueError("unknown HWE native-shell action")
    if not isinstance(arguments, Mapping) or any(not isinstance(key, str) for key in arguments):
        raise ValueError("HWE action arguments must be an object")
    allowed = {
        "list_files": {"path"},
        "read_file": {"path", "start_line", "end_line"},
        "apply_patch": {"patch"},
        "shell": {"command", "cwd"},
        "inspect_diff": set(),
        "finish": {"summary"},
    }[name]
    if set(arguments) - allowed:
        raise ValueError("HWE action contains unsupported arguments")
    result = dict(arguments)
    if name == "list_files":
        result.setdefault("path", ".")
        result["path"] = validate_workspace_relative_path(result["path"], allow_dot=True)
    elif name == "read_file":
        result["path"] = validate_workspace_relative_path(_required_string(result, "path"))
        for key in ("start_line", "end_line"):
            value = result.get(key)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise ValueError(f"{key} must be a positive integer")
        if result.get("start_line") and result.get("end_line"):
            if result["start_line"] > result["end_line"]:
                raise ValueError("read_file line range is reversed")
    elif name == "apply_patch":
        patch = _required_string(result, "patch")
        if len(patch.encode("utf-8")) > 4 * 1024 * 1024:
            raise ValueError("HWE patch exceeds its bound")
        for line in patch.splitlines():
            if line.startswith(("--- ", "+++ ")):
                path = line[4:].split("\t", 1)[0]
                if path != "/dev/null":
                    validate_workspace_relative_path(path.removeprefix("a/").removeprefix("b/"))
    elif name == "shell":
        result["command"] = validate_shell_command(
            _required_string(result, "command"), profile_id=profile_id
        )
        if "cwd" in result:
            result["cwd"] = validate_workspace_relative_path(result["cwd"], allow_dot=True)
    elif name == "finish":
        summary = _required_string(result, "summary")
        if len(summary.encode("utf-8")) > 16 * 1024:
            raise ValueError("finish summary exceeds its bound")
    return result


def validate_workspace_relative_path(value: object, *, allow_dot: bool = False) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise ValueError("workspace path must be non-empty canonical text")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or any(part in {"", ".."} for part in candidate.parts):
        raise ValueError("workspace path must be relative and cannot escape through '..'")
    normalized = candidate.as_posix()
    if normalized == "." and not allow_dot:
        raise ValueError("workspace path must identify a file")
    return normalized


def validate_shell_command(value: str, *, profile_id: str = HWE_COLLECTION_PROFILE_ID) -> str:
    profile = resolve_hwe_collection_profile(profile_id)
    if (
        not value
        or value != value.strip()
        or "\x00" in value
        or len(value.encode("utf-8")) > 64 * 1024
    ):
        raise HweShellCommandPolicyError(
            "noncanonical_or_oversized",
            "shell command is empty, non-canonical, or oversized",
        )
    projected_value = value
    heredoc_expansion = False
    v2_heredoc = False
    if profile.profile_id == HWE_COLLECTION_PROFILE_V2_ID:
        projected_value, heredoc_expansion, v2_heredoc = _mask_v2_heredoc_bodies(value)
        projected_value = _mask_v2_local_exit_status(projected_value)
        projected_value = _mask_v2_local_loop_variables(projected_value)
        projected_value = _mask_v2_safe_environment_expansions(projected_value)
    projection, active_expansion = _shell_unquoted_projection(projected_value)
    if _has_environment_assignment(projection):
        raise HweShellCommandPolicyError(
            "environment_assignment",
            "shell environment assignment is forbidden",
        )
    if active_expansion or heredoc_expansion:
        raise HweShellCommandPolicyError(
            "environment_expansion",
            "shell environment expansion is forbidden",
        )
    try:
        words = shlex.split(value, posix=True)
    except ValueError as exc:
        if v2_heredoc:
            words = []
        else:
            raise HweShellCommandPolicyError(
                "tokenization",
                "shell command cannot be safely tokenized",
            ) from exc
    if not words and not v2_heredoc:
        raise HweShellCommandPolicyError("empty", "shell command is empty")
    if profile.profile_id == HWE_COLLECTION_PROFILE_ID:
        for word in words:
            stripped = word.lstrip("<>")
            if stripped.startswith("/"):
                raise HweShellCommandPolicyError(
                    "absolute_path",
                    "shell command contains an absolute path",
                )
            if ".." in PurePosixPath(stripped).parts:
                raise HweShellCommandPolicyError(
                    "parent_path",
                    "shell command contains an escaping path",
                )
    return value


def _mask_v2_local_exit_status(value: str) -> str:
    """Mask bounded shell-local exit-status bookkeeping without allowing env injection."""

    projection, _active = _shell_unquoted_projection(value)
    captures = list(_LOCAL_EXIT_STATUS_CAPTURE.finditer(projection))
    if not captures:
        return value
    masked = list(value)
    first_capture_by_name: dict[str, int] = {}
    for capture in captures:
        name = capture.group("name")
        start = capture.start("name")
        end = capture.end()
        first_capture_by_name.setdefault(name, start)
        for index in range(start, end):
            masked[index] = "x"
    for name, capture_start in first_capture_by_name.items():
        reference = re.compile(rf"\$(?:\{{{re.escape(name)}\}}|{re.escape(name)}(?![A-Za-z0-9_]))")
        for match in reference.finditer(value, capture_start):
            for index in range(match.start(), match.end()):
                masked[index] = "x"
    return "".join(masked)


def _mask_v2_safe_environment_expansions(value: str) -> str:
    """Mask reads of frozen, non-secret HWE toolchain environment variables."""

    masked = list(value)
    names = "|".join(re.escape(name) for name in _SAFE_V2_ENV_EXPANSIONS)
    reference = re.compile(rf"\$(?:\{{(?:{names})\}}|(?:{names})(?![A-Za-z0-9_]))")
    for match in reference.finditer(value):
        for index in range(match.start(), match.end()):
            masked[index] = "x"
    return "".join(masked)


def _mask_v2_local_loop_variables(value: str) -> str:
    """Mask references to lowercase variables declared by a bounded shell ``for`` loop."""

    projection, _active = _shell_unquoted_projection(value)
    declaration = re.compile(
        r"(?:^|[;\n]|&&|\|\|)[ \t]*for[ \t]+(?P<name>[a-z][a-z0-9_]*)[ \t]+in\b"
    )
    masked = list(value)
    first_declaration: dict[str, int] = {}
    for match in declaration.finditer(projection):
        first_declaration.setdefault(match.group("name"), match.end())
    for name, declaration_end in first_declaration.items():
        reference = re.compile(rf"\$(?:\{{{re.escape(name)}\}}|{re.escape(name)}(?![A-Za-z0-9_]))")
        for match in reference.finditer(value, declaration_end):
            for index in range(match.start(), match.end()):
                masked[index] = "x"
    return "".join(masked)


def _has_environment_assignment(projection: str) -> bool:
    """Detect shell assignment words without confusing ordinary ``name=value`` arguments."""

    lexer = shlex.shlex(
        projection.replace("\n", " ; "),
        posix=True,
        punctuation_chars=";&|()",
    )
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        words = list(lexer)
    except ValueError:
        return True
    command_started = False
    environment_mutator = False
    boundaries = {"if", "then", "elif", "else", "while", "until", "do", "!", "time", "{"}
    mutators = {"env", "export", "declare", "typeset", "local"}
    for word in words:
        if word and all(character in ";&|()" for character in word):
            command_started = False
            environment_mutator = False
            continue
        if word in boundaries:
            command_started = False
            environment_mutator = False
            continue
        if not command_started:
            if _ENV_ASSIGNMENT_WORD.match(word):
                return True
            command_started = True
            environment_mutator = PurePosixPath(word).name in mutators
            continue
        if environment_mutator and _ENV_ASSIGNMENT_WORD.match(word):
            return True
    return False


def _mask_v2_heredoc_bodies(value: str) -> tuple[str, bool, bool]:
    """Mask heredoc data while retaining expansion checks for unquoted delimiters."""

    projection, _active = _shell_unquoted_projection(value)
    original_lines = value.splitlines(keepends=True)
    masked = list(value)
    offsets: list[int] = []
    offset = 0
    for line in original_lines:
        offsets.append(offset)
        offset += len(line)
    declarations: list[tuple[str, bool, bool]] = []
    body_expansion = False
    heredoc_seen = False
    line_index = 0
    while line_index < len(original_lines):
        original_line = original_lines[line_index]
        line_offset = offsets[line_index]
        projected_line = projection[line_offset : line_offset + len(original_line)]
        for match in _HEREDOC_DECLARATION.finditer(original_line):
            if projected_line[match.start() : match.start() + 2] != "<<":
                continue
            declarations.append(
                (
                    match.group("delimiter"),
                    bool(match.group("quote")),
                    match.group("strip") == "-",
                )
            )
            heredoc_seen = True
        line_index += 1
        while declarations and line_index < len(original_lines):
            delimiter, quoted, strip_tabs = declarations.pop(0)
            found = False
            while line_index < len(original_lines):
                body_line = original_lines[line_index]
                comparison = body_line.rstrip("\r\n")
                if strip_tabs:
                    comparison = comparison.lstrip("\t")
                if comparison == delimiter:
                    found = True
                    line_index += 1
                    break
                if not quoted and any(
                    character == "$" and _named_expansion_at(body_line, index)
                    for index, character in enumerate(body_line)
                ):
                    body_expansion = True
                start = offsets[line_index]
                for index, character in enumerate(body_line):
                    if character not in "\r\n":
                        masked[start + index] = "x"
                line_index += 1
            if not found:
                break
    return "".join(masked), body_expansion, heredoc_seen


def _shell_unquoted_projection(value: str) -> tuple[str, bool]:
    """Mask quoted literals while detecting only shell-active named expansions."""

    output: list[str] = []
    quote: str | None = None
    escaped = False
    active_expansion = False
    index = 0
    while index < len(value):
        character = value[index]
        if escaped:
            output.append("x")
            escaped = False
            index += 1
            continue
        if character == "\\" and quote != "'":
            output.append("x")
            escaped = True
            index += 1
            continue
        if character == "'" and quote != '"':
            quote = None if quote == "'" else "'"
            output.append("x")
            index += 1
            continue
        if character == '"' and quote != "'":
            quote = None if quote == '"' else '"'
            output.append("x")
            index += 1
            continue
        if quote is not None:
            if character == "$" and quote == '"' and _named_expansion_at(value, index):
                active_expansion = True
            output.append("x")
            index += 1
            continue
        if character == "$" and _named_expansion_at(value, index):
            active_expansion = True
        output.append(character)
        index += 1
    return "".join(output), active_expansion


def _named_expansion_at(value: str, index: int) -> bool:
    following = index + 1
    if following >= len(value):
        return False
    if value[following] == "{":
        name = following + 1
        if name >= len(value) or value[name] not in _ENV_NAME_START:
            return False
        cursor = name + 1
        while cursor < len(value) and value[cursor] in _ENV_NAME_CONTINUE:
            cursor += 1
        return cursor < len(value) and value[cursor] == "}"
    return value[following] in _ENV_NAME_START


def command_timeout_seconds(command: str, *, profile_id: str = HWE_COLLECTION_PROFILE_ID) -> int:
    profile = resolve_hwe_collection_profile(profile_id)
    lowered = command.casefold()
    if any(word in lowered for word in ("simulate", "simulation", "regress", "spike", "vcs")):
        return profile.simulation_command_timeout_s
    if any(
        word in lowered
        for word in ("make", "verilator", "iverilog", "sbt", "mill", "compile", "elaborat")
    ):
        return profile.compile_command_timeout_s
    return profile.ordinary_command_timeout_s


def _required_string(arguments: Mapping[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"HWE action requires non-empty {key}")
    return value


def _object_schema(
    properties: dict[str, Any], *, required: list[str] | None = None
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        value["required"] = required
    return value


__all__ = [
    "HWE_COLLECTION_PROFILE_ID",
    "HWE_COLLECTION_PROFILE_V2_ID",
    "HWE_CURRENT_COLLECTION_PROFILE_ID",
    "HWE_OBSERVATION_POLICY_ID",
    "HWE_OBSERVATION_POLICY_V2_ID",
    "HWE_STANDARD_V1",
    "HWE_STANDARD_V2",
    "HWE_TOKENIZER_ID",
    "HWE_TOOL_CONTRACT_ID",
    "HWE_TOOL_CONTRACT_V2_ID",
    "HweCollectionProfile",
    "canonical_hwe_action_json",
    "command_timeout_seconds",
    "hwe_tool_contract_hash",
    "hwe_tool_definitions",
    "resolve_hwe_collection_profile",
    "validate_hwe_action",
    "validate_shell_command",
    "validate_workspace_relative_path",
]

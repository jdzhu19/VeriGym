"""Context-aware, privacy-preserving security scanning for persisted artifacts."""

from __future__ import annotations

import csv
import json
import math
import os
import re
import stat
import tomllib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast
from urllib.parse import parse_qsl, urlsplit

import yaml

from verigym.core.hashing import content_hash
from verigym.schemas.security_scan import (
    ArtifactContentClass,
    ArtifactParser,
    ArtifactSecurityScan,
    SecurityFinding,
    SecurityScanPolicy,
    SecurityScanReport,
    StructuredFieldRole,
)

_STRUCTURED_EXTENSIONS = (".json", ".jsonl", ".yaml", ".yml", ".toml", ".csv")
_TEXT_EXTENSIONS = (
    ".md",
    ".txt",
    ".rst",
    ".log",
    ".patch",
    ".diff",
    ".sv",
    ".v",
    ".py",
    ".sh",
    ".ini",
    ".cfg",
)
_SECURITY_VOCABULARY = re.compile(
    r"(?i)(?:auth(?:entication|orization)?|bearer|cookie|credential|key|password|"
    r"controller|private.reasoning|proxy|secret|session|token|validation)"
)
_SENSITIVE_KEY = re.compile(
    r"(?i)(?:^|[_-])(?:access[_-]?token|api[_-]?key|authorization|bearer|cookie|"
    r"credential|identity[_-]?token|password|private[_-]?key|refresh[_-]?token|"
    r"secret|session(?:[_-]?id|[_-]?key|[_-]?token)?)(?:$|[_-])"
)
_HASH_KEY = re.compile(
    r"(?i)(?:hash|sha(?:1|224|256|384|512)?|digest|fingerprint|checksum|commit|tree)"
)
_IDENTITY_KEY = re.compile(
    r"(?i)(?:^|[_-])(?:id|mode|class|kind|type|status|role|policy|name|version)(?:$|[_-])"
)
_ENVIRONMENT_VARIABLE_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")
_ENVIRONMENT_NAME_KEY = re.compile(
    r"(?i)(?:^|[_-])(?:(?:env|environment)(?:[_-](?:var(?:iable)?[_-])?name)?|"
    r"credential[_-](?:source|env(?:ironment)?(?:[_-](?:var(?:iable)?[_-])?name)?))"
    r"(?:s)?$"
)
_AUTHENTICATION_MODE_KEY = re.compile(
    r"(?i)(?:^|[_-])(?:auth(?:entication)?)(?:[_-](?:semantic[_-]?id|mode))$"
)
_AUTHORIZATION_AUDIT_METADATA_KEY = re.compile(r"(?i)^authorization[_-](?:basis|scope)$")
_EXECUTION_BOUNDARY_KEY = re.compile(
    r"(?i)(?:execution[_-]?boundary|credential[_-]?bearing[_-]?http[_-]?location|"
    r"controller[_-]?(?:role|location|boundary)|trust[_-]?boundary|process[_-]?boundary)"
)
_BASE_URL_KEY = re.compile(
    r"(?i)(?:^|[_-])(?:normalized[_-])?(?:base[_-]?url|endpoint[_-]?origin|"
    r"provider[_-]?url|proxy[_-]?(?:url|uri))(?:$|[_-])"
)
_BOOLEAN_POLICY_KEY = re.compile(
    r"(?i)(?:^|[_-])(?:allowed|available|enabled|exposed|exported|forwarded|hashed|"
    r"included|modified|persisted|present|redacted|required|resolved|verified)(?:$|[_-])"
)
_PATH_KEY = re.compile(r"(?i)(?:^|[_-])(?:path|file|directory|root|uri)(?:$|[_-])")
_DOCUMENTATION_KEY = re.compile(
    r"(?i)(?:description|documentation|example|explanation|help|message|note|rationale|"
    r"reason|required_interpretation|summary|text|title|vocabulary)"
)
_UNKNOWN_SENSITIVE_KEY = re.compile(
    r"(?i)^(?:(?:opaque|unclassified|unknown)[_-](?:sensitive[_-])?"
    r"(?:blob|material|value)|sensitive[_-](?:blob|material|value))$"
)
_IDENTITY_VALUE = re.compile(
    r"^(?:[0-9a-f]{32}|[0-9a-f]{40}|[0-9a-f]{64}|sha256:[0-9a-f]{64}|"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$",
    re.IGNORECASE,
)
_PRIVATE_KEY = re.compile(
    rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
    re.IGNORECASE,
)
_BEARER = re.compile(rb"(?i)\bAuthorization\s*:\s*Bearer\s+([A-Za-z0-9._~+/=-]{1,4096})")
_BARE_BEARER = re.compile(rb"(?i)^Bearer\s+([A-Za-z0-9._~+/=-]{1,4096})$")
_PROVIDER_TOKEN = re.compile(
    rb"(?<![A-Za-z0-9_-])(?:"
    rb"sk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,}|"
    rb"AKIA[0-9A-Z]{16}|"
    rb"gh[opusr]_[A-Za-z0-9]{30,}|"
    rb"hf_[A-Za-z0-9]{24,}|"
    rb"xox[baprs]-[A-Za-z0-9-]{24,}"
    rb")(?![A-Za-z0-9_-])"
)
_PROVIDER_STYLE_IDENTIFIER = re.compile(rb"sk-(?:[a-z][a-z0-9]{2,}-){1,}[a-z][a-z0-9]{2,}$")
_URL = re.compile(rb"(?i)\b[a-z][a-z0-9+.-]{1,20}://[^\s<>\"']{1,8192}")
_ASSIGNMENT = re.compile(
    rb"(?im)^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]{1,127})[ \t]*=[ \t]*"
    rb"(?:'([^'\r\n]{1,4096})'|\"([^\"\r\n]{1,4096})\"|([^\s#;`]{1,4096}))[ \t]*"
    rb"(?:[#;].*)?$"
)
_PLACEHOLDERS = {
    "<redacted>",
    "example-token",
    "redacted",
    "test_only_not_a_secret",
}
_MAX_DIAGNOSTICS_PER_ARTIFACT = 25


class SecurityScanFailure(ValueError):
    """A redacted fail-closed signal for a non-passing security scan."""

    def __init__(self, report: SecurityScanReport) -> None:
        categories = sorted({item.evidence_category for item in report.findings})
        paths = sorted({item.relative_path for item in report.findings})
        super().__init__(
            "artifact security scan failed "
            f"(hard={report.hard_secret_leak_count}, errors={report.scanner_error_count}, "
            f"categories={','.join(categories)}, paths={','.join(paths)})"
        )
        self.report = report


@dataclass(frozen=True)
class _Node:
    path: str
    key: str | None
    value: Any
    role: StructuredFieldRole


def build_security_scan_policy() -> SecurityScanPolicy:
    """Return the fixed context-aware scanning policy and its deterministic identity."""

    base = {
        "schema_version": "1.0",
        "policy_id": "context_aware_structured_artifact_secret_scan_v2",
        "max_files": 100_000,
        "max_file_bytes": 256 * 1024 * 1024,
        "max_total_bytes": 2 * 1024 * 1024 * 1024,
        "provider_token_min_length": 24,
        "unknown_sensitive_min_length": 24,
        "unknown_sensitive_min_entropy_bits_per_character": 3.5,
        "structured_extensions": _STRUCTURED_EXTENSIONS,
        "placeholder_policy": "fixture_provenance_only",
        "private_value_reporting": "length_only_never_hash",
        "proxy_value_reporting": "presence_only_never_hash",
        "malformed_structured_policy": "fail_closed",
        "unknown_finding_policy": "fail_closed",
    }
    return SecurityScanPolicy.model_validate({**base, "policy_hash": content_hash(base)})


def validate_security_scan_policy(policy: SecurityScanPolicy) -> SecurityScanPolicy:
    payload = policy.model_dump(mode="json")
    observed = payload.pop("policy_hash")
    if content_hash(payload) != observed:
        raise ValueError("security scan policy identity changed")
    return policy


def _artifact_class(relative: str) -> ArtifactContentClass:
    lowered = relative.casefold()
    name = PurePosixPath(relative).name.casefold()
    if "allowed-synthesis-corpus" in name:
        return "allowed_synthesis_corpus"
    if "trajectory" in lowered or name in {"rewards.jsonl", "index.jsonl", "statistics.json"}:
        return "trajectory_dataset"
    if "memory-pack" in name or "memory_pack" in name:
        return "memory_pack"
    if name.endswith(".schema.json") or "/schemas/" in f"/{lowered}" or "contract" in name:
        return "schema_or_contract"
    if name.endswith((".md", ".rst")) or "/docs/" in f"/{lowered}":
        return "documentation"
    if name.endswith((".whl", ".tar.gz", ".zip", ".so", ".a", ".o")):
        return "binary_build_artifact"
    if any(
        part in {"runs", "artifacts", "reports", "replay"} for part in PurePosixPath(lowered).parts
    ):
        return "runtime_artifact"
    return "unknown"


def _parser_for(path: Path, data: bytes) -> ArtifactParser:
    name = path.name.casefold()
    suffix = path.suffix.casefold()
    if suffix == ".json":
        return "json"
    if suffix == ".jsonl":
        return "jsonl"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    if suffix == ".toml":
        return "toml"
    if suffix == ".csv":
        return "csv"
    if suffix in {".md", ".rst"}:
        return "markdown"
    if suffix in _TEXT_EXTENSIONS or name in {"license", "notice", "sha256sums"}:
        return "text"
    if b"\0" in data[:8192]:
        return "binary"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return "binary"
    return "text"


def _parse_structured(parser: ArtifactParser, data: bytes) -> Any:
    text = data.decode("utf-8")
    if parser == "json":
        return json.loads(text)
    if parser == "jsonl":
        values = []
        for index, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                values.append(json.loads(line))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ValueError(f"malformed JSONL record at line class {index}") from exc
        return values
    if parser == "yaml":
        return list(yaml.safe_load_all(text))
    if parser == "toml":
        return tomllib.loads(text)
    if parser == "csv":
        return list(csv.DictReader(text.splitlines()))
    raise ValueError("parser is not structured")


def _looks_like_identity(key: str | None, value: str) -> bool:
    if not _IDENTITY_VALUE.fullmatch(value):
        return False
    return key is None or bool(_HASH_KEY.search(key) or _IDENTITY_KEY.search(key))


def _boolean_or_null_string_role(key: str | None, value: Any) -> StructuredFieldRole | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    normalized_key = (key or "").casefold()
    policy_context = bool(
        _BOOLEAN_POLICY_KEY.search(normalized_key) or _SENSITIVE_KEY.search(normalized_key)
    )
    if not policy_context:
        return None
    if normalized in {"true", "false"}:
        return "boolean_policy"
    if normalized in {"null", "none"}:
        return "null_policy"
    return None


def classify_structured_field_role(
    *,
    key: str | None,
    value: Any,
    content_class: ArtifactContentClass,
    field_path: str,
) -> StructuredFieldRole:
    """Resolve a leaf's semantic role without inspecting external state or secret values."""

    if value is None:
        return "null_policy"
    if isinstance(value, bool):
        return "boolean_policy"
    normalized_key = (key or "").casefold()
    string_policy_role = _boolean_or_null_string_role(key, value)
    if string_policy_role is not None:
        return string_policy_role
    if isinstance(value, str) and _looks_like_identity(key, value):
        return "known_hash_or_digest"
    if key and _ENVIRONMENT_VARIABLE_NAME.fullmatch(key) and _SENSITIVE_KEY.search(key):
        return "credential_value_candidate"
    if (
        key
        and isinstance(value, str)
        and _ENVIRONMENT_NAME_KEY.search(normalized_key)
        and _ENVIRONMENT_VARIABLE_NAME.fullmatch(value.strip())
    ):
        return "environment_variable_name"
    if key and _AUTHENTICATION_MODE_KEY.search(normalized_key):
        return "authentication_mode"
    if key and _AUTHORIZATION_AUDIT_METADATA_KEY.fullmatch(normalized_key):
        return "documentation_text"
    if key and _EXECUTION_BOUNDARY_KEY.search(normalized_key):
        return "execution_boundary_enum"
    if key and _BASE_URL_KEY.search(normalized_key):
        return "normalized_base_url"
    if key and (
        "semantic_id" in normalized_key
        or normalized_key.endswith("_state")
        or (normalized_key.endswith("_id") and normalized_key not in {"cookie_id", "session_id"})
    ):
        return "known_identifier"
    if key and _SENSITIVE_KEY.search(normalized_key):
        return "credential_value_candidate"
    if key and _UNKNOWN_SENSITIVE_KEY.search(normalized_key):
        return "unknown_value"
    if content_class == "allowed_synthesis_corpus" and (
        ".normalized_tokens[" in field_path
        or normalized_key in {"source_class", "source_id", "policy_id", "corpus_id"}
    ):
        return "known_identifier"
    if key and _PATH_KEY.search(normalized_key):
        return "known_path_identity"
    if key and _DOCUMENTATION_KEY.search(normalized_key):
        return "documentation_text"
    if key and _IDENTITY_KEY.search(normalized_key):
        return "known_identifier"
    if content_class in {"documentation", "schema_or_contract"}:
        return "documentation_text"
    if isinstance(value, (str, int, float)):
        return "runtime_value"
    return "unknown_value"


def _walk_structured(
    value: Any,
    *,
    content_class: ArtifactContentClass,
    path: str = "$",
    key: str | None = None,
) -> Iterator[_Node]:
    if isinstance(value, Mapping):
        for item_key, item in value.items():
            normalized = str(item_key)
            item_path = f"{path}.{normalized}"
            yield _Node(item_path, normalized, item, "field_name")
            yield from _walk_structured(
                item,
                content_class=content_class,
                path=item_path,
                key=normalized,
            )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_structured(
                item,
                content_class=content_class,
                path=f"{path}[{index}]",
                key=key,
            )
        return
    yield _Node(
        path,
        key,
        value,
        classify_structured_field_role(
            key=key,
            value=value,
            content_class=content_class,
            field_path=path,
        ),
    )


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for character in value:
        counts[character] = counts.get(character, 0) + 1
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _fixture_placeholder(value: str, fixture: bool) -> bool:
    return fixture and value.strip().casefold() in _PLACEHOLDERS


def _finding(
    *,
    relative: str,
    content_class: ArtifactContentClass,
    field_path: str | None,
    role: StructuredFieldRole,
    category: str,
    severity: str,
    value: bytes | None,
    rationale: str,
) -> SecurityFinding:
    return SecurityFinding(
        relative_path=relative,
        artifact_content_class=content_class,
        structured_field_path=field_path,
        field_role=role,
        evidence_category=cast(Any, category),
        severity=cast(Any, severity),
        value_length=len(value) if value is not None else None,
        evidence_sha256=None,
        rationale_code=rationale,
    )


def _explicit_secret_findings(
    data: bytes,
    *,
    relative: str,
    content_class: ArtifactContentClass,
    field_path: str | None,
    role: StructuredFieldRole,
    fixture: bool,
) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    if _PRIVATE_KEY.search(data):
        findings.append(
            _finding(
                relative=relative,
                content_class=content_class,
                field_path=field_path,
                role=role,
                category="private_key",
                severity="hard_secret_leak",
                value=data,
                rationale="private_key_block_present",
            )
        )
        return findings
    for match in _BEARER.finditer(data):
        candidate = match.group(1)
        if not _fixture_placeholder(candidate.decode("ascii", errors="ignore"), fixture):
            findings.append(
                _finding(
                    relative=relative,
                    content_class=content_class,
                    field_path=field_path,
                    role=role,
                    category="authorization_bearer",
                    severity="hard_secret_leak",
                    value=candidate,
                    rationale="authorization_header_has_value",
                )
            )
    if role == "credential_value_candidate":
        bare_bearer = _BARE_BEARER.fullmatch(data.strip())
        if bare_bearer is not None:
            candidate = bare_bearer.group(1)
            if not _fixture_placeholder(candidate.decode("ascii", errors="ignore"), fixture):
                findings.append(
                    _finding(
                        relative=relative,
                        content_class=content_class,
                        field_path=field_path,
                        role=role,
                        category="authorization_bearer",
                        severity="hard_secret_leak",
                        value=candidate,
                        rationale="structured_authorization_bearer_has_value",
                    )
                )
    for match in _PROVIDER_TOKEN.finditer(data):
        candidate = match.group(0)
        if not _fixture_placeholder(candidate.decode("ascii", errors="ignore"), fixture):
            if (
                _PROVIDER_STYLE_IDENTIFIER.fullmatch(candidate)
                and not candidate.startswith((b"sk-proj-", b"sk-ant-"))
                and role != "credential_value_candidate"
            ):
                findings.append(
                    _finding(
                        relative=relative,
                        content_class=content_class,
                        field_path=field_path,
                        role=role,
                        category="diagnostic_security_metadata",
                        severity="diagnostic_security_metadata",
                        value=None,
                        rationale="provider_prefix_kebab_identifier_without_secret_value",
                    )
                )
                continue
            findings.append(
                _finding(
                    relative=relative,
                    content_class=content_class,
                    field_path=field_path,
                    role=role,
                    category="provider_api_token",
                    severity="hard_secret_leak",
                    value=candidate,
                    rationale="anchored_provider_token_shape",
                )
            )
    for match in _URL.finditer(data):
        candidate = match.group(0).rstrip(b".,);]}")
        decoded = candidate.decode("utf-8", errors="ignore")
        rationale: str | None = None
        try:
            parsed = urlsplit(decoded)
        except ValueError:
            # Compiler diagnostics and other untrusted text can contain URL-shaped fragments with
            # unmatched IPv6 brackets. Keep scanning without treating parser failure as a scanner
            # failure, while conservatively retaining the two credential-bearing URI checks.
            remainder = decoded.split("://", 1)[1]
            authority = re.split(r"[/?#]", remainder, maxsplit=1)[0]
            query = remainder.partition("?")[2].partition("#")[0]
            if "@" in authority:
                rationale = "uri_contains_userinfo_secret"
            else:
                for query_key, query_value in parse_qsl(query, keep_blank_values=True):
                    if _SENSITIVE_KEY.search(query_key) and query_value.strip():
                        rationale = "uri_contains_sensitive_query_value"
                        break
        else:
            if parsed.username is not None or parsed.password is not None:
                rationale = "uri_contains_userinfo_secret"
            else:
                for query_key, query_value in parse_qsl(parsed.query, keep_blank_values=True):
                    if _SENSITIVE_KEY.search(query_key) and query_value.strip():
                        rationale = "uri_contains_sensitive_query_value"
                        break
        if rationale is not None:
            findings.append(
                _finding(
                    relative=relative,
                    content_class=content_class,
                    field_path=field_path,
                    role=role,
                    category="credential_bearing_uri",
                    severity="hard_secret_leak",
                    value=candidate,
                    rationale=rationale,
                )
            )
    for match in _ASSIGNMENT.finditer(data):
        assignment_name = match.group(1).decode("ascii", errors="ignore")
        if not _SENSITIVE_KEY.search(assignment_name):
            continue
        candidate = next(group for group in match.groups()[1:] if group is not None)
        decoded = candidate.decode("utf-8", errors="ignore").strip()
        safe_non_value = decoded.casefold() in {"false", "true", "null", "none"}
        if not safe_non_value and not _fixture_placeholder(decoded, fixture):
            findings.append(
                _finding(
                    relative=relative,
                    content_class=content_class,
                    field_path=field_path,
                    role=role,
                    category="persisted_secret_assignment",
                    severity="hard_secret_leak",
                    value=candidate,
                    rationale="sensitive_environment_assignment_has_value",
                )
            )
    return findings


def _structured_node_findings(
    node: _Node,
    *,
    relative: str,
    content_class: ArtifactContentClass,
    fixture: bool,
    policy: SecurityScanPolicy,
    diagnostics_remaining: int,
) -> list[SecurityFinding]:
    if node.role == "field_name":
        if diagnostics_remaining > 0 and node.key and _SECURITY_VOCABULARY.search(node.key):
            return [
                _finding(
                    relative=relative,
                    content_class=content_class,
                    field_path=node.path,
                    role="field_name",
                    category="diagnostic_security_metadata",
                    severity="diagnostic_security_metadata",
                    value=None,
                    rationale="security_vocabulary_in_field_name",
                )
            ]
        return []
    if not isinstance(node.value, str):
        return []
    encoded = node.value.encode("utf-8")
    explicit = _explicit_secret_findings(
        encoded,
        relative=relative,
        content_class=content_class,
        field_path=node.path,
        role=node.role,
        fixture=fixture,
    )
    if explicit:
        return explicit
    if node.role == "credential_value_candidate":
        stripped = node.value.strip()
        if not stripped or _fixture_placeholder(stripped, fixture):
            return []
        key = (node.key or "").casefold()
        category = (
            "session_or_cookie"
            if any(term in key for term in ("cookie", "session", "refresh", "identity_token"))
            else "persisted_secret_assignment"
        )
        return [
            _finding(
                relative=relative,
                content_class=content_class,
                field_path=node.path,
                role=node.role,
                category=category,
                severity="hard_secret_leak",
                value=encoded,
                rationale="sensitive_structured_field_has_value",
            )
        ]
    if (
        node.role == "unknown_value"
        and len(node.value) >= policy.unknown_sensitive_min_length
        and _entropy(node.value) >= policy.unknown_sensitive_min_entropy_bits_per_character
        and not _looks_like_identity(node.key, node.value)
    ):
        return [
            _finding(
                relative=relative,
                content_class=content_class,
                field_path=node.path,
                role=node.role,
                category="unknown_sensitive_high_entropy",
                severity="hard_secret_leak",
                value=encoded,
                rationale="unknown_value_high_entropy_not_declared_identity",
            )
        ]
    if (
        diagnostics_remaining > 0
        and node.role
        in {
            "environment_variable_name",
            "authentication_mode",
            "execution_boundary_enum",
            "boolean_policy",
            "null_policy",
            "known_hash_or_digest",
            "known_identifier",
            "normalized_base_url",
            "enum_or_identifier",
            "boolean_or_null_policy",
            "known_hash_identity",
            "documentation_text",
        }
        and _SECURITY_VOCABULARY.search(node.value)
    ):
        return [
            _finding(
                relative=relative,
                content_class=content_class,
                field_path=node.path,
                role=node.role,
                category="diagnostic_security_metadata",
                severity="diagnostic_security_metadata",
                value=None,
                rationale="non_value_bearing_security_vocabulary",
            )
        ]
    return []


def _artifact_record(
    *,
    relative: str,
    content_class: ArtifactContentClass,
    parser: ArtifactParser,
    size: int,
    structured: bool,
    fields: int,
    findings: Sequence[SecurityFinding],
) -> ArtifactSecurityScan:
    base = {
        "schema_version": "1.0",
        "relative_path": relative,
        "artifact_content_class": content_class,
        "parser": parser,
        "size_bytes": size,
        "structured": structured,
        "fields_examined": fields,
        "hard_secret_leak_count": sum(item.severity == "hard_secret_leak" for item in findings),
        "diagnostic_security_vocabulary_count": sum(
            item.severity in {"diagnostic_security_metadata", "diagnostic_security_vocabulary"}
            for item in findings
        ),
        "scanner_error_count": sum(item.severity == "scanner_error" for item in findings),
    }
    return ArtifactSecurityScan.model_validate({**base, "scan_hash": content_hash(base)})


def _safe_entries(
    roots: Sequence[Path],
    *,
    policy: SecurityScanPolicy,
) -> tuple[list[tuple[str, Path]], list[SecurityFinding]]:
    entries: list[tuple[str, Path]] = []
    errors: list[SecurityFinding] = []
    total = 0
    for root_index, supplied in enumerate(roots):
        expanded = supplied.expanduser()
        supplied_metadata = os.lstat(expanded)
        if stat.S_ISLNK(supplied_metadata.st_mode) or not stat.S_ISDIR(supplied_metadata.st_mode):
            raise ValueError("security scan root must be an ordinary directory")
        root = expanded.resolve(strict=True)
        prefix = "" if len(roots) == 1 else f"root-{root_index}/"
        for current, directories, names in os.walk(root, followlinks=False):
            current_path = Path(current)
            retained: list[str] = []
            for directory in sorted(directories):
                path = current_path / directory
                metadata = os.lstat(path)
                relative = prefix + path.relative_to(root).as_posix()
                if stat.S_ISLNK(metadata.st_mode):
                    errors.append(
                        _finding(
                            relative=relative,
                            content_class="unknown",
                            field_path=None,
                            role="unknown_value",
                            category="unsafe_filesystem_entry",
                            severity="scanner_error",
                            value=None,
                            rationale="symlink_directory_rejected",
                        )
                    )
                else:
                    retained.append(directory)
            directories[:] = retained
            for name in sorted(names):
                path = current_path / name
                relative = prefix + path.relative_to(root).as_posix()
                metadata = os.lstat(path)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    errors.append(
                        _finding(
                            relative=relative,
                            content_class="unknown",
                            field_path=None,
                            role="unknown_value",
                            category="unsafe_filesystem_entry",
                            severity="scanner_error",
                            value=None,
                            rationale="nonregular_or_hardlinked_file_rejected",
                        )
                    )
                    continue
                if metadata.st_size > policy.max_file_bytes:
                    errors.append(
                        _finding(
                            relative=relative,
                            content_class="unknown",
                            field_path=None,
                            role="unknown_value",
                            category="unsupported_or_oversized_artifact",
                            severity="scanner_error",
                            value=None,
                            rationale="file_size_bound_exceeded",
                        )
                    )
                    continue
                total += metadata.st_size
                if total > policy.max_total_bytes:
                    raise ValueError("security scan aggregate byte bound exceeded")
                entries.append((relative, path))
                if len(entries) > policy.max_files:
                    raise ValueError("security scan file-count bound exceeded")
    return sorted(entries), errors


def scan_artifact_roots(
    roots: Sequence[Path],
    *,
    report_id: str = "artifact-security-scan",
    policy: SecurityScanPolicy | None = None,
    proxy_values: Sequence[str] = (),
    forbidden_host_roots: Sequence[str] = (),
    fixture_paths: Sequence[str] = (),
) -> SecurityScanReport:
    """Scan artifacts without persisting suspected values, proxy values, or host roots."""

    if not roots:
        raise ValueError("at least one artifact root is required")
    resolved_policy = validate_security_scan_policy(policy or build_security_scan_policy())
    entries, findings = _safe_entries(roots, policy=resolved_policy)
    artifacts: list[ArtifactSecurityScan] = []
    scanned_bytes = 0
    structured_files = 0
    binary_files = 0
    proxy_bytes = tuple(value.encode("utf-8") for value in proxy_values if value)
    host_bytes = tuple(value.encode("utf-8") for value in forbidden_host_roots if value)
    fixture_set = frozenset(PurePosixPath(path).as_posix() for path in fixture_paths)
    for relative, path in entries:
        data = path.read_bytes()
        scanned_bytes += len(data)
        parser = _parser_for(path, data)
        content_class = _artifact_class(relative)
        fixture = relative in fixture_set
        if fixture:
            content_class = "security_scan_fixture"
        artifact_findings: list[SecurityFinding] = []
        if any(value in data for value in proxy_bytes):
            artifact_findings.append(
                _finding(
                    relative=relative,
                    content_class=content_class,
                    field_path=None,
                    role="runtime_value",
                    category="persisted_proxy_value",
                    severity="hard_secret_leak",
                    value=None,
                    rationale="exact_proxy_value_persisted",
                )
            )
        if any(value in data for value in host_bytes):
            artifact_findings.append(
                _finding(
                    relative=relative,
                    content_class=content_class,
                    field_path=None,
                    role="known_path_identity",
                    category="raw_host_path",
                    severity="hard_secret_leak",
                    value=None,
                    rationale="forbidden_host_root_persisted",
                )
            )
        fields = 0
        if parser in {"json", "jsonl", "yaml", "toml", "csv"}:
            structured_files += 1
            try:
                payload = _parse_structured(parser, data)
                diagnostics = 0
                for node in _walk_structured(payload, content_class=content_class):
                    fields += 1
                    node_findings = _structured_node_findings(
                        node,
                        relative=relative,
                        content_class=content_class,
                        fixture=fixture,
                        policy=resolved_policy,
                        diagnostics_remaining=_MAX_DIAGNOSTICS_PER_ARTIFACT - diagnostics,
                    )
                    diagnostics += sum(
                        item.severity
                        in {"diagnostic_security_metadata", "diagnostic_security_vocabulary"}
                        for item in node_findings
                    )
                    artifact_findings.extend(node_findings)
            except (ValueError, TypeError, UnicodeDecodeError, yaml.YAMLError, csv.Error):
                artifact_findings.append(
                    _finding(
                        relative=relative,
                        content_class=content_class,
                        field_path=None,
                        role="unknown_value",
                        category="malformed_structured_artifact",
                        severity="scanner_error",
                        value=None,
                        rationale=f"malformed_{parser}_artifact",
                    )
                )
        else:
            if parser == "binary":
                binary_files += 1
            artifact_findings.extend(
                _explicit_secret_findings(
                    data,
                    relative=relative,
                    content_class=content_class,
                    field_path=None,
                    role=("documentation_text" if parser == "markdown" else "runtime_value"),
                    fixture=fixture,
                )
            )
            if (
                parser in {"markdown", "text"}
                and not artifact_findings
                and _SECURITY_VOCABULARY.search(data.decode("utf-8", errors="ignore"))
            ):
                artifact_findings.append(
                    _finding(
                        relative=relative,
                        content_class=content_class,
                        field_path=None,
                        role="documentation_text",
                        category="diagnostic_security_metadata",
                        severity="diagnostic_security_metadata",
                        value=None,
                        rationale="security_vocabulary_in_text",
                    )
                )
        findings.extend(artifact_findings)
        artifacts.append(
            _artifact_record(
                relative=relative,
                content_class=content_class,
                parser=parser,
                size=len(data),
                structured=parser in {"json", "jsonl", "yaml", "toml", "csv"},
                fields=fields,
                findings=artifact_findings,
            )
        )
    for error in findings:
        if error.severity != "scanner_error":
            continue
        if not any(item.relative_path == error.relative_path for item in artifacts):
            artifacts.append(
                _artifact_record(
                    relative=error.relative_path,
                    content_class=error.artifact_content_class,
                    parser="binary",
                    size=0,
                    structured=False,
                    fields=0,
                    findings=[error],
                )
            )
    ordered_findings = tuple(
        sorted(
            findings,
            key=lambda item: (
                item.relative_path,
                item.structured_field_path or "",
                item.severity,
                item.evidence_category,
            ),
        )
    )
    ordered_artifacts = tuple(sorted(artifacts, key=lambda item: item.relative_path))
    hard = sum(item.severity == "hard_secret_leak" for item in ordered_findings)
    diagnostic = sum(
        item.severity in {"diagnostic_security_metadata", "diagnostic_security_vocabulary"}
        for item in ordered_findings
    )
    errors = sum(item.severity == "scanner_error" for item in ordered_findings)
    base = {
        "schema_version": "1.0",
        "report_id": report_id,
        "policy_hash": resolved_policy.policy_hash,
        "root_count": len(roots),
        "scanned_files": len(entries),
        "scanned_bytes": scanned_bytes,
        "structured_files": structured_files,
        "binary_files": binary_files,
        "hard_secret_leak_count": hard,
        "diagnostic_security_vocabulary_count": diagnostic,
        "scanner_error_count": errors,
        "proxy_values_persisted_or_hashed": False,
        "raw_suspected_values_exported": False,
        "findings": ordered_findings,
        "artifacts": ordered_artifacts,
        "gate": "pass" if hard == 0 and errors == 0 else "fail",
    }
    return SecurityScanReport.model_validate({**base, "report_hash": content_hash(base)})


def validate_security_scan_report(report: SecurityScanReport) -> SecurityScanReport:
    for artifact in report.artifacts:
        payload = artifact.model_dump(mode="json")
        observed = payload.pop("scan_hash")
        if content_hash(payload) != observed:
            raise ValueError("artifact security scan identity changed")
    payload = report.model_dump(mode="json")
    observed = payload.pop("report_hash")
    if content_hash(payload) != observed:
        raise ValueError("security scan report identity changed")
    return report


def require_security_scan_pass(report: SecurityScanReport) -> SecurityScanReport:
    validate_security_scan_report(report)
    if report.gate != "pass":
        raise SecurityScanFailure(report)
    return report


__all__ = [
    "SecurityScanFailure",
    "build_security_scan_policy",
    "classify_structured_field_role",
    "require_security_scan_pass",
    "scan_artifact_roots",
    "validate_security_scan_policy",
    "validate_security_scan_report",
]

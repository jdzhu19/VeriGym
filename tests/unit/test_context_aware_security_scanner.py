from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from verigym.core.security_scanner import (
    SecurityScanFailure,
    build_security_scan_policy,
    require_security_scan_pass,
    scan_artifact_roots,
    validate_security_scan_policy,
    validate_security_scan_report,
)

FIXTURE = Path("tests/fixtures/m10b_historical_allowed_synthesis_corpus_93097b7.json")
PRIVATE_KEY_BEGIN = "-----BEGIN " + "PRIVATE " + "KEY-----"
PRIVATE_KEY_END = "-----END " + "PRIVATE " + "KEY-----"
OPENSSH_KEY_BEGIN = "-----BEGIN " + "OPENSSH " + "PRIVATE " + "KEY-----"
OPENSSH_KEY_END = "-----END " + "OPENSSH " + "PRIVATE " + "KEY-----"
CANARIES = {
    "bearer": "bearer-canary-7Qv3R2m9Lp5Xs8Nd4Jt6",
    "provider": "sk-" + "proj-" + "7Qv3R2m9Lp5Xs8Nd4Jt6Kc8Wz1Hb4",
    "refresh": "refresh-canary-7Qv3R2m9Lp5Xs8Nd4Jt6",
    "cookie": "cookie-canary-7Qv3R2m9Lp5Xs8Nd4Jt6",
    "pem": "MIIEowIBAAKCAQEA7Qv3R2m9Lp5Xs8Nd4Jt6",
    "openssh": "b3BlbnNzaC1rZXktdjEAAAAABG5vbmU7Qv3R2m9",
    "uri": "proxy-password-7Qv3R2m9Lp5Xs8Nd4Jt6",
    "assignment": "assignment-canary-7Qv3R2m9Lp5Xs8Nd4Jt6",
    "yaml": "yaml-canary-7Qv3R2m9Lp5Xs8Nd4Jt6",
    "toml": "toml-canary-7Qv3R2m9Lp5Xs8Nd4Jt6",
    "unknown": "X7vQ2mL9pR4sN8dK5jH3cW6zB1fT0aY",
}


def _write(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


def _scan(root: Path, **kwargs: object):
    return scan_artifact_roots([root], report_id="unit-security-scan", **kwargs)


def test_policy_and_empty_scan_are_deterministic(tmp_path: Path) -> None:
    first = build_security_scan_policy()
    second = build_security_scan_policy()
    assert first == second
    validate_security_scan_policy(first)
    _write(tmp_path / "plain.json", '{"resolved": true, "count": 3}')
    one = _scan(tmp_path)
    two = _scan(tmp_path)
    assert one == two
    assert one.gate == "pass"
    assert one.report_hash == two.report_hash
    validate_security_scan_report(one)
    require_security_scan_pass(one)


def test_historical_allowed_corpus_identifier_is_diagnostic_not_secret(tmp_path: Path) -> None:
    reproduced = json.loads(FIXTURE.read_text(encoding="utf-8"))
    target = tmp_path / "implementation/allowed-synthesis-corpus.json"
    _write(target, json.dumps(reproduced, sort_keys=True))
    report = _scan(tmp_path)
    assert report.gate == "pass"
    assert report.hard_secret_leak_count == report.scanner_error_count == 0
    assert report.diagnostic_security_vocabulary_count > 0
    assert all(finding.severity != "hard_secret_leak" for finding in report.findings)
    assert report.raw_suspected_values_exported is False


def test_provider_prefix_kebab_identifier_is_diagnostic_but_sensitive_field_blocks(
    tmp_path: Path,
) -> None:
    identifier = "sk-" + "generalized-" + "memory-" + "policy"
    _write(
        tmp_path / "forensic.json",
        json.dumps({"matched_noncredential_suffix": identifier}),
    )
    diagnostic = _scan(tmp_path)
    assert diagnostic.gate == "pass"
    assert diagnostic.hard_secret_leak_count == 0
    assert any(
        finding.rationale_code == "provider_prefix_kebab_identifier_without_secret_value"
        for finding in diagnostic.findings
    )
    assert identifier not in diagnostic.model_dump_json()

    _write(tmp_path / "credential.json", json.dumps({"api_key": identifier}))
    blocking = _scan(tmp_path)
    assert blocking.gate == "fail"
    assert any(
        finding.field_role == "credential_value_candidate"
        and finding.severity == "hard_secret_leak"
        for finding in blocking.findings
    )


@pytest.mark.parametrize(
    ("relative", "payload", "category"),
    [
        (
            "authorization.txt",
            f"Authorization: Bearer {CANARIES['bearer']}",
            "authorization_bearer",
        ),
        ("provider.txt", CANARIES["provider"], "provider_api_token"),
        (
            "refresh.json",
            json.dumps({"refresh_token": CANARIES["refresh"]}),
            "session_or_cookie",
        ),
        ("cookie.json", json.dumps({"cookie": CANARIES["cookie"]}), "session_or_cookie"),
        (
            "private.pem",
            PRIVATE_KEY_BEGIN + "\n" + CANARIES["pem"] + "\n" + PRIVATE_KEY_END,
            "private_key",
        ),
        (
            "openssh.txt",
            OPENSSH_KEY_BEGIN + "\n" + CANARIES["openssh"] + "\n" + OPENSSH_KEY_END,
            "private_key",
        ),
        (
            "proxy.txt",
            f"https://proxy-user:{CANARIES['uri']}@proxy.example.test:8443",
            "credential_bearing_uri",
        ),
        (
            "assignment.env",
            f"SECRET_KEY={CANARIES['assignment']}",
            "persisted_secret_assignment",
        ),
        ("structured.yaml", f"api_key: {CANARIES['yaml']}\n", "persisted_secret_assignment"),
        (
            "structured.toml",
            f'session_token = "{CANARIES["toml"]}"\n',
            "session_or_cookie",
        ),
        (
            "unknown.json",
            json.dumps({"unknown_sensitive_value": CANARIES["unknown"]}),
            "unknown_sensitive_high_entropy",
        ),
    ],
)
def test_true_positive_canaries_are_blocking_and_redacted(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    relative: str,
    payload: str,
    category: str,
) -> None:
    _write(tmp_path / relative, payload)
    report = _scan(tmp_path)
    assert report.gate == "fail"
    assert report.hard_secret_leak_count >= 1
    assert category in {finding.evidence_category for finding in report.findings}
    serialized = report.model_dump_json()
    with pytest.raises(SecurityScanFailure) as raised:
        require_security_scan_pass(report)
    captured = capsys.readouterr()
    for canary in CANARIES.values():
        assert canary not in serialized
        assert canary not in str(raised.value)
        assert canary not in captured.out + captured.err
    assert all(finding.redacted for finding in report.findings)
    assert all(not finding.recoverable_fragment_exported for finding in report.findings)


def test_known_content_identities_never_block(tmp_path: Path) -> None:
    payload = {
        "source_commit": "a" * 40,
        "source_tree_hash": "b" * 64,
        "memory_pack_hash": "c" * 64,
        "plan_hash": "d" * 64,
        "task_hash": "e" * 64,
        "bundle_sha256": "f" * 64,
        "capability_fingerprint": "1" * 64,
        "image_digest": "sha256:" + "2" * 64,
        "runtime_session_id": "3" * 32,
        "manifest_id": "123e4567-e89b-12d3-a456-426614174000",
    }
    _write(tmp_path / "identities.json", json.dumps(payload))
    report = _scan(tmp_path)
    assert report.gate == "pass"
    assert report.hard_secret_leak_count == 0


def test_security_vocabulary_and_structured_policy_context_do_not_block(tmp_path: Path) -> None:
    payload = {
        "credential_environment_name": "OPENAI_API_KEY",
        "auth_semantic_id": "codex.auth.inherited_chatgpt_session.v1",
        "requested_auth_mode": "api_key_env",
        "resolved_auth_mode": "inherited_codex_login",
        "api_key_fallback": False,
        "secret_values_persisted": False,
        "refresh_token": None,
        "private_reasoning_exported": False,
        "documentation": (
            "Authentication, authorization, credentials, tokens, keys, secrets, proxy, "
            "validation, preserve, private reasoning, and the Authorization header are policy "
            "vocabulary. Environment-variable names do not contain their values."
        ),
    }
    _write(tmp_path / "schema-or-contract.json", json.dumps(payload))
    report = _scan(tmp_path)
    assert report.gate == "pass"
    assert report.hard_secret_leak_count == report.scanner_error_count == 0
    assert report.diagnostic_security_vocabulary_count > 0


def test_same_sensitive_key_with_value_blocks(tmp_path: Path) -> None:
    value = CANARIES["yaml"]
    _write(tmp_path / "runtime.json", json.dumps({"api_key": value}))
    report = _scan(tmp_path)
    assert report.gate == "fail"
    assert any(
        finding.field_role == "credential_value_candidate"
        and finding.severity == "hard_secret_leak"
        for finding in report.findings
    )
    assert value not in report.model_dump_json()


@pytest.mark.parametrize(
    ("relative", "payload"),
    [
        ("authorization.txt", "Authorization: Bearer x"),
        ("assignment.env", "SECRET_KEY=x"),
        ("session.json", '{"session_token":"x"}'),
    ],
)
def test_short_concrete_credential_values_still_fail_closed(
    tmp_path: Path, relative: str, payload: str
) -> None:
    _write(tmp_path / relative, payload)
    report = _scan(tmp_path)
    assert report.gate == "fail"
    assert report.hard_secret_leak_count >= 1


def test_fixture_placeholder_requires_bound_fixture_provenance(tmp_path: Path) -> None:
    _write(tmp_path / "fixture.json", json.dumps({"api_key": "REDACTED"}))
    production = _scan(tmp_path)
    assert production.gate == "fail"
    fixture = _scan(tmp_path, fixture_paths=("fixture.json",))
    assert fixture.gate == "pass"
    assert fixture.artifacts[0].artifact_content_class == "security_scan_fixture"


def test_exact_proxy_value_is_blocking_and_never_hashed(tmp_path: Path) -> None:
    proxy_value = "http://proxy-user:proxy-canary-7Qv3R2m9Lp5Xs8Nd4Jt6@example.test:8080"
    _write(tmp_path / "runtime.txt", "transport=" + proxy_value)
    report = _scan(tmp_path, proxy_values=(proxy_value,))
    proxy_findings = [
        finding
        for finding in report.findings
        if finding.evidence_category == "persisted_proxy_value"
    ]
    assert report.gate == "fail" and proxy_findings
    assert all(finding.evidence_sha256 is None for finding in proxy_findings)
    assert proxy_value not in report.model_dump_json()


def test_host_path_symlink_hardlink_and_malformed_structures_fail_closed(
    tmp_path: Path,
) -> None:
    host = "/data/private/source-root"
    _write(tmp_path / "host.json", json.dumps({"path": host + "/repo"}))
    malformed = _write(tmp_path / "malformed.json", "{not-json")
    original = _write(tmp_path / "original.txt", "ordinary")
    os.link(original, tmp_path / "hardlink.txt")
    (tmp_path / "symlink.txt").symlink_to(original)
    report = _scan(tmp_path, forbidden_host_roots=(host,))
    categories = {finding.evidence_category for finding in report.findings}
    assert report.gate == "fail"
    assert "raw_host_path" in categories
    assert "malformed_structured_artifact" in categories
    assert "unsafe_filesystem_entry" in categories
    assert malformed.name in {finding.relative_path for finding in report.findings}


def test_symlink_scan_root_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    linked = tmp_path / "linked-root"
    linked.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="ordinary directory"):
        _scan(linked)


def test_bundle_scale_scan_is_deterministic_and_keeps_values_private(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write(
        bundle / "implementation/allowed-synthesis-corpus.json",
        json.dumps(json.loads(FIXTURE.read_text(encoding="utf-8"))),
    )
    _write(bundle / "schemas/security.schema.json", json.dumps({"api_key": {"type": "string"}}))
    _write(bundle / "trajectory/trajectories.jsonl", '{"private_reasoning_exported":false}\n')
    _write(bundle / "memory/memory-pack.json", '{"secrets_included":false}\n')
    _write(bundle / "reports/report.md", "Credential and proxy validation policy.\n")
    first = _scan(bundle)
    second = _scan(bundle)
    assert first == second
    assert first.gate == "pass"
    assert first.scanned_files == 5
    assert first.raw_suspected_values_exported is False


def test_csv_and_binary_are_classified_and_scanned(tmp_path: Path) -> None:
    _write(tmp_path / "policy.csv", "name,value\nauth_mode,inherited_codex_login\n")
    binary = tmp_path / "artifact.bin"
    binary.write_bytes(b"\x00ordinary-binary\x01")
    report = _scan(tmp_path)
    assert report.gate == "pass"
    by_path = {artifact.relative_path: artifact for artifact in report.artifacts}
    assert by_path["policy.csv"].parser == "csv"
    assert by_path["artifact.bin"].parser == "binary"
    assert report.binary_files == 1

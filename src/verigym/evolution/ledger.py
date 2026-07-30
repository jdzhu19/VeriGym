"""Append-only, campaign-wide accounting for M10B model-bearing processes."""

from __future__ import annotations

import os
import stat
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from verigym.core.hashing import canonical_json, content_hash
from verigym.schemas.evolution import (
    EvolutionProcessLedgerManifest,
    EvolutionProcessLedgerRecord,
)

MAX_M10B_PROCESSES = 24


def _record(**values: object) -> EvolutionProcessLedgerRecord:
    payload = {"schema_version": "1.0", **values}
    payload.pop("record_hash", None)
    return EvolutionProcessLedgerRecord.model_validate(
        {**payload, "record_hash": content_hash(payload)}
    )


def validate_process_record(
    record: EvolutionProcessLedgerRecord,
) -> EvolutionProcessLedgerRecord:
    payload = record.model_dump(mode="json")
    expected = payload.pop("record_hash")
    candidates = [payload]
    lifecycle_fields = (
        "invocation_spec_hash",
        "payload_binding_hash",
        "memory_synthesis_plan_hash",
    )
    if all(payload[field] is None for field in lifecycle_fields):
        candidates.append(
            {key: value for key, value in payload.items() if key not in lifecycle_fields}
        )
    if all(content_hash(candidate) != expected for candidate in candidates):
        raise ValueError("evolution process-ledger record identity changed")
    return record


def _read_records(path: Path) -> list[EvolutionProcessLedgerRecord]:
    if not path.exists():
        return []
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode) or path.is_symlink():
        raise ValueError("process ledger must be a regular non-symlink file")
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("process ledger exceeds its 4 MiB bound")
    records: list[EvolutionProcessLedgerRecord] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            record = EvolutionProcessLedgerRecord.model_validate_json(line)
        except Exception as exc:
            raise ValueError(
                f"process ledger contains an invalid record at line {line_number}"
            ) from exc
        records.append(validate_process_record(record))
    return records


def validate_process_records(
    records: Sequence[EvolutionProcessLedgerRecord],
    *,
    authorization_id: str | None = None,
) -> list[EvolutionProcessLedgerRecord]:
    """Validate ordering, hash chains, unique process ordinals, and the global cap."""

    validated = [validate_process_record(record) for record in records]
    if authorization_id is not None and any(
        record.authorization_id != authorization_id for record in validated
    ):
        raise ValueError("process ledger contains another campaign authorization")
    authorized: dict[int, EvolutionProcessLedgerRecord] = {}
    terminal: dict[int, EvolutionProcessLedgerRecord] = {}
    last_ordinal = 0
    for record in validated:
        if record.record_phase == "authorized":
            if record.ordinal != last_ordinal + 1 or record.ordinal in authorized:
                raise ValueError("process authorizations must use contiguous unique ordinals")
            authorized[record.ordinal] = record
            last_ordinal = record.ordinal
            continue
        source = authorized.get(record.ordinal)
        if source is None or record.ordinal in terminal:
            raise ValueError("terminal records require one preceding unmatched authorization")
        if record.source_ledger_record_hash != source.record_hash:
            raise ValueError("terminal record does not bind its authorization record")
        stable_fields = (
            "process_kind",
            "authorization_id",
            "run_or_build_id",
            "task_identity_hash",
            "agent_version_hash",
            "invocation_spec_hash",
            "payload_binding_hash",
            "memory_synthesis_plan_hash",
            "requested_model_id",
            "reasoning_effort",
            "retry",
            "resume",
        )
        if any(getattr(record, field) != getattr(source, field) for field in stable_fields):
            raise ValueError("terminal process identity differs from its authorization")
        terminal[record.ordinal] = record
    if len(authorized) > MAX_M10B_PROCESSES:
        raise ValueError("M10B process authorization exceeds the 24-process ceiling")
    return validated


def _append(path: Path, record: EvolutionProcessLedgerRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and (path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode)):
        raise ValueError("process ledger must be a regular non-symlink file")
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    descriptor = os.open(path, flags, 0o600)
    try:
        os.write(descriptor, (canonical_json(record) + "\n").encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def authorize_process(
    path: Path,
    *,
    process_kind: str,
    authorization_id: str,
    run_or_build_id: str,
    requested_model_id: str,
    reasoning_effort: str,
    task_identity_hash: str | None = None,
    agent_version_hash: str | None = None,
    invocation_spec_hash: str | None = None,
    payload_binding_hash: str | None = None,
    memory_synthesis_plan_hash: str | None = None,
) -> EvolutionProcessLedgerRecord:
    """Durably append an authorization before a single process is launched."""

    records = validate_process_records(
        _read_records(path),
        authorization_id=authorization_id,
    )
    unfinished = {record.ordinal for record in records if record.record_phase == "authorized"} - {
        record.ordinal for record in records if record.record_phase == "terminal"
    }
    if unfinished:
        raise ValueError("a prior authorized process lacks a terminal ledger record")
    ordinal = sum(record.record_phase == "authorized" for record in records) + 1
    if ordinal > MAX_M10B_PROCESSES:
        raise ValueError("M10B process authorization exceeds the 24-process ceiling")
    record = _record(
        ordinal=ordinal,
        record_phase="authorized",
        process_kind=process_kind,
        authorization_id=authorization_id,
        run_or_build_id=run_or_build_id,
        task_identity_hash=task_identity_hash,
        agent_version_hash=agent_version_hash,
        invocation_spec_hash=invocation_spec_hash,
        payload_binding_hash=payload_binding_hash,
        memory_synthesis_plan_hash=memory_synthesis_plan_hash,
        requested_model_id=requested_model_id,
        reasoning_effort=reasoning_effort,
        model_process_started=False,
        retry=False,
        resume=False,
        terminal=False,
        terminal_outcome=None,
        source_ledger_record_hash=None,
    )
    _append(path, record)
    return record


def finish_process(
    path: Path,
    *,
    authorization_record: EvolutionProcessLedgerRecord,
    terminal_outcome: str,
) -> EvolutionProcessLedgerRecord:
    """Append the terminal half of an already-authorized process record."""

    records = validate_process_records(
        _read_records(path),
        authorization_id=authorization_record.authorization_id,
    )
    matching = [
        record
        for record in records
        if record.ordinal == authorization_record.ordinal and record.record_phase == "authorized"
    ]
    if matching != [authorization_record]:
        raise ValueError("process authorization is absent or differs from the ledger")
    if any(
        record.ordinal == authorization_record.ordinal and record.record_phase == "terminal"
        for record in records
    ):
        raise ValueError("process already has a terminal ledger record")
    if not terminal_outcome:
        raise ValueError("terminal process outcome cannot be empty")
    values = authorization_record.model_dump(mode="json")
    values.update(
        {
            "record_phase": "terminal",
            "model_process_started": True,
            "terminal": True,
            "terminal_outcome": terminal_outcome,
            "source_ledger_record_hash": authorization_record.record_hash,
        }
    )
    record = _record(**values)
    _append(path, record)
    validate_process_records([*records, record])
    return record


def seal_process_ledger(
    path: Path,
    *,
    authorization_id: str,
    complete: bool,
) -> EvolutionProcessLedgerManifest:
    """Create an immutable summary while retaining the append-only JSONL evidence."""

    records = validate_process_records(
        _read_records(path),
        authorization_id=authorization_id,
    )
    authorizations = [record for record in records if record.record_phase == "authorized"]
    terminals = [record for record in records if record.record_phase == "terminal"]
    if complete and len(authorizations) != len(terminals):
        raise ValueError("a complete process ledger requires every process to be terminal")
    counts = Counter(record.process_kind for record in authorizations)
    base = {
        "schema_version": "1.0",
        "authorization_id": authorization_id,
        "records": [record.model_dump(mode="json") for record in records],
        "authorized_processes": len(authorizations),
        "started_processes": len(terminals),
        "terminal_processes": len(terminals),
        "process_kind_counts": dict(sorted(counts.items())),
        "maximum_processes": MAX_M10B_PROCESSES,
        "complete": complete,
    }
    return EvolutionProcessLedgerManifest.model_validate(
        {**base, "manifest_hash": content_hash(base)}
    )


def validate_process_ledger_manifest(
    manifest: EvolutionProcessLedgerManifest,
) -> EvolutionProcessLedgerManifest:
    payload = manifest.model_dump(mode="json")
    expected = payload.pop("manifest_hash")
    if content_hash(payload) != expected:
        raise ValueError("evolution process-ledger manifest identity changed")
    records = validate_process_records(
        manifest.records,
        authorization_id=manifest.authorization_id,
    )
    rebuilt_counts = Counter(
        record.process_kind for record in records if record.record_phase == "authorized"
    )
    terminals = sum(record.record_phase == "terminal" for record in records)
    if (
        manifest.authorized_processes
        != sum(record.record_phase == "authorized" for record in records)
        or manifest.started_processes != terminals
        or manifest.terminal_processes != terminals
        or manifest.process_kind_counts != dict(sorted(rebuilt_counts.items()))
        or (manifest.complete and manifest.authorized_processes != terminals)
    ):
        raise ValueError("process-ledger manifest counters differ from its records")
    return manifest


__all__ = [
    "MAX_M10B_PROCESSES",
    "authorize_process",
    "finish_process",
    "seal_process_ledger",
    "validate_process_ledger_manifest",
    "validate_process_record",
    "validate_process_records",
]

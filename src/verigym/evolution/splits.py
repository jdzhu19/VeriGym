"""Task-split identity and provenance-aware post-freeze contamination scanning."""

from __future__ import annotations

import os
import re
import stat
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from verigym.core.hashing import canonical_json, content_hash, hash_bytes
from verigym.schemas.evolution import (
    AllowedSynthesisCorpus,
    AllowedSynthesisSource,
    AssetSignatureBucket,
    AssetSignatureManifest,
    ContaminationFinding,
    ContaminationMatch,
    ContaminationMatchClass,
    ContaminationScan,
    ContaminationScanPolicy,
    ContaminationScanReport,
    FrozenMemoryContaminationScan,
    MemoryPack,
    SanitizedTrainingSummary,
    SplitAssetContaminationScan,
    TaskSplitEntry,
    TaskSplitManifest,
)

_MAX_FILES = 20_000
_MAX_FILE_BYTES = 8 * 1024 * 1024
_SEMANTIC_EXCLUDED_NAMES = {"LICENSE", "NOTICE", ".gitignore"}
_LEXICAL_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_$-]*|\d+")
_IDENTIFIER_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_PUBLIC_TRAINING_PREFIXES = ("repository/", "public/")
_PRIVATE_CLASSES = {"hidden_test_fragment", "reference_patch_fragment"}


@dataclass(frozen=True)
class _Signature:
    match_class: ContaminationMatchClass
    signature_hash: str
    heldout_identity: str
    task_hash: str
    source_artifact_hash: str
    normalized_token_count: int
    match_location_class: str
    normalized_value: str | None = None


def build_task_split(
    *,
    split_id: str,
    training: Sequence[TaskSplitEntry],
    heldout: Sequence[TaskSplitEntry],
    validation: Sequence[TaskSplitEntry] = (),
    heldout_assets_loaded_after_version_hash: str | None = None,
) -> TaskSplitManifest:
    payload = {
        "schema_version": "1.0",
        "split_id": split_id,
        "training": [
            item.model_dump(mode="json") for item in sorted(training, key=lambda item: item.task_id)
        ],
        "validation": [
            item.model_dump(mode="json")
            for item in sorted(validation, key=lambda item: item.task_id)
        ],
        "heldout": [
            item.model_dump(mode="json") for item in sorted(heldout, key=lambda item: item.task_id)
        ],
        "heldout_assets_loaded_after_version_hash": heldout_assets_loaded_after_version_hash,
    }
    return TaskSplitManifest.model_validate({**payload, "manifest_hash": content_hash(payload)})


def validate_task_split(manifest: TaskSplitManifest) -> TaskSplitManifest:
    payload = manifest.model_dump(mode="json")
    expected = payload.pop("manifest_hash")
    if content_hash(payload) != expected:
        raise ValueError("task split identity changed")
    return manifest


def build_contamination_scan_policy(
    *,
    natural_language_min_tokens: int = 5,
    natural_language_min_characters: int = 20,
    code_sequence_min_tokens: int = 5,
    source_fragment_min_lines: int = 5,
    distinctive_identifier_min_characters: int = 5,
) -> ContaminationScanPolicy:
    """Freeze tokenizer, thresholds, match vocabulary, privacy, and unknown handling."""

    base = {
        "schema_version": "1.0",
        "policy_id": "provenance_aware_contamination_v1",
        "tokenizer_id": "ascii_casefold_lexical_v1",
        "natural_language_min_tokens": natural_language_min_tokens,
        "natural_language_min_characters": natural_language_min_characters,
        "code_sequence_min_tokens": code_sequence_min_tokens,
        "source_fragment_min_lines": source_fragment_min_lines,
        "distinctive_identifier_min_characters": distinctive_identifier_min_characters,
        "known_match_classes": sorted(get_args(ContaminationMatchClass)),
        "hidden_reference_output": "hash_only",
        "unknown_match_policy": "fail_closed",
    }
    return ContaminationScanPolicy.model_validate({**base, "policy_hash": content_hash(base)})


def validate_contamination_scan_policy(
    policy: ContaminationScanPolicy,
) -> ContaminationScanPolicy:
    payload = policy.model_dump(mode="json")
    expected = payload.pop("policy_hash")
    if content_hash(payload) != expected:
        raise ValueError("contamination policy identity changed")
    return policy


def _regular_files(root: Path) -> dict[str, bytes]:
    resolved = root.resolve(strict=True)
    result: dict[str, bytes] = {}
    inodes: set[tuple[int, int]] = set()
    for directory, names, files in os.walk(resolved, followlinks=False):
        names.sort()
        files.sort()
        base = Path(directory)
        for name in names:
            metadata = os.lstat(base / name)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise ValueError("split source contains a symlink or special directory entry")
        for name in files:
            path = base / name
            metadata = os.lstat(path)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ValueError("split source contains a symlink or special file")
            inode = (metadata.st_dev, metadata.st_ino)
            if inode in inodes or metadata.st_nlink != 1:
                raise ValueError("split source contains a hard-linked file")
            inodes.add(inode)
            if metadata.st_size > _MAX_FILE_BYTES:
                raise ValueError("split source contains an oversized file")
            relative = path.relative_to(resolved).as_posix()
            result[relative] = path.read_bytes()
            if len(result) > _MAX_FILES:
                raise ValueError("split source exceeds the file-count bound")
    return result


def _decode(payload: bytes) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def _tokens(text: str) -> list[str]:
    return [value.casefold() for value in _LEXICAL_TOKEN.findall(text)]


def _token_ngrams(text: str, width: int) -> list[tuple[str, str]]:
    tokens = _tokens(text)
    values: list[tuple[str, str]] = []
    for index in range(max(0, len(tokens) - width + 1)):
        normalized = " ".join(tokens[index : index + width])
        values.append((normalized, hash_bytes(normalized.encode("utf-8"))))
    return values


def _line_shingles(payload: bytes, width: int) -> set[str]:
    text = _decode(payload)
    if not text:
        return set()
    normalized = [
        " ".join(line.strip().split())
        for line in text.splitlines()
        if len(" ".join(line.strip().split())) >= 16
        and not line.lstrip().startswith(("//", "#", "/*", "*"))
    ]
    return {
        hash_bytes("\n".join(normalized[index : index + width]).encode("utf-8"))
        for index in range(max(0, len(normalized) - width + 1))
    }


def _public_training_payloads(files: Mapping[str, bytes]) -> dict[str, bytes]:
    return {
        path: payload
        for path, payload in files.items()
        if path == "issue.md" or path.startswith(_PUBLIC_TRAINING_PREFIXES)
    }


def _source_record(
    *,
    source_id: str,
    source_class: str,
    materials: Mapping[str, str],
) -> tuple[AllowedSynthesisSource, str]:
    canonical_material = canonical_json(dict(sorted(materials.items())))
    tokens = _tokens(canonical_material)
    record = AllowedSynthesisSource(
        source_id=source_id,
        source_class=source_class,  # type: ignore[arg-type]
        content_hash=hash_bytes(canonical_material.encode("utf-8")),
        token_count=len(tokens),
    )
    return record, canonical_material


def build_allowed_synthesis_corpus(
    *,
    policy: ContaminationScanPolicy,
    training_roots: Mapping[str, Path],
    prompt_schema_texts: Mapping[str, str],
    sanitized_training_summary: SanitizedTrainingSummary | None,
    reward_channel_names: Sequence[str],
    generic_policy_instructions: Mapping[str, str],
    corpus_id: str = "m10b-allowed-synthesis-corpus-v1",
) -> AllowedSynthesisCorpus:
    """Hash only material legitimately available to memory synthesis before v1 freeze."""

    validate_contamination_scan_policy(policy)
    records_and_text: list[tuple[AllowedSynthesisSource, str]] = []
    records_and_text.append(
        _source_record(
            source_id="memory-builder-prompt-schema",
            source_class="memory_builder_prompt_schema",
            materials=prompt_schema_texts,
        )
    )
    if sanitized_training_summary is not None:
        records_and_text.append(
            _source_record(
                source_id="sanitized-training-summary",
                source_class="sanitized_training_summary",
                materials={
                    "summary": canonical_json(sanitized_training_summary.model_dump(mode="json"))
                },
            )
        )
    training_public: dict[str, str] = {}
    for task_id, root in sorted(training_roots.items()):
        for relative, payload in sorted(_public_training_payloads(_regular_files(root)).items()):
            text = _decode(payload)
            if text:
                training_public[f"{task_id}:{relative}"] = text
    records_and_text.append(
        _source_record(
            source_id="training-public-assets",
            source_class="training_public_assets",
            materials=training_public,
        )
    )
    records_and_text.append(
        _source_record(
            source_id="reward-channel-names",
            source_class="reward_channel_names",
            materials={
                str(index): value for index, value in enumerate(sorted(set(reward_channel_names)))
            },
        )
    )
    records_and_text.append(
        _source_record(
            source_id="generic-policy-instructions",
            source_class="generic_policy_instructions",
            materials=generic_policy_instructions,
        )
    )
    records_and_text.sort(key=lambda item: item[0].source_id)
    material_text = "\n".join(text for _, text in records_and_text)
    normalized_tokens = sorted(set(_tokens(material_text)))
    phrase_hashes = sorted(
        {
            digest
            for width in {
                policy.natural_language_min_tokens,
                policy.code_sequence_min_tokens,
            }
            for _, digest in _token_ngrams(material_text, width)
        }
    )
    base = {
        "schema_version": "1.0",
        "corpus_id": corpus_id,
        "policy_hash": policy.policy_hash,
        "sources": [record.model_dump(mode="json") for record, _ in records_and_text],
        "normalized_tokens": normalized_tokens,
        "normalized_phrase_hashes": phrase_hashes,
        "heldout_assets_included": False,
        "hidden_assets_included": False,
        "reference_assets_included": False,
    }
    return AllowedSynthesisCorpus.model_validate({**base, "corpus_hash": content_hash(base)})


def validate_allowed_synthesis_corpus(
    corpus: AllowedSynthesisCorpus,
) -> AllowedSynthesisCorpus:
    payload = corpus.model_dump(mode="json")
    expected = payload.pop("corpus_hash")
    if content_hash(payload) != expected:
        raise ValueError("allowed synthesis corpus identity changed")
    return corpus


def _entry_map(entries: Sequence[TaskSplitEntry]) -> dict[str, TaskSplitEntry]:
    return {entry.task_id: entry for entry in entries}


def _is_distinctive_identifier(value: str, minimum: int) -> bool:
    if len(value) < minimum:
        return False
    return (
        "_" in value
        or "$" in value
        or any(character.isdigit() for character in value)
        or (
            any(character.islower() for character in value)
            and any(character.isupper() for character in value)
        )
    )


def _collect_heldout_signatures(
    *,
    split_manifest: TaskSplitManifest,
    heldout_roots: Mapping[str, Path],
    allowed_corpus: AllowedSynthesisCorpus,
    policy: ContaminationScanPolicy,
) -> tuple[list[_Signature], dict[str, bytes]]:
    expected = {entry.task_id for entry in split_manifest.heldout}
    if set(heldout_roots) != expected:
        raise ValueError("held-out roots do not match the frozen split")
    allowed_tokens = set(allowed_corpus.normalized_tokens)
    allowed_phrases = set(allowed_corpus.normalized_phrase_hashes)
    entries = _entry_map(split_manifest.heldout)
    all_files: dict[str, bytes] = {}
    signatures: dict[tuple[str, str, str], _Signature] = {}

    def add(signature: _Signature) -> None:
        key = (signature.match_class, signature.signature_hash, signature.heldout_identity)
        signatures[key] = signature

    for task_id, root in sorted(heldout_roots.items()):
        entry = entries[task_id]
        files = _regular_files(root)
        for relative, payload in files.items():
            all_files[f"{task_id}:{relative}"] = payload
        task_id_normalized = task_id.casefold()
        add(
            _Signature(
                match_class="exact_task_id",
                signature_hash=hash_bytes(task_id_normalized.encode("utf-8")),
                heldout_identity=task_id,
                task_hash=entry.task_hash,
                source_artifact_hash=entry.source_hash,
                normalized_token_count=len(_tokens(task_id_normalized)),
                match_location_class="heldout_task_identity",
                normalized_value=task_id_normalized,
            )
        )
        for relative, payload in sorted(files.items()):
            artifact_hash = hash_bytes(payload)
            if relative.startswith(("repository/", "public/")):
                normalized_path = relative.casefold()
                add(
                    _Signature(
                        match_class="repository_path",
                        signature_hash=hash_bytes(normalized_path.encode("utf-8")),
                        heldout_identity=f"{task_id}:{relative}",
                        task_hash=entry.task_hash,
                        source_artifact_hash=artifact_hash,
                        normalized_token_count=max(1, len(_tokens(normalized_path))),
                        match_location_class="heldout_public_path",
                        normalized_value=normalized_path,
                    )
                )
            text = _decode(payload)
            is_public = relative == "issue.md" or relative.startswith(_PUBLIC_TRAINING_PREFIXES)
            if is_public and text:
                for identifier in sorted(set(_IDENTIFIER_TOKEN.findall(text))):
                    normalized_identifier = identifier.casefold()
                    if (
                        _is_distinctive_identifier(
                            identifier, policy.distinctive_identifier_min_characters
                        )
                        and normalized_identifier not in allowed_tokens
                    ):
                        add(
                            _Signature(
                                match_class="distinctive_identifier",
                                signature_hash=hash_bytes(normalized_identifier.encode("utf-8")),
                                heldout_identity=f"{task_id}:{relative}",
                                task_hash=entry.task_hash,
                                source_artifact_hash=artifact_hash,
                                normalized_token_count=1,
                                match_location_class="heldout_public_identifier",
                                normalized_value=normalized_identifier,
                            )
                        )
            if relative == "issue.md" and text:
                for phrase, digest in _token_ngrams(text, policy.natural_language_min_tokens):
                    if (
                        len(phrase) >= policy.natural_language_min_characters
                        and digest not in allowed_phrases
                    ):
                        add(
                            _Signature(
                                match_class="heldout_issue_phrase",
                                signature_hash=digest,
                                heldout_identity=f"{task_id}:issue.md",
                                task_hash=entry.task_hash,
                                source_artifact_hash=artifact_hash,
                                normalized_token_count=policy.natural_language_min_tokens,
                                match_location_class="heldout_public_issue",
                                normalized_value=phrase,
                            )
                        )
            if is_public and relative.endswith((".sv", ".v")) and text:
                for phrase, digest in _token_ngrams(text, policy.code_sequence_min_tokens):
                    if digest not in allowed_phrases:
                        add(
                            _Signature(
                                match_class="source_code_sequence",
                                signature_hash=digest,
                                heldout_identity=f"{task_id}:{relative}",
                                task_hash=entry.task_hash,
                                source_artifact_hash=artifact_hash,
                                normalized_token_count=policy.code_sequence_min_tokens,
                                match_location_class="heldout_public_source",
                                normalized_value=phrase,
                            )
                        )
            private_class: ContaminationMatchClass | None = None
            if relative.startswith("hidden/"):
                private_class = "hidden_test_fragment"
            elif relative.endswith("reference.patch"):
                private_class = "reference_patch_fragment"
            if private_class is not None:
                for digest in sorted(_line_shingles(payload, policy.source_fragment_min_lines)):
                    add(
                        _Signature(
                            match_class=private_class,
                            signature_hash=digest,
                            heldout_identity=f"{task_id}:<{private_class}>",
                            task_hash=entry.task_hash,
                            source_artifact_hash=artifact_hash,
                            normalized_token_count=policy.source_fragment_min_lines,
                            match_location_class=private_class,
                            normalized_value=None,
                        )
                    )
    return sorted(
        signatures.values(),
        key=lambda item: (
            item.match_class,
            item.signature_hash,
            item.heldout_identity,
        ),
    ), all_files


def build_asset_signature_manifest(
    *,
    split_manifest: TaskSplitManifest,
    training_roots: Mapping[str, Path],
    heldout_roots: Mapping[str, Path],
    allowed_corpus: AllowedSynthesisCorpus,
    policy: ContaminationScanPolicy,
    manifest_id: str | None = None,
) -> AssetSignatureManifest:
    validate_task_split(split_manifest)
    validate_contamination_scan_policy(policy)
    validate_allowed_synthesis_corpus(allowed_corpus)
    if allowed_corpus.policy_hash != policy.policy_hash:
        raise ValueError("allowed synthesis corpus binds another contamination policy")
    signatures, heldout_files = _collect_heldout_signatures(
        split_manifest=split_manifest,
        heldout_roots=heldout_roots,
        allowed_corpus=allowed_corpus,
        policy=policy,
    )
    training_files = {
        f"{task_id}:{path}": payload
        for task_id, root in sorted(training_roots.items())
        for path, payload in _regular_files(root).items()
    }
    buckets: list[AssetSignatureBucket] = []
    by_class: dict[str, list[str]] = defaultdict(list)
    for signature in signatures:
        by_class[signature.match_class].append(signature.signature_hash)
    for match_class, hashes in sorted(by_class.items()):
        unique_hashes = sorted(set(hashes))
        buckets.append(
            AssetSignatureBucket(
                match_class=match_class,  # type: ignore[arg-type]
                signature_count=len(unique_hashes),
                signature_set_hash=content_hash(unique_hashes),
            )
        )
    base = {
        "schema_version": "1.0",
        "manifest_id": manifest_id or f"{split_manifest.split_id}-asset-signatures",
        "split_manifest_hash": split_manifest.manifest_hash,
        "policy_hash": policy.policy_hash,
        "allowed_synthesis_corpus_hash": allowed_corpus.corpus_hash,
        "buckets": [bucket.model_dump(mode="json") for bucket in buckets],
        "training_file_count": len(training_files),
        "heldout_file_count": len(heldout_files),
        "hidden_assets_exported": False,
        "reference_assets_exported": False,
    }
    return AssetSignatureManifest.model_validate({**base, "manifest_hash": content_hash(base)})


def validate_asset_signature_manifest(
    manifest: AssetSignatureManifest,
) -> AssetSignatureManifest:
    payload = manifest.model_dump(mode="json")
    expected = payload.pop("manifest_hash")
    if content_hash(payload) != expected:
        raise ValueError("asset signature manifest identity changed")
    return manifest


def _match_sort_key(match: ContaminationMatch) -> tuple[object, ...]:
    return (
        match.severity,
        match.match_class,
        match.training_identity or "",
        match.heldout_identity,
        match.evidence_hash,
    )


def _match(
    *,
    stage: str,
    match_class: str,
    evidence_hash: str,
    heldout_identity: str,
    normalized_token_count: int,
    match_location_class: str,
    training_identity: str | None = None,
    task_hash: str | None = None,
    source_artifact_hash: str | None = None,
    public_excerpt: str | None = None,
) -> ContaminationMatch:
    return ContaminationMatch(
        stage=stage,  # type: ignore[arg-type]
        match_class=match_class,  # type: ignore[arg-type]
        severity=(
            "diagnostic_overlap"
            if match_class in {"allowed_synthesis_vocabulary", "generic_vocabulary"}
            else "hard_contamination"
        ),
        evidence_hash=evidence_hash,
        training_identity=training_identity,
        heldout_identity=heldout_identity,
        task_hash=task_hash,
        source_artifact_hash=source_artifact_hash,
        normalized_token_count=normalized_token_count,
        match_location_class=match_location_class,
        public_excerpt=public_excerpt,
    )


def scan_split_assets(
    *,
    split_manifest: TaskSplitManifest,
    training_roots: Mapping[str, Path],
    heldout_roots: Mapping[str, Path],
    signature_manifest: AssetSignatureManifest,
    policy: ContaminationScanPolicy,
) -> SplitAssetContaminationScan:
    """Detect train/held-out asset reuse independently of frozen memory."""

    validate_task_split(split_manifest)
    validate_contamination_scan_policy(policy)
    validate_asset_signature_manifest(signature_manifest)
    if (
        signature_manifest.split_manifest_hash != split_manifest.manifest_hash
        or signature_manifest.policy_hash != policy.policy_hash
    ):
        raise ValueError("asset signature manifest differs from split scan identity")
    expected_train = {item.task_id for item in split_manifest.training}
    expected_heldout = {item.task_id for item in split_manifest.heldout}
    if set(training_roots) != expected_train or set(heldout_roots) != expected_heldout:
        raise ValueError("contamination roots do not match the frozen split")
    heldout_entries = _entry_map(split_manifest.heldout)
    training_files = {
        f"{task_id}:{path}": payload
        for task_id, root in sorted(training_roots.items())
        for path, payload in _regular_files(root).items()
    }
    heldout_files = {
        f"{task_id}:{path}": payload
        for task_id, root in sorted(heldout_roots.items())
        for path, payload in _regular_files(root).items()
    }
    matches: dict[tuple[str, str, str, str], ContaminationMatch] = {}

    def add(match: ContaminationMatch) -> None:
        key = (
            match.match_class,
            match.training_identity or "",
            match.heldout_identity,
            match.evidence_hash,
        )
        matches[key] = match

    train_hashes: dict[str, list[str]] = defaultdict(list)
    for identity, payload in training_files.items():
        relative = identity.split(":", 1)[1]
        if Path(relative).name not in _SEMANTIC_EXCLUDED_NAMES:
            train_hashes[hash_bytes(payload)].append(identity)
    for identity, payload in heldout_files.items():
        task_id, relative = identity.split(":", 1)
        if Path(relative).name in _SEMANTIC_EXCLUDED_NAMES:
            continue
        digest = hash_bytes(payload)
        for training_identity in train_hashes.get(digest, []):
            private = relative.startswith(("hidden/", "reference/"))
            add(
                _match(
                    stage="split_asset",
                    match_class="exact_file_content",
                    evidence_hash=digest,
                    training_identity=(
                        f"{training_identity.split(':', 1)[0]}:<private>"
                        if private
                        else training_identity
                    ),
                    heldout_identity=(f"{task_id}:<private>" if private else identity),
                    task_hash=heldout_entries[task_id].task_hash,
                    source_artifact_hash=digest,
                    normalized_token_count=max(1, len(_tokens(_decode(payload)))),
                    match_location_class=(
                        "exact_private_file_hash" if private else "exact_public_file_hash"
                    ),
                )
            )
    train_issues = {
        hash_bytes(b" ".join(payload.split()).lower()): identity
        for identity, payload in training_files.items()
        if identity.endswith(":issue.md")
    }
    for identity, payload in heldout_files.items():
        if not identity.endswith(":issue.md"):
            continue
        digest = hash_bytes(b" ".join(payload.split()).lower())
        if digest in train_issues:
            task_id = identity.split(":", 1)[0]
            add(
                _match(
                    stage="split_asset",
                    match_class="issue_text_duplication",
                    evidence_hash=digest,
                    training_identity=train_issues[digest],
                    heldout_identity=identity,
                    task_hash=heldout_entries[task_id].task_hash,
                    source_artifact_hash=hash_bytes(payload),
                    normalized_token_count=max(1, len(_tokens(_decode(payload)))),
                    match_location_class="normalized_public_issue",
                )
            )
    for match_class, selector in (
        (
            "reference_patch_fragment",
            lambda identity: (
                identity.endswith("/reference.patch") or identity.endswith(":reference.patch")
            ),
        ),
        ("hidden_test_fragment", lambda identity: ":hidden/" in identity),
        (
            "source_code_sequence",
            lambda identity: (
                (":repository/" in identity or ":public/" in identity)
                and identity.endswith((".sv", ".v"))
            ),
        ),
    ):
        train_shingles: dict[str, str] = {}
        for identity, payload in training_files.items():
            if selector(identity):
                for shingle in _line_shingles(payload, policy.source_fragment_min_lines):
                    train_shingles.setdefault(shingle, identity)
        for identity, payload in heldout_files.items():
            if not selector(identity):
                continue
            task_id = identity.split(":", 1)[0]
            for shingle in sorted(
                _line_shingles(payload, policy.source_fragment_min_lines) & train_shingles.keys()
            ):
                private = match_class in _PRIVATE_CLASSES
                add(
                    _match(
                        stage="split_asset",
                        match_class=match_class,
                        evidence_hash=shingle,
                        training_identity=(
                            f"{train_shingles[shingle].split(':', 1)[0]}:<private>"
                            if private
                            else train_shingles[shingle]
                        ),
                        heldout_identity=(f"{task_id}:<private>" if private else identity),
                        task_hash=heldout_entries[task_id].task_hash,
                        source_artifact_hash=hash_bytes(payload),
                        normalized_token_count=policy.source_fragment_min_lines,
                        match_location_class=match_class,
                    )
                )
    ordered = sorted(matches.values(), key=_match_sort_key)
    hard_count = len(ordered)
    base = {
        "schema_version": "1.0",
        "scan_id": f"{split_manifest.split_id}-split-assets",
        "split_manifest_hash": split_manifest.manifest_hash,
        "policy_hash": policy.policy_hash,
        "signature_manifest_hash": signature_manifest.manifest_hash,
        "matches": [match.model_dump(mode="json") for match in ordered],
        "hard_contamination_count": hard_count,
        "diagnostic_overlap_count": 0,
        "passed": hard_count == 0,
        "implementation_error": False,
        "hidden_assets_exported": False,
        "reference_assets_exported": False,
    }
    return SplitAssetContaminationScan.model_validate({**base, "scan_hash": content_hash(base)})


def validate_split_asset_scan(
    scan: SplitAssetContaminationScan,
) -> SplitAssetContaminationScan:
    payload = scan.model_dump(mode="json")
    expected = payload.pop("scan_hash")
    if content_hash(payload) != expected:
        raise ValueError("split contamination scan identity changed")
    return scan


def scan_frozen_memory_to_heldout(
    *,
    split_manifest: TaskSplitManifest,
    heldout_roots: Mapping[str, Path],
    memory_pack: MemoryPack,
    allowed_corpus: AllowedSynthesisCorpus,
    signature_manifest: AssetSignatureManifest,
    policy: ContaminationScanPolicy,
) -> FrozenMemoryContaminationScan:
    """Classify only typed provenance-bearing signatures as blocking memory leakage."""

    validate_task_split(split_manifest)
    validate_contamination_scan_policy(policy)
    validate_allowed_synthesis_corpus(allowed_corpus)
    validate_asset_signature_manifest(signature_manifest)
    if (
        allowed_corpus.policy_hash != policy.policy_hash
        or signature_manifest.split_manifest_hash != split_manifest.manifest_hash
        or signature_manifest.policy_hash != policy.policy_hash
        or signature_manifest.allowed_synthesis_corpus_hash != allowed_corpus.corpus_hash
    ):
        raise ValueError("memory scan inputs do not share one frozen contamination identity")
    signatures, heldout_files = _collect_heldout_signatures(
        split_manifest=split_manifest,
        heldout_roots=heldout_roots,
        allowed_corpus=allowed_corpus,
        policy=policy,
    )
    memory_text = "\n".join(item for section in memory_pack.sections for item in section.items)
    memory_casefold = memory_text.casefold()
    memory_tokens = _tokens(memory_text)
    memory_token_set = set(memory_tokens)
    memory_phrase_hashes = {
        digest
        for width in {
            policy.natural_language_min_tokens,
            policy.code_sequence_min_tokens,
        }
        for _, digest in _token_ngrams(memory_text, width)
    }
    memory_line_shingles = _line_shingles(
        memory_text.encode("utf-8"), policy.source_fragment_min_lines
    )
    matches: dict[tuple[str, str, str], ContaminationMatch] = {}

    def add(match: ContaminationMatch) -> None:
        matches[(match.match_class, match.heldout_identity, match.evidence_hash)] = match

    for signature in signatures:
        found = False
        if signature.match_class in {"exact_task_id", "repository_path"}:
            found = (
                signature.normalized_value is not None
                and signature.normalized_value in memory_casefold
            )
        elif signature.match_class == "distinctive_identifier":
            found = signature.normalized_value in memory_token_set
        elif signature.match_class in {"heldout_issue_phrase", "source_code_sequence"}:
            found = signature.signature_hash in memory_phrase_hashes
        elif signature.match_class in _PRIVATE_CLASSES:
            found = signature.signature_hash in memory_line_shingles
        if found:
            add(
                _match(
                    stage="frozen_memory_to_heldout",
                    match_class=signature.match_class,
                    evidence_hash=signature.signature_hash,
                    heldout_identity=signature.heldout_identity,
                    task_hash=signature.task_hash,
                    source_artifact_hash=signature.source_artifact_hash,
                    normalized_token_count=signature.normalized_token_count,
                    match_location_class=signature.match_location_class,
                    public_excerpt=(
                        signature.normalized_value[:160]
                        if signature.normalized_value is not None
                        and signature.match_class not in _PRIVATE_CLASSES
                        else None
                    ),
                    training_identity=memory_pack.memory_pack_id,
                )
            )
    public_heldout_tokens: set[str] = set()
    for identity, payload in heldout_files.items():
        relative = identity.split(":", 1)[1]
        if relative == "issue.md" or relative.startswith(_PUBLIC_TRAINING_PREFIXES):
            public_heldout_tokens.update(_tokens(_decode(payload)))
    allowed_tokens = set(allowed_corpus.normalized_tokens)
    for token in sorted(
        value
        for value in memory_token_set & public_heldout_tokens
        if len(value) >= 4 and value.isalpha()
    ):
        match_class = (
            "allowed_synthesis_vocabulary" if token in allowed_tokens else "generic_vocabulary"
        )
        add(
            _match(
                stage="frozen_memory_to_heldout",
                match_class=match_class,
                evidence_hash=hash_bytes(token.encode("utf-8")),
                heldout_identity="<public-heldout-vocabulary>",
                normalized_token_count=1,
                match_location_class="public_single_token_overlap",
                public_excerpt=token,
                training_identity=memory_pack.memory_pack_id,
            )
        )
    ordered = sorted(matches.values(), key=_match_sort_key)
    hard_count = sum(match.severity == "hard_contamination" for match in ordered)
    diagnostic_count = sum(match.severity == "diagnostic_overlap" for match in ordered)
    base = {
        "schema_version": "1.0",
        "scan_id": f"{split_manifest.split_id}-frozen-memory",
        "split_manifest_hash": split_manifest.manifest_hash,
        "policy_hash": policy.policy_hash,
        "allowed_synthesis_corpus_hash": allowed_corpus.corpus_hash,
        "signature_manifest_hash": signature_manifest.manifest_hash,
        "memory_pack_hash": memory_pack.content_hash,
        "matches": [match.model_dump(mode="json") for match in ordered],
        "hard_contamination_count": hard_count,
        "diagnostic_overlap_count": diagnostic_count,
        "passed": hard_count == 0,
        "implementation_error": False,
        "hidden_assets_exported": False,
        "reference_assets_exported": False,
    }
    return FrozenMemoryContaminationScan.model_validate({**base, "scan_hash": content_hash(base)})


def validate_frozen_memory_scan(
    scan: FrozenMemoryContaminationScan,
) -> FrozenMemoryContaminationScan:
    payload = scan.model_dump(mode="json")
    expected = payload.pop("scan_hash")
    if content_hash(payload) != expected:
        raise ValueError("frozen-memory contamination scan identity changed")
    return scan


def scan_contamination_report(
    *,
    split_manifest: TaskSplitManifest,
    training_roots: Mapping[str, Path],
    heldout_roots: Mapping[str, Path],
    allowed_corpus: AllowedSynthesisCorpus,
    policy: ContaminationScanPolicy,
    memory_pack: MemoryPack | None = None,
) -> tuple[ContaminationScanReport, AssetSignatureManifest]:
    """Run independent split-asset and optional frozen-memory stages."""

    signatures = build_asset_signature_manifest(
        split_manifest=split_manifest,
        training_roots=training_roots,
        heldout_roots=heldout_roots,
        allowed_corpus=allowed_corpus,
        policy=policy,
    )
    split_scan = scan_split_assets(
        split_manifest=split_manifest,
        training_roots=training_roots,
        heldout_roots=heldout_roots,
        signature_manifest=signatures,
        policy=policy,
    )
    memory_scan = (
        scan_frozen_memory_to_heldout(
            split_manifest=split_manifest,
            heldout_roots=heldout_roots,
            memory_pack=memory_pack,
            allowed_corpus=allowed_corpus,
            signature_manifest=signatures,
            policy=policy,
        )
        if memory_pack is not None
        else None
    )
    hard_count = split_scan.hard_contamination_count
    diagnostic_count = 0
    passed = split_scan.passed
    if memory_scan is not None:
        hard_count += memory_scan.hard_contamination_count
        diagnostic_count = memory_scan.diagnostic_overlap_count
        passed = passed and memory_scan.passed
    base = {
        "schema_version": "1.0",
        "report_id": f"{split_manifest.split_id}-contamination-report",
        "split_asset_scan": split_scan.model_dump(mode="json"),
        "frozen_memory_scan": (
            memory_scan.model_dump(mode="json") if memory_scan is not None else None
        ),
        "passed": passed,
        "hard_contamination_count": hard_count,
        "diagnostic_overlap_count": diagnostic_count,
    }
    report = ContaminationScanReport.model_validate({**base, "report_hash": content_hash(base)})
    return report, signatures


def validate_contamination_scan_report(
    report: ContaminationScanReport,
) -> ContaminationScanReport:
    validate_split_asset_scan(report.split_asset_scan)
    if report.frozen_memory_scan is not None:
        validate_frozen_memory_scan(report.frozen_memory_scan)
    payload = report.model_dump(mode="json")
    expected = payload.pop("report_hash")
    if content_hash(payload) != expected:
        raise ValueError("contamination report identity changed")
    return report


def _default_allowed_corpus(
    *,
    policy: ContaminationScanPolicy,
    training_roots: Mapping[str, Path],
) -> AllowedSynthesisCorpus:
    from verigym.evolution.memory_builder import memory_builder_allowed_synthesis_sources
    from verigym.schemas.evolution import RewardVector

    return build_allowed_synthesis_corpus(
        policy=policy,
        training_roots=training_roots,
        prompt_schema_texts=memory_builder_allowed_synthesis_sources(),
        sanitized_training_summary=None,
        reward_channel_names=tuple(RewardVector.model_fields),
        generic_policy_instructions={
            "bounded-memory-policy": (
                "Generalize task-independent public-test strategy, workspace policy, "
                "debugging checklists, and patch discipline from observable training outcomes."
            )
        },
    )


def scan_contamination(
    *,
    split_manifest: TaskSplitManifest,
    training_roots: Mapping[str, Path],
    heldout_roots: Mapping[str, Path],
    memory_pack: MemoryPack | None = None,
) -> ContaminationScan:
    """Backward-compatible hard-finding view over the provenance-aware two-stage scanner."""

    policy = build_contamination_scan_policy()
    allowed_corpus = _default_allowed_corpus(
        policy=policy,
        training_roots=training_roots,
    )
    report, signatures = scan_contamination_report(
        split_manifest=split_manifest,
        training_roots=training_roots,
        heldout_roots=heldout_roots,
        allowed_corpus=allowed_corpus,
        policy=policy,
        memory_pack=memory_pack,
    )
    category_map = {
        "task_identity_overlap": "task_id_overlap",
        "source_identity_overlap": "source_hash_overlap",
        "exact_file_content": "identical_file",
        "issue_text_duplication": "issue_text_overlap",
        "source_code_sequence": "identical_file",
        "hidden_test_fragment": "hidden_test_fragment",
        "reference_patch_fragment": "reference_fragment",
        "exact_task_id": "memory_heldout_token",
        "repository_path": "memory_heldout_token",
        "distinctive_identifier": "memory_heldout_token",
        "heldout_issue_phrase": "memory_heldout_token",
    }
    hard_matches = [
        match
        for match in (
            report.split_asset_scan.matches
            + (report.frozen_memory_scan.matches if report.frozen_memory_scan is not None else [])
        )
        if match.severity == "hard_contamination"
    ]
    findings = [
        ContaminationFinding(
            category=category_map[match.match_class],  # type: ignore[arg-type]
            training_identity=match.training_identity or "<memory>",
            heldout_identity=match.heldout_identity,
            evidence_hash=match.evidence_hash,
        )
        for match in hard_matches
    ]
    findings.sort(
        key=lambda item: (
            item.category,
            item.training_identity,
            item.heldout_identity,
            item.evidence_hash,
        )
    )
    base = {
        "schema_version": "1.0",
        "scan_id": f"{split_manifest.split_id}-contamination",
        "split_manifest_hash": split_manifest.manifest_hash,
        "memory_pack_hash": memory_pack.content_hash if memory_pack is not None else None,
        "findings": [item.model_dump(mode="json") for item in findings],
        "passed": not findings,
        "train_file_count": signatures.training_file_count,
        "heldout_file_count": signatures.heldout_file_count,
        "hidden_assets_exported": False,
        "reference_assets_exported": False,
    }
    return ContaminationScan.model_validate({**base, "scan_hash": content_hash(base)})


def validate_contamination_scan(scan: ContaminationScan) -> ContaminationScan:
    payload = scan.model_dump(mode="json")
    expected = payload.pop("scan_hash")
    if content_hash(payload) != expected:
        raise ValueError("contamination scan identity changed")
    return scan


__all__ = [
    "build_allowed_synthesis_corpus",
    "build_asset_signature_manifest",
    "build_contamination_scan_policy",
    "build_task_split",
    "scan_contamination",
    "scan_contamination_report",
    "scan_frozen_memory_to_heldout",
    "scan_split_assets",
    "validate_allowed_synthesis_corpus",
    "validate_asset_signature_manifest",
    "validate_contamination_scan",
    "validate_contamination_scan_policy",
    "validate_contamination_scan_report",
    "validate_frozen_memory_scan",
    "validate_split_asset_scan",
    "validate_task_split",
]

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from verigym.core.errors import ConfigurationError
from verigym.hwe.image_transfer import (
    ContentAddressedLayerCache,
    LayerCachePromotionError,
    LayerCacheValidationError,
    LayerTransferRetryPolicy,
    SingleCleanupArchive,
    redacted_transfer_failure,
    redacted_transfer_failure_v2,
    validate_registry_image_manifest,
)


def _staged(cache: ContentAddressedLayerCache, task: str, payload: bytes) -> tuple[Path, str]:
    staging = cache.task_staging(task)
    path = staging / "layer.part"
    path.write_bytes(payload)
    return path, "sha256:" + hashlib.sha256(payload).hexdigest()


def test_persistent_layer_cache_miss_then_hit_is_digest_bound(tmp_path: Path) -> None:
    cache = ContentAddressedLayerCache(tmp_path / "persistent-cache")
    first, digest = _staged(cache, "pr2728-first", b"layer-payload")

    miss = cache.commit(first, digest=digest, size=len(b"layer-payload"))
    second, _ = _staged(cache, "pr2728-second", b"layer-payload")
    hit = cache.commit(second, digest=digest, size=len(b"layer-payload"))

    assert miss.safe_dict() == {
        "digest": digest,
        "size": len(b"layer-payload"),
        "cache_hit": False,
    }
    assert hit.safe_dict()["cache_hit"] is True
    assert second.exists() is False
    assert cache.bounded_inventory([digest]) == [
        {"digest": digest, "size": len(b"layer-payload"), "cache_hit": True}
    ]


def test_registry_platform_manifest_freezes_ordered_digest_and_size_inventory() -> None:
    value = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {
            "mediaType": "application/vnd.oci.image.config.v1+json",
            "digest": "sha256:" + "1" * 64,
            "size": 41,
        },
        "layers": [
            {
                "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                "digest": "sha256:" + "2" * 64,
                "size": 101,
            },
            {
                "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                "digest": "sha256:" + "3" * 64,
                "size": 202,
            },
        ],
    }
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()

    manifest = validate_registry_image_manifest(raw + b"\n", expected_digest=digest)

    assert manifest.manifest_digest == digest
    assert manifest.manifest_size == len(raw)
    assert manifest.config.digest == "sha256:" + "1" * 64
    assert [(item.digest, item.size) for item in manifest.layers] == [
        ("sha256:" + "2" * 64, 101),
        ("sha256:" + "3" * 64, 202),
    ]


@pytest.mark.parametrize("mutation", ["digest", "index", "duplicate", "empty"])
def test_registry_platform_manifest_fails_closed_on_identity_or_shape_drift(
    mutation: str,
) -> None:
    value = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
        "config": {"digest": "sha256:" + "1" * 64, "size": 1},
        "layers": [{"digest": "sha256:" + "2" * 64, "size": 2}],
    }
    if mutation == "index":
        value["mediaType"] = "application/vnd.oci.image.index.v1+json"
    elif mutation == "duplicate":
        value["layers"].append(dict(value["layers"][0]))
    elif mutation == "empty":
        value["layers"] = []
    raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if mutation == "digest":
        digest = "sha256:" + "0" * 64

    with pytest.raises(ConfigurationError, match="manifest|layer"):
        validate_registry_image_manifest(raw, expected_digest=digest)


def test_layer_cache_rejects_digest_or_size_drift_before_publication(tmp_path: Path) -> None:
    cache = ContentAddressedLayerCache(tmp_path / "persistent-cache")
    staged, digest = _staged(cache, "pr2728-drift", b"payload")

    with pytest.raises(ConfigurationError, match="size"):
        cache.commit(staged, digest=digest, size=99)
    with pytest.raises(ConfigurationError, match="checksum"):
        cache.commit(staged, digest="sha256:" + "0" * 64, size=7)

    assert cache.bounded_inventory([digest])[0]["cache_hit"] is False


def test_crane_staging_is_promoted_then_seeded_without_writable_inode_sharing(
    tmp_path: Path,
) -> None:
    cache = ContentAddressedLayerCache(tmp_path / "persistent-cache")
    payload = b"crane-filesystem-cache-layer"
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    first_staging = cache.task_staging("pr2728-crane-first")
    (first_staging / digest).write_bytes(payload)

    promoted = cache.promote_task_staging(first_staging)

    assert [item.safe_dict() for item in promoted] == [
        {"digest": digest, "size": len(payload), "cache_hit": False}
    ]
    assert list(first_staging.iterdir()) == []

    second_staging = cache.task_staging("pr2728-crane-second")
    seeded = cache.seed_task_staging(second_staging)
    seeded_path = second_staging / digest

    assert [item.safe_dict() for item in seeded] == [
        {"digest": digest, "size": len(payload), "cache_hit": True}
    ]
    assert seeded_path.read_bytes() == payload
    assert seeded_path.stat().st_nlink == 1

    # crane opens its filesystem cache entries with truncation. Mutating the
    # task copy must never change the persistent content-addressed blob.
    seeded_path.write_bytes(b"partial-download")
    with pytest.raises(LayerCachePromotionError) as error:
        cache.promote_task_staging(second_staging)
    assert error.value.inventory == ()
    assert seeded_path.exists() is False
    assert cache.bounded_inventory([digest]) == [
        {"digest": digest, "size": len(payload), "cache_hit": True}
    ]

    third_staging = cache.task_staging("pr2728-crane-third")
    cache.seed_task_staging(third_staging)
    assert (third_staging / digest).read_bytes() == payload


def test_crane_staging_can_seed_only_the_manifest_requested_digests(tmp_path: Path) -> None:
    cache = ContentAddressedLayerCache(tmp_path / "persistent-cache")
    digests: list[str] = []
    for index, payload in enumerate((b"current-layer", b"unrelated-old-layer")):
        staging = cache.task_staging(f"seed-source-{index}")
        path = staging / "layer.part"
        path.write_bytes(payload)
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        cache.commit(path, digest=digest, size=len(payload))
        digests.append(digest)
    target = cache.task_staging("manifest-only")

    receipts = cache.seed_task_staging(target, digests=[digests[0]])

    assert [item.digest for item in receipts] == [digests[0]]
    assert (target / digests[0]).is_file()
    assert (target / digests[1]).exists() is False

    missing = cache.task_staging("missing-manifest-layer")
    with pytest.raises(ConfigurationError, match="missing"):
        cache.seed_task_staging(missing, digests=["sha256:" + "0" * 64])


def test_crane_promotion_commits_valid_layers_before_reporting_incomplete_layer(
    tmp_path: Path,
) -> None:
    cache = ContentAddressedLayerCache(tmp_path / "persistent-cache")
    staging = cache.task_staging("pr2728-mixed")
    valid_payload = b"complete-layer"
    valid_digest = "sha256:" + hashlib.sha256(valid_payload).hexdigest()
    invalid_digest = "sha256:" + "0" * 64
    (staging / valid_digest).write_bytes(valid_payload)
    (staging / invalid_digest).write_bytes(b"partial-layer")

    with pytest.raises(LayerCachePromotionError) as error:
        cache.promote_task_staging(staging)

    assert [item.safe_dict() for item in error.value.inventory] == [
        {"digest": valid_digest, "size": len(valid_payload), "cache_hit": False}
    ]
    assert list(staging.iterdir()) == []
    assert cache.bounded_inventory([valid_digest, invalid_digest]) == [
        {"digest": invalid_digest, "size": 0, "cache_hit": False},
        {"digest": valid_digest, "size": len(valid_payload), "cache_hit": True},
    ]
    failure = redacted_transfer_failure(
        error.value,
        raw_stderr=b"private crane stderr",
        stage="layer_promotion",
    )
    assert failure["error_family"] == "checksum"
    assert "private crane stderr" not in repr(failure)


def test_crane_staging_rejects_unknown_names_symlinks_and_foreign_directories(
    tmp_path: Path,
) -> None:
    cache = ContentAddressedLayerCache(tmp_path / "persistent-cache")
    unknown_staging = cache.task_staging("pr2728-unknown-name")
    (unknown_staging / "unexpected").write_bytes(b"layer")
    with pytest.raises(ConfigurationError, match="filename"):
        cache.promote_task_staging(unknown_staging)

    symlink_staging = cache.task_staging("pr2728-symlink")
    outside = tmp_path / "outside-layer"
    outside.write_bytes(b"layer")
    digest = "sha256:" + hashlib.sha256(b"layer").hexdigest()
    (symlink_staging / digest).symlink_to(outside)
    with pytest.raises(ConfigurationError, match="symlink"):
        cache.promote_task_staging(symlink_staging)

    foreign = tmp_path / "foreign-staging"
    foreign.mkdir()
    with pytest.raises(ConfigurationError, match="boundary"):
        cache.seed_task_staging(foreign)


def test_transfer_failure_persists_only_allowed_family_size_and_hash() -> None:
    raw = b"authorization=secret\nTLS certificate verify failed"
    receipt = redacted_transfer_failure(
        RuntimeError("private message"), raw_stderr=raw, stage="pull"
    )

    assert receipt["error_family"] == "tls"
    assert receipt["stderr_bytes"] == len(raw)
    assert receipt["stderr_sha256"] == hashlib.sha256(raw).hexdigest()
    assert receipt["raw_stderr_persisted"] is False
    assert "secret" not in repr(receipt)

    with pytest.raises(ConfigurationError, match="stage"):
        redacted_transfer_failure(RuntimeError("private"), raw_stderr=raw, stage="pull /secret")


@pytest.mark.parametrize(
    ("stderr", "family", "reason", "retryable", "status"),
    [
        (b"read: connection reset by peer", "transport", "connection_reset", True, None),
        (b"copy failed: unexpected EOF", "transport", "unexpected_eof", True, None),
        (b"request timeout", "timeout", "timeout", True, None),
        (b"HTTP status: 503", "http_status", "http_status", True, 503),
        (b"status code 404", "http_status", "http_status", False, 404),
        (b"x509 certificate signed by unknown authority", "tls", "tls", False, None),
        (b"credential=secret opaque failure", "unknown", "unknown", False, None),
    ],
)
def test_v2_transfer_diagnostics_bound_retryable_causes_without_raw_text(
    stderr: bytes,
    family: str,
    reason: str,
    retryable: bool,
    status: int | None,
) -> None:
    receipt = redacted_transfer_failure_v2(
        RuntimeError("private"),
        raw_stderr=stderr,
        stage="layer_015_attempt_01",
    )

    assert receipt["error_family"] == family
    assert receipt["reason"] == reason
    assert receipt["retryable"] is retryable
    assert receipt.get("http_status") == status
    assert receipt["stderr_bytes"] == len(stderr)
    assert receipt["stderr_sha256"] == hashlib.sha256(stderr).hexdigest()
    assert stderr.decode() not in repr(receipt)


def test_staged_validation_is_retryable_but_persistent_cache_drift_is_not(
    tmp_path: Path,
) -> None:
    cache = ContentAddressedLayerCache(tmp_path / "persistent-cache")
    staged, digest = _staged(cache, "retryable-size", b"partial")

    with pytest.raises(LayerCacheValidationError) as error:
        cache.commit(staged, digest=digest, size=99)

    receipt = redacted_transfer_failure_v2(
        error.value,
        raw_stderr=b"",
        stage="layer_000_attempt_01",
    )
    assert receipt["error_family"] == "checksum"
    assert receipt["reason"] == "staged_size_mismatch"
    assert receipt["retryable"] is True


def test_layer_transfer_retry_policy_is_tightly_bounded() -> None:
    assert LayerTransferRetryPolicy().maximum_attempts == 3
    assert LayerTransferRetryPolicy(1).maximum_attempts == 1
    for value in (0, 4, True):
        with pytest.raises(ConfigurationError, match="retry policy"):
            LayerTransferRetryPolicy(value)


def test_temporary_archive_has_exactly_one_cleanup_owner(tmp_path: Path) -> None:
    archive_path = tmp_path / "candidate.tar"
    owner = SingleCleanupArchive(archive_path)
    archive_path.write_bytes(b"tar")

    owner.cleanup()

    assert owner.cleanup_count == 1
    assert archive_path.exists() is False
    with pytest.raises(ConfigurationError, match="repeated"):
        owner.cleanup()

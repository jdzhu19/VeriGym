# OpenHands v27 resumed public qualification authorization

## Decision

This preregistration authorizes exactly one zero-model continuation under the new identity
`openhands-hwe-v27-resumed-public-qualification-v1`, and only after this authorization merges and
all repository checks pass. It does not retry or rewrite v26 or any earlier identity.

The exact predecessor is the audited v26 stop at commit
`f9d25e52724506b575b3f9d71f3aaae63be27df4`. Its progress file SHA-256 is
`751ad6ced84f445794bf3cf23ed300170f0dcdbd657789cf8340a1a891f411b5`, canonical progress hash is
`386941d45755c3c023c7a075b0ef0441437bdd823bc886ad33d7711a67006a76`, and terminal diagnostic
hash is `0b856e05a7b778fb264a65545c19d77b4f0805eab58889b346df2bc2b43a9327`.

The authorization receipt is
`configs/training/qwen35_hwe_openhands_v27_resumed_qualification_v1.json`; its hash is
`627d4debd68503ab879c2478d50d875871d00a88465f8d87086a90b825295626`.
The reviewed runner SHA-256 is
`cd95ea44f959eedd220cfe3f0ee32b639a27d2cc59c1073440349eac4722871f`.

## Evidence import and continuation

v27 verifies the entire sealed v26 progress file before importing anything. PR-2330 and PR-3226
must remain infrastructure-valid base-FAIL/reference-PASS outcomes, and their task, source, source
lock, verifier image, manifest, and transfer receipt bindings must agree exactly. Their two local
images must still match the recorded config identities. Imported evidence remains labelled as v26
evidence and is not rerun, reconstructed, or relabelled.

PR-2844 remains the terminal v26 transfer failure. v27 records a derived predecessor-failure marker
bound to the v26 progress and diagnostic hashes solely so capacity can be recomputed across the
frozen order. It does not create a verifier result for PR-2844. All three attempted tasks are
permanently skipped; the only executable continuation order is PR-3231, 2989, 1482, then 3059.

The two imported passes plus four unused candidates leave enough distinct capacity to reach five.
Each new candidate is transferred, imported, source-prepared, and zero-model qualified before the
next is touched. The runner stops immediately at five passes, before capacity becomes insufficient,
or on any current infrastructure or security error. Automatic retries remain zero.

## Upstream-informed diagnostic repair

The go-containerregistry project describes `crane pull` as
[`remote.Image -> tarball.Write`](https://github.com/google/go-containerregistry/tree/v0.22.0#overview),
and its pinned
[`pull` command](https://github.com/google/go-containerregistry/blob/v0.22.0/cmd/crane/doc/crane_pull.md)
also exposes a content-addressed layer cache. A nonzero exit can therefore originate at registry,
transport, cache filesystem, or tar writing boundaries. The project's transport documentation
shows that registry responses are checked as
[`structured errors`](https://github.com/google/go-containerregistry/blob/v0.22.0/pkg/v1/remote/transport/README.md),
while the historical tarball regression in
[`issue #2309`](https://github.com/google/go-containerregistry/issues/2309) demonstrates why a pull
failure must not automatically be called a registry failure. These references define the local
taxonomy boundary; they do not identify the discarded PR-2844 message after the fact.

v27 inspects bounded stderr only in memory and persists none of its text. It maps a failure to one
of ten fixed categories: registry HTTP 4xx/5xx, DNS, TLS, transport timeout/connection, cache
filesystem, archive writer, resource exhaustion, or unknown. Receipts retain only the category,
byte counts, stream hashes, exit state, and cleanup state. Any unmatched text becomes `unknown`;
classification never authorizes retry or changes failure semantics.

The non-root, non-privileged, read-only-root, cap-drop `ALL`, no-new-privileges, bounded-resource,
port-free, proxy-free, credential-free, Docker-socket-free controls remain unchanged. Candidate
transfer alone uses `verigym-hwe-net`; both verifier arms use `network=none`.

## Verification before authorization

- v27 regressions: `15 passed`; v25, v26, and v27 combined regressions: `25 passed`;
- OpenHands Python 3.12 credential-free suite: `287 passed`; strict mypy: `28 source files`;
- HWE credential-free suite: `39 passed`; strict mypy: `9 source files`;
- ordinary credential-free repository suite: `1035 passed`, `1 skipped`, `52 deselected`;
- v27 strict Python 3.12 mypy: `1 source file`; tracked-source Ruff, format, and root mypy
  checks: passed;
- exact authorization hash recomputation: passed;
- real read-only predecessor, dataset, inventory, image, network, execution-image, and tool-cache
  binding preflight: passed;
- real v27 `network=none` container control test: zero exit/output, new identity and control hash
  validated, temporary container and scratch removed;
- OpenHands wheel/sdist local build and package-content audit: passed; the local isolated build
  dependency fetch encountered a package-index proxy 502, so the successful local build reused the
  already compliant `setuptools 78.1.1`; Actions must recheck an isolated build;
- changed implementation/config/security scan: `5 files`, `137,709 bytes`, zero hard leaks and
  zero scanner errors; proxy values were neither persisted nor hashed; report hash
  `cf1bdca7b18a65ac47355c908c65907fef175cd0fed85e25e555204ae541c50c`;
- GitHub Actions package, reproducible-build, security, and ordinary checks remain the authoritative
  stage guard.

These are infrastructure and contract tests, not qualification or a benchmark result.

## Explicitly not authorized

This authorization permits only import of sealed public v26 evidence and one pass over never-used
public continuation candidates for zero-model base-FAIL/reference-PASS qualification. It does not
permit provider calls, agent-image construction, canary contract materialization, collection, SFT,
GPU work, adapter publication, or held-out access. The run must not start before this authorization
merges and may not be retried. Any result requires a separate sanitized audit.

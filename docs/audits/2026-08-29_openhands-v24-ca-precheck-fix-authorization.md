# OpenHands v24 daemonless CA-precheck fix authorization

## Decision

This preregistration authorizes one new no-candidate preflight under identity
`openhands-hwe-v24-daemonless-prewarm-preflight-v1`. It preserves the sealed v23 status
`stopped_security_or_infrastructure_invalid`, report hash
`ccdaf9ec9bce419a5d2ffa9fbfc2d0f8b9d6707d86a2609de90d3435e88dc966`, report-file SHA-256
`2a9a96ba39613427c78687a5326e94669834a647a182a6c14a15485cb6b0db27`, and audit commit
`ec0dd95459a9c5b443fedd8dd1666c9b7db3f011`. It does not retry, relabel, import, or reuse v23.

The authorization receipt is
`configs/training/qwen35_hwe_openhands_v24_daemonless_preflight_v1.json`; its authorization hash is
`53572cf1ced6bce6f3dccc6ce5d68f70c568bd57b8fed5ad63a0123d8d224990`.

## Root cause and upstream reference

v23 passed SLSA bootstrap and the registered version smoke, then its public registry digest command
exited 1 before returning stdout. A networkless inspection found that the exact Debian slim
execution image contained no `/etc/ssl/certs` directory or CA bundle. Go's official Linux
[`crypto/x509` source](https://go.dev/src/crypto/x509/root_linux.go) lists
`/etc/ssl/certs/ca-certificates.crt` and `/etc/ssl/certs` as Debian/Linux system-root inputs. The
CA-less image could not provide the ordinary TLS trust required by crane's registry client.

The already locked bootstrap image
`python@sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317` has a nonempty CA bundle;
an exact `/usr/bin/test -s /etc/ssl/certs/ca-certificates.crt` invocation passed under non-root,
read-only-root, `network=none` controls. v24 uses that same binding for both bootstrap and execution.
It introduces no new image or package download.

## Fail-early CA contract

After building and validating a new v24 tool cache, but before `crane version` or any registry
request, the runner starts a controlled container with:

- exact digest-locked CA-bearing execution image;
- exact path `/usr/bin/test` and argv `-s /etc/ssl/certs/ca-certificates.crt`;
- `network=none`, non-root user, read-only root, cap-drop `ALL`, no-new-privileges, private IPC/PID,
  bounded resources, no ports, no socket, and the same narrow read-only cache mount;
- exact image environment validation and zero expected stdout/stderr.

Any missing bundle, image/environment drift, output, nonzero exit, or cleanup failure stops before a
networked crane command. The final report records the CA path, pass bit, control hash, and
content-free command receipt. Authorization validation additionally requires the execution-image
binding to equal the bootstrap-image binding.

Runtime package installation, TLS disabling, `--insecure`, custom CA injection, credentials, proxy
forwarding, v23 cache reuse, candidate access, and fallback to the default Docker bridge are all
forbidden.

## Preserved inputs and controls

v24 retains v23's exact crane archive/checksum/Sigstore provenance, official `slsa-verifier`
v2.7.1, source/builder/workflow bindings, absolute verifier path, restricted subprocess `PATH`,
independent seven-byte CLI version binding, registered non-candidate digest, atomic receipts,
bounded diagnostics, and verified cleanup. It uses a distinct cache. The reviewed v24 helper
SHA-256 is `26979a11103afd81ac6e50d86127787cb61dad7fb4ffc0030a9ef2bf7f64bc69`.

## Verification before authorization

- v24 targeted regression: `8 passed`; combined v20 through v24 regressions: `35 passed`;
- v24 regression covers identical CA-bearing image bindings, networkless CA precheck receipt,
  independent version output, absolute verifier path, and no-candidate completion;
- v24 scripts strict mypy: `2 source files`; Ruff and diff checks: passed;
- ordinary credential-free repository suite: `1035 passed`, `1 skipped`, `52 deselected`;
- unchanged OpenHands Python 3.12 baseline: `262 passed`, strict mypy `28 source files`;
- unchanged HWE baseline: `37 passed`, strict mypy `9 source files`; core strict mypy:
  `206 source files`;
- documentation contracts: `2 passed`; exported schemas: no drift;
- core wheel and sdist were byte-identical across two builds; distribution audit: passed;
- changed implementation/config/security scan: `6 files`, `149,085 bytes`, zero hard leaks and
  zero scanner errors; report hash
  `8bbab025a5bc35ada08ac09e67a16637de3d9701c0e4a77cdf74c64a954f0554`.

These checks are implementation evidence only, not candidate qualification or a benchmark result.
All repository, integration, Docker-security, OpenHands-package, packaging, and reproducible-build
Actions remain merge gates.

## Explicitly not authorized

This authorization permits only one new v24 no-candidate preflight after merge. It does not permit
candidate download/load, qualification, provider calls, reserve assignment, collection, SFT, GPU
work, or held-out access. v24 may not be retried. Passing still requires a separate audited
candidate-transfer authorization.

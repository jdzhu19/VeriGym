# OpenHands v24 daemonless prewarm preflight passed

## Result

The independently authorized no-candidate preflight
`openhands-hwe-v24-daemonless-prewarm-preflight-v1` ran exactly once after authorization PR #24
merged at commit `9b9d9fe79c72f2c39fe67f2ec8eb93db9b1acce7`. It completed with status
`preflight_passed`. The sealed report hash is
`71e315de5eda2fb7bd3bbc2fb4f6b38405b33a47a028bc22191eaa5f306a1b35`; the report file SHA-256 is
`569e9d62b71632d2e80cea09152e0cc6debb3085d18698fc00f0bb17e30949c0` over 5,063 bytes.

This result belongs only to authorization hash
`53572cf1ced6bce6f3dccc6ce5d68f70c568bd57b8fed5ad63a0123d8d224990`. Recomputing the canonical
JSON content hash after removing `report_hash` reproduced the sealed report hash. The run preserved
v23's stopped status and report hash; it did not retry, relabel, import, or reuse v23.

## Repaired boundary

v24 completed the SLSA-verified bootstrap through all atomic stages. The bootstrap progress hash is
`1ae3817dc084d06330dac5402ac8c64c8a5d27f33c8e5bea338eeb4e719cd8f6`, the bootstrap control hash
is `45b295811b4bb72743278828c0559d6a3e6bcf39c1f9449789b55c5b4b1e5c6b`, and the extracted crane
binary remained SHA-256 `771ced475a87b8b2314b9f9de267264789b3297f34a6d5d8ab601e8482db4d94`.

Before either crane command, the exact networkless CA-bundle precheck exited zero with zero stdout
and zero stderr. It verified a nonempty `/etc/ssl/certs/ca-certificates.crt` in the frozen execution
image and recorded control hash
`9358c95d07d73c1907da946dd270ba90a546d8c1d4d708f229c9899f4918be7c`. Go's official Linux
[`crypto/x509` source](https://go.dev/src/crypto/x509/root_linux.go) lists that file and the Debian
certificate directory as system trust inputs. This is the upstream-backed prerequisite that was
absent from v23's execution image.

The independent `crane version` receipt exited zero with seven stdout bytes, zero stderr bytes, and
registered stdout SHA-256
`464863ee696ca862f6ae2bfee9728ebbd84463597825442efc62838d945b00fb`. The release tag remained
`v0.22.0`; crane's own
[`version` documentation](https://github.com/google/go-containerregistry/blob/v0.22.0/cmd/crane/doc/crane_version.md)
warns that build-dependent output formats should not be assumed, which is why v24 retained v23's
independent exact-output binding.

The final registered public registry probe then exited zero with 72 stdout bytes, zero stderr bytes,
and returned the expected manifest digest
`sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317`. This proves that the CA
precondition repair restored the bounded registry path. It does not qualify any benchmark task.

## Security and scope invariants

- release assets downloaded: `4`; registry probes: `1`;
- candidate downloads authorized or started: `false`;
- candidate images imported or present: `0` across all seven frozen public references;
- qualification started: `false`;
- provider calls: `0`;
- held-out task IDs loaded: none;
- Docker socket mounted, privileged containers, or TCP API listener used: `false`;
- all four command receipts recorded zero exit status and verified temporary-container cleanup;
- remaining v24 temporary containers: `0`;
- promoted v24 public tool cache present: `true`, with eight registered regular files.

The one-file result passed the context-aware artifact scan over 5,063 bytes with zero hard leaks and
zero scanner errors. Proxy values were neither persisted nor hashed. Three diagnostic-only security
vocabulary findings were expected from the content-free control fields and did not affect the gate.
The scan report hash is
`0e1c3ad14499bda29ffc21312b9dfd629a469431bb2b66288e288957afec330c`.

## Decision

The v24 CA-precheck repair is accepted as effective, and the daemonless public-tool preflight is
sealed as passed. This removes the known bootstrap/version/TLS prerequisite failures before task
transfer and avoids spending candidate-transfer or provider budget on those defects.

This audit authorizes no candidate download or load by itself. Candidate qualification, provider
canary, collection, SFT, GPU work, and held-out evaluation remain unstarted. The next stage requires
a separate preregistered candidate-transfer and zero-model qualification authorization with the
frozen seven-task order, explicit `verigym-hwe-net` transfer, digest-locked `--network none`
verification, atomic progress, and immediate stop on infrastructure-invalid outcomes.

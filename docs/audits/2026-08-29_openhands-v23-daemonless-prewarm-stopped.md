# OpenHands v23 daemonless prewarm preflight stopped

## Result

The independently authorized no-candidate preflight
`openhands-hwe-v23-daemonless-prewarm-preflight-v1` ran once after authorization PR #22 merged at
commit `bec9578317dde9ad55c9e1bd077a29b00740678c`. It stopped fail closed with status
`stopped_security_or_infrastructure_invalid` and will not be retried. The sealed report hash is
`ccdaf9ec9bce419a5d2ffa9fbfc2d0f8b9d6707d86a2609de90d3435e88dc966`; the report file SHA-256 is
`2a9a96ba39613427c78687a5326e94669834a647a182a6c14a15485cb6b0db27` over 1,916 bytes.

This result belongs only to authorization hash
`aa9b8bdc9c00a0c7eeb0bd39bc4febe4ea681b2a16d034f11d16c3359347bdc3`. It preserves all sealed
predecessors and does not retry, reconstruct, or relabel them.

## Passed repair boundary

v23 completed the SLSA-verified bootstrap through all nine atomic stages. The verifier exited zero;
the bootstrap progress hash is
`5be6ac868d8b687c84b948478c3c9deb4e1c810cb4b28249a7f3f0522946eb62`, and the final receipt hash is
`7f68137917d8a1431a0b0bcfe6d784e91453d6b26f59ffbdb430490ed57588a4`. The extracted crane binary
remained SHA-256 `771ced475a87b8b2314b9f9de267264789b3297f34a6d5d8ab601e8482db4d94`.

The networkless `crane version` stage also passed its independently registered seven-byte output.
The failure occurred only after the runner advanced to the final registered public digest probe.
This proves the v23 tag/output repair and preserves v22's verifier-path repair.

## Exact new failure boundary

The controlled `crane-digest-probe` container returned exit code 1, zero stdout bytes, and 301
bounded stderr bytes on `verigym-hwe-net`. Its cleanup receipt recorded
`temporary_container_removed=true`. The command failed before any manifest digest could be checked;
it was not a digest mismatch.

A separate `network=none`, read-only inspection of the exact execution image
`debian@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241` found neither
`/etc/ssl/certs/ca-certificates.crt` nor `/etc/ssl/certs`. Go's official Linux
[`crypto/x509` root loader](https://go.dev/src/crypto/x509/root_linux.go) lists the Debian CA bundle
at that path and the certificate directory as its system trust inputs. The execution image therefore
could not establish ordinary registry TLS trust. This is an execution-image prerequisite defect,
not a registry digest, SLSA, candidate, or provider failure.

The already digest-locked bootstrap image
`python@sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317` contains a nonempty Debian
CA bundle, and an exact `/usr/bin/test -s /etc/ssl/certs/ca-certificates.crt` command passes under
`network=none`, non-root, read-only-root controls. The official Python slim
[`Dockerfile`](https://github.com/docker-library/python/blob/master/3.14/slim-bookworm/Dockerfile)
likewise installs `ca-certificates`; the exact local digest inspection remains the binding evidence
for the older frozen image used here.

## Post-stop invariants

- candidate downloads authorized or started: `false`
- candidate images imported or present: `0`
- qualification started: `false`
- provider calls: `0`
- held-out task IDs loaded: none
- promoted v23 public tool cache present: `true`, with eight registered regular files
- remaining v23 temporary containers: `0`

The one-file result passed the context-aware artifact scan over 1,916 bytes with zero hard leaks and
zero scanner errors. Its scan report hash is
`5847574c56363d723c2d4129f58405c2cf97b49da23a7c8794b02caf44d0634e`.

## Decision

This audit authorizes no retry or successor. Candidate transfer, qualification, provider canary,
collection, SFT, GPU work, and held-out evaluation remain unauthorized and unstarted. The v23 cache
remains external evidence and must not be reused.

A v24 successor requires a distinct identity and new cache. It may replace the CA-less execution
image only with the already digest-locked CA-bearing bootstrap image. Before either crane command,
it must run the exact `/usr/bin/test -s /etc/ssl/certs/ca-certificates.crt` precheck with
`network=none` and persist a content-free receipt. It must not disable TLS, use `--insecure`, install
packages at runtime, add credentials, or relax existing container controls. The full merge gate must
pass before one new no-candidate preflight.

# OpenHands v26 streamed public qualification stopped

## Result

The one authorized run of `openhands-hwe-v26-streamed-public-qualification-v1` stopped fail closed
during the third candidate transfer. It is not eligible for retry, provider canary, collection,
training, or a benchmark claim. The authorization merged as PR #28 at commit
`74e0ceb774e024209ef54f4aa6ed8a2fa0e3bd07` after all 16 push/PR checks passed.

The result is frozen outside Git at
`/data/jzhu484/Agent/experiments/openhands-hwe-v26-streamed-public-qualification-v1`. Its sealed
`qualification-progress.json` is 15,575 bytes with SHA-256
`751ad6ced84f445794bf3cf23ed300170f0dcdbd657789cf8340a1a891f411b5`. The canonical progress
hash is `386941d45755c3c023c7a075b0ef0441437bdd823bc886ad33d7711a67006a76` and recomputes exactly.

## Qualified evidence preserved

The streamed transfer and immediate zero-model qualification path worked for its first two public
candidates. Both PR-2330 and PR-3226 produced infrastructure-valid base-FAIL/reference-PASS
outcomes under the digest-bound verifier images with verifier networking disabled. They are frozen
as qualified evidence inside this v26 result, but v26 did not reach the required five-task split and
therefore did not create training or validation reserves.

- PR-2330: task hash
  `c0ce40d1c733daf1f48ab7c4f357839b7738ac3174c318ba77697ffc70032fba`, source hash
  `b2682457ca342f6548850c2e83d1a7eea60bff7dec99f168eb6b9a75c9054c7b`, transfer receipt
  `3e3a0ad21941fee44de8deb91aeb2833ecdb33eb94bd893af46eedd16621779a`;
- PR-3226: task hash
  `47cd8b6b6964b337751528bd7479dc9fb8e7f18cbdef1bf605bd70acd6e70fad`, source hash
  `b6a03041571bfbd70cbea308f358747efce9001685f1104ff411306e51bbafa9`, transfer receipt
  `b3a3f33782c67022f7b3231d772a358cf2151a262850f3e2ff28e17303db3c21`.

Their successful pull receipts recorded zero stdout and bounded stderr of 2,224 and 2,042 bytes.
The independently checked tar inventory, config digest, Docker-loaded image ID, manifest digest,
source lock, and zero-model verifier results all passed. No model process was started, provider
calls remained zero, and no held-out task ID was loaded.

## Exact stop boundary

The PR-2844 candidate-pull container was created successfully and then exited 1. Its content-free
failure receipt recorded zero stdout, 2,157 stderr bytes, the stderr SHA-256
`4436c6d3ce3d869dfe46317ade6f350b8da0f79c12c0dc744128594ffe9d1e78`, and successful temporary
container removal. No transfer receipt, source preparation, image import, or verifier outcome was
created for PR-2844. This is an infrastructure stop, not a verifier rejection.

v26 deliberately discarded raw stderr after recording only its bound and digest. That prevented
secret persistence, but it also prevents this audit from distinguishing a registry response,
transport interruption, cache failure, or tar writer error. The pinned go-containerregistry
[`crane pull` documentation](https://github.com/google/go-containerregistry/blob/v0.22.0/cmd/crane/doc/crane_pull.md)
exposes a verbose diagnostic mode and a layer cache, while the project describes `crane pull` as
the composition `remote.Image -> tarball.Write` in its
[`README`](https://github.com/google/go-containerregistry/tree/v0.22.0#overview). A failed exit can
therefore arise on more than one boundary and must not be relabelled from exit status alone.

A later identity may retain only an allowlisted, redacted error classification such as registry
HTTP status family, DNS/TLS/transport, cache filesystem, tar writer, timeout, or unknown. It must
continue to discard raw output, preserve its hash and byte count, fail closed without automatic
retry, and continue only from candidates never attempted by v26. It may import the two sealed v26
qualified bindings only after verifying the complete predecessor hash and binding receipts. This
audit does not authorize that successor or another network run.

## Cleanup and security scan

After the stop, transfer scratch and all v26 temporary containers were absent. Exactly the two
successfully imported candidate images remained as external evidence; no PR-2844 candidate image
or sentinel tag was retained.

The export-eligible progress file passed the context-aware artifact scan over 15,575 bytes with
zero hard secret leaks and zero scanner errors. Proxy values were neither persisted nor hashed. The
scan report hash is `d9a3b3bc95cdc8d88c332efbc0e98c71f38753775cb04eb4b23bd055d4e8d150`.

No dataset, candidate source, image, cache, tarball, verifier workspace, credential, proxy value,
raw diagnostic, or full experiment artifact is committed by this audit.

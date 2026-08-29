# OpenHands v25 streamed public qualification stopped

## Result

The one authorized run of `openhands-hwe-v25-streamed-public-qualification-v1` stopped fail closed
during the first candidate transfer. It is not eligible for retry, provider canary, collection,
training, or a benchmark claim. The authorization merged as PR #26 at commit
`4312773d91dbba825a10c27df008dab8879d3799` after all 16 push/PR checks passed.

The result is frozen outside Git at
`/data/jzhu484/Agent/experiments/openhands-hwe-v25-streamed-public-qualification-v1`. Its only file,
`qualification-progress.json`, is 4,214 bytes with SHA-256
`90a7d04a3cb16863b366757584859dfb7ae96c52bccef316a02573ef58a22594`. The canonical progress
hash is `f3fa6795b0db0e7592dc168d9dd15d842f80945c1df06fa969b14a3642be916b` and recomputes exactly.

## Observed boundary

- status: `stopped_security_or_infrastructure_invalid`;
- active transfer: public PR-2330; completed transfers and qualification outcomes: zero;
- qualified tasks, model processes, provider calls, and held-out tasks loaded: zero;
- transfer scratch removed, temporary containers removed, and host candidate images present: zero;
- the source preparer, Docker image load, and both zero-model verifier arms were never entered.

The controlled `crane pull` command returned successfully within its time and output bounds and
created the candidate tarball, but v25 then rejected it because stdout or stderr was nonempty. The
v25 stop receipt intentionally retained no diagnostic content and the scratch was removed, so this
audit does not infer which stream or message caused the rejection.

## Upstream-informed diagnosis

The pinned go-containerregistry v0.22.0
[`pull` command](https://github.com/google/go-containerregistry/blob/v0.22.0/cmd/crane/cmd/pull.go)
returns after `MultiSave` and defines no semantic stdout payload. The pinned
[`MultiSave` implementation](https://github.com/google/go-containerregistry/blob/v0.22.0/pkg/crane/pull.go)
also delegates the download and tar write to the registry/cache/tarball libraries. Neither source
defines empty stderr as an image-integrity condition. v25 nevertheless required both empty stdout
and empty stderr after an otherwise successful, bounded command. That local policy converted a
recoverable diagnostic-output condition into an infrastructure stop after downloading the large
first image.

A later identity may allow bounded stderr from a zero-exit pull, retain only byte count and digest,
continue to require empty stdout, and rely on the independently checked tar inventory, remote
config digest, Docker-loaded image ID, and manifest digest for integrity. It must also persist the
content-free pull receipt before any output-policy decision so another stop remains diagnosable.
This audit does not authorize that identity or another network run.

## Security scan

The single result file passed the context-aware artifact scan over 4,214 bytes with zero hard
secret leaks and zero scanner errors. Proxy values were neither persisted nor hashed. The scan
report hash is `26febefa88a6942f9d7ff9463bbda9dfe35ab70828bea6e0220138a89320ff98`.

No dataset, image, cache, tarball, task source, verifier output, credential, proxy value, or full
experiment artifact is committed by this audit.

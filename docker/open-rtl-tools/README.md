# VeriGym open RTL tools reference image

This explicit multi-stage image builds the official Yosys `v0.67` release asset,
its vendored ABC source, and Icarus Verilog `v12_0`. The Yosys download is checked
against the SHA-256 published by the GitHub release API; Icarus is fetched by its
exact peeled commit. See `SOURCE_IDENTITIES` for the recorded inputs.

For the verified build, the v0.67 tag peels to
`2d1509d1bcb8df0723f6790057e3b1d21c876683`; the official release archive records
the vendored build source as `b8e7da6f40ae8f552c116bf6c359b07c6533e159` and
ABC as `e026ed5380f3bdc3beea2ff9ffc23236fc549d5b`. The final executable reports the
archive identity, so that is the git identity required by the built-in profile.

Build only by explicit user action from the repository root:

```bash
docker build \
  -f docker/open-rtl-tools/Dockerfile \
  -t verigym/open-rtl-tools:iverilog12-yosys067 \
  docker/open-rtl-tools
```

`verigym run` never builds this image and does not pull it under the default
policy. The tag is only a requested reference. DockerRuntime records Docker's
actual immutable image ID, actual `yosys -V`, ABC version text, Icarus versions,
platform, and effective UID/GID. It never manufactures a repository digest when
Docker reports none.

The runtime user is the fixed non-root UID/GID `10001:10001`. All Milestone 7
network, read-only-root, capability, no-new-privileges, filesystem, resource,
environment, artifact, and cleanup controls remain runtime-enforced.

## Verified acceptance build

The local acceptance build completed on 2026-07-22 with:

```text
image ID: sha256:77aa99d8afc4143f6168f749075a20f387f46d38080f228b7e7ff8e85fcbeaa6
repository digests reported by Docker: none
platform/user: linux/amd64, 10001:10001
Yosys: 0.67+post, git sha1 b8e7da6f40ae8f552c116bf6c359b07c6533e159
ABC: 1.01 (vendored source e026ed5380f3bdc3beea2ff9ffc23236fc549d5b)
Icarus/VVP: 12.0 (source 4fd5291632232fbe1ba49b2c26bb6b2bf1c6c9cf)
```

This image ID is evidence for that exact local build, not a fabricated registry digest and not a
promise that rebuilding will produce the same layer ID. VeriGym resolves every supplied tag and
records the actual image ID again for each run.

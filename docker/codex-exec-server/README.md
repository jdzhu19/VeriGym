# Codex exec-server agent image

This image contains only the exact native Codex CLI 0.144.6 binary and a
digest-pinned Debian base. It intentionally contains no `~/.codex`, `auth.json`,
provider token, proxy setting, task, verifier asset, or Docker socket.

Build it through the repository helper, which verifies the native binary before
creating a two-file temporary build context:

```bash
scripts/build_codex_agent_image.sh \
  /absolute/path/to/codex \
  verigym/codex-exec-server:0.144.6
```

VeriGym starts the image by immutable image ID with a numeric non-root user,
network disabled, a read-only root filesystem, bounded `/tmp`, and `/workspace`
as the sole task mount. The process is `codex exec-server --listen stdio://`;
authentication and provider transport remain in the host control plane.

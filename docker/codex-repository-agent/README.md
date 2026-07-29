# Codex repository-agent image

This credential-free image extends the separately built Icarus Verilog 12
runtime with the exact native Codex CLI 0.144.6 exec-server and the trusted
`verigym-public-test` launcher. It contains no Codex home, authentication
files, provider tokens, proxy values, task repositories, public test assets,
hidden verifier assets, host paths, or Docker socket.

Build it only through:

```bash
scripts/build_codex_repository_agent_image.sh \
  /absolute/path/to/codex \
  verigym/rtl-iverilog:12.0 \
  verigym/codex-repository-agent:0.144.6
```

The image defaults to numeric user `10001:10001`; each run binds the exact
declared non-root user identity and records the effective UID/GID. The runtime
starts the resulting immutable image ID with network disabled and a read-only
root filesystem. The visible task workspace is the only writable bind mount;
`/verigym-public` is a separate runtime-staged read-only mount.

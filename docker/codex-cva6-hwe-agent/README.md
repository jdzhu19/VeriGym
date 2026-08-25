# CVA6 HWE native-shell agent image

This Dockerfile is built only from an already-local, digest-locked official CVA6 verifier image.
The build runs with `--network none`, whiteouts `/home/cva6`, and injects exactly the hash-checked
native Codex CLI 0.147.0 exec-server and its bundled static `rg`. At runtime,
`/workspace/repository` is the only persistent task mount; the image root is read-only and
`/tmp` is a bounded ephemeral tmpfs. The v2 shell may read ordinary paths in this isolated
container, while only workspace changes can become the candidate. The host app-server retains
provider authentication. The build input must be the platform-native ELF, not the npm launcher
symlink.

Use `scripts/build_cva6_hwe_agent_image.sh` with a task-keyed pre-lock. The emitted JSON contains
the resolved derived image ID and must be completed and sealed as a
`verigym_hwe_agent_image_lock_v2` before current collection. Explicit v1 locks remain valid only
for legacy `hwe_standard_v1` replay and cannot be substituted into a v2 campaign.

# Local Codex Verilator repository-agent image

This local-only image extends the public Verilator 5.052 + Icarus 12 tool image with the exact
native Codex CLI 0.147.0 exec-server and trusted `verigym-public-test` launcher. The build context
must contain only those two executables. It contains no Codex home, authentication file, provider
token, proxy value, dataset, task workspace, hidden verifier asset, or Docker socket.

Build it only through `scripts/build_codex_repository_agent_verilator_image.sh`, passing the
package's native `x86_64-unknown-linux-musl/bin/codex` ELF rather than the npm JavaScript launcher.
The recipe separately freezes the host launcher SHA-256 used by the campaign and the native
container executable SHA-256. Do not publish the resulting image: the public base image and
reproducible recipes belong in GHCR/GitHub, while this Codex-bearing composition remains a locally
attested runtime identity.

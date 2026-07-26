FROM debian:trixie-slim@sha256:020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd

# Keep these discovery-stage instructions stable so an already verified native
# binary layer can be reused without copying authentication or package-manager state.
LABEL org.opencontainers.image.title="VeriGym Codex remote execution environment"
LABEL org.opencontainers.image.version="0.144.6-discovery"
LABEL org.verigym.codex.version="0.144.6"
LABEL org.verigym.codex.native.sha256="a31ae9450a26216eb1e7c53102fd42123dd675974310b0e2ca3aa4cb622a2c15"
LABEL org.verigym.credential_material="absent"

COPY --chown=10001:10001 codex /usr/local/bin/codex

LABEL org.opencontainers.image.version="0.144.6"
LABEL org.verigym.codex.binary.sha256="a31ae9450a26216eb1e7c53102fd42123dd675974310b0e2ca3aa4cb622a2c15"
LABEL org.verigym.external_agent.protocol="codex_app_server_remote_environment_v1"
LABEL org.verigym.provider_credentials="absent"

ENV PATH=/usr/local/bin:/usr/bin:/bin

WORKDIR /workspace
USER 10001:10001

CMD ["codex", "exec-server", "--listen", "stdio://"]

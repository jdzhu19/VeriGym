ARG RTL_BASE
FROM ${RTL_BASE}

ARG CODEX_SHA256
ARG LAUNCHER_SHA256
ARG RTL_BASE_ID

LABEL org.opencontainers.image.title="VeriGym Codex Verilator repository agent"
LABEL org.opencontainers.image.version="0.147.0-verilator-public-v1"
LABEL org.verigym.runtime.role="repository-agent"
LABEL org.verigym.codex.version="0.147.0"
LABEL org.verigym.codex.binary.sha256="${CODEX_SHA256}"
LABEL org.verigym.external_agent.protocol="codex_app_server_remote_environment_v1"
LABEL org.verigym.public_test.protocol="verigym_public_test_v1"
LABEL org.verigym.public_test_launcher.sha256="${LAUNCHER_SHA256}"
LABEL org.verigym.iverilog.version="12.0"
LABEL org.verigym.verilator.version="5.052"
LABEL org.verigym.rtl.base_image_id="${RTL_BASE_ID}"
LABEL org.verigym.provider_credentials="absent"
LABEL org.verigym.credential_material="absent"

USER root

COPY --chown=10001:10001 codex /usr/local/bin/codex
COPY --chown=10001:10001 verigym-public-test /usr/local/bin/verigym-public-test

ENV PATH=/opt/verilator/bin:/opt/iverilog/bin:/usr/local/bin:/usr/bin:/bin

WORKDIR /workspace
USER 10001:10001

CMD ["codex", "exec-server", "--listen", "stdio://"]

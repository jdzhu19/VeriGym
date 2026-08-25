ARG CVA6_VERIFIER_BASE
FROM ${CVA6_VERIFIER_BASE}

ARG CODEX_SHA256
ARG RG_SHA256
ARG CVA6_VERIFIER_BASE_ID
ARG HWE_TASK_ID
ARG AGENT_UID
ARG AGENT_GID

LABEL org.opencontainers.image.title="VeriGym CVA6 HWE native-shell agent"
LABEL org.opencontainers.image.version="0.147.0-hwe-native-shell-v2"
LABEL org.verigym.runtime.role="hwe-cva6-agent"
LABEL org.verigym.collection.profile="hwe_standard_v2"
LABEL org.verigym.tool.contract="hwe_native_shell_v2"
LABEL org.verigym.codex.version="0.147.0"
LABEL org.verigym.codex.binary.sha256="${CODEX_SHA256}"
LABEL org.verigym.codex.rg.sha256="${RG_SHA256}"
LABEL org.verigym.hwe.task_id="${HWE_TASK_ID}"
LABEL org.verigym.cva6.verifier_base_image_id="${CVA6_VERIFIER_BASE_ID}"
LABEL org.verigym.cva6.source_whiteout="/home/cva6"
LABEL org.verigym.provider_credentials="absent"
LABEL org.verigym.hidden_assets="absent"
LABEL org.verigym.reference_patch="absent"
LABEL org.verigym.verifier_payload="absent"

USER root

# A layer whiteout makes the official source checkout unavailable in the runtime view.  The sole
# source presented to an episode is the private host staging mount at /workspace/repository.
RUN rm -rf /home/cva6 /home/cva6_base_commit.txt \
    && mkdir -p /workspace/repository \
    && chown -R ${AGENT_UID}:${AGENT_GID} /workspace

COPY --chown=${AGENT_UID}:${AGENT_GID} codex /usr/local/lib/codex/bin/codex
COPY --chown=${AGENT_UID}:${AGENT_GID} rg /usr/local/lib/codex/codex-path/rg

RUN ln -s /usr/local/lib/codex/bin/codex /usr/local/bin/codex \
    && ln -s /usr/local/lib/codex/codex-path/rg /usr/local/bin/rg

ENV PATH=/usr/local/bin:/tools/verilator/bin:/opt/micromamba/envs/cva6/bin:/usr/bin:/bin
WORKDIR /workspace/repository
USER ${AGENT_UID}:${AGENT_GID}

CMD ["codex", "exec-server", "--listen", "stdio://"]

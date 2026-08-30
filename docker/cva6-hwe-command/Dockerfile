ARG CVA6_VERIFIER_BASE
FROM ${CVA6_VERIFIER_BASE}

ARG RG_SHA256
ARG RG_RELEASE_ARCHIVE_SHA256
ARG CVA6_VERIFIER_BASE_ID
ARG HWE_TASK_ID
ARG COMMAND_UID
ARG COMMAND_GID

LABEL org.opencontainers.image.title="VeriGym CVA6 HWE command image"
LABEL org.opencontainers.image.version="15.2.0-hwe-command-v1"
LABEL org.verigym.runtime.role="hwe-cva6-command"
LABEL org.verigym.collection.profile="hwe_standard_v2"
LABEL org.verigym.tool.contract="hwe_native_shell_v2"
LABEL org.verigym.command.protocol="hwe_command_image_v1"
LABEL org.verigym.command.rg.version="ripgrep 15.2.0 (rev e89fff89ac)"
LABEL org.verigym.command.rg.sha256="${RG_SHA256}"
LABEL org.verigym.command.rg.release_archive.sha256="${RG_RELEASE_ARCHIVE_SHA256}"
LABEL org.verigym.hwe.task_id="${HWE_TASK_ID}"
LABEL org.verigym.cva6.verifier_base_image_id="${CVA6_VERIFIER_BASE_ID}"
LABEL org.verigym.cva6.source_whiteout="/home/cva6"
LABEL org.verigym.codex.present="absent"
LABEL org.verigym.provider_credentials="absent"
LABEL org.verigym.hidden_assets="absent"
LABEL org.verigym.reference_patch="absent"
LABEL org.verigym.verifier_payload="absent"

USER root

# The task source is supplied only through the private episode workspace mount. The command image
# contains the verifier toolchain plus a separately downloaded, hash-bound ripgrep release binary.
RUN rm -rf /home/cva6 /home/cva6_base_commit.txt \
    && mkdir -p /workspace/repository /usr/local/lib/verigym-command-tools \
    && chown -R ${COMMAND_UID}:${COMMAND_GID} /workspace \
    && test -x /usr/bin/tail

COPY --chown=${COMMAND_UID}:${COMMAND_GID} rg /usr/local/lib/verigym-command-tools/rg

RUN ln -s /usr/local/lib/verigym-command-tools/rg /usr/local/bin/rg

ENV PATH=/usr/local/bin:/tools/verilator/bin:/opt/micromamba/envs/cva6/bin:/usr/bin:/bin
WORKDIR /workspace/repository
USER ${COMMAND_UID}:${COMMAND_GID}

CMD ["/usr/bin/tail", "-f", "/dev/null"]

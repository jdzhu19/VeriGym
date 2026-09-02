ARG IBEX_VERIFIER_BASE
FROM ${IBEX_VERIFIER_BASE}

ARG RG_SHA256
ARG RG_RELEASE_ARCHIVE_SHA256
ARG IBEX_VERIFIER_BASE_ID
ARG HWE_TASK_ID
ARG COMMAND_UID
ARG COMMAND_GID
ARG IBEX_TOOLCHAIN_PROFILE

LABEL org.opencontainers.image.title="VeriGym Ibex HWE command image"
LABEL org.opencontainers.image.version="15.2.0-hwe-command-v1"
LABEL org.verigym.runtime.role="hwe-ibex-command"
LABEL org.verigym.collection.profile="hwe_standard_v2"
LABEL org.verigym.tool.contract="hwe_native_shell_v2"
LABEL org.verigym.command.protocol="hwe_command_image_v1"
LABEL org.verigym.command.rg.version="ripgrep 15.2.0 (rev e89fff89ac)"
LABEL org.verigym.command.rg.sha256="${RG_SHA256}"
LABEL org.verigym.command.rg.release_archive.sha256="${RG_RELEASE_ARCHIVE_SHA256}"
LABEL org.verigym.hwe.task_id="${HWE_TASK_ID}"
LABEL org.verigym.ibex.verifier_base_image_id="${IBEX_VERIFIER_BASE_ID}"
LABEL org.verigym.ibex.toolchain.profile="${IBEX_TOOLCHAIN_PROFILE}"
LABEL org.verigym.ibex.source_whiteout="/home/ibex"
LABEL org.verigym.codex.present="absent"
LABEL org.verigym.provider_credentials="absent"
LABEL org.verigym.hidden_assets="absent"
LABEL org.verigym.reference_patch="absent"
LABEL org.verigym.verifier_payload="absent"

USER root

# Keep the public simulator/build toolchain while removing the complete task source and marker.
# The candidate repository is provided only through the private /workspace/repository mount.
RUN rm -rf /home/ibex /home/ibex_base_commit.txt \
    && mkdir -p /home/ibex /workspace/repository /usr/local/lib/verigym-command-tools \
    && chown -R ${COMMAND_UID}:${COMMAND_GID} /workspace \
    && test -x /usr/bin/tail \
    && test -x /usr/bin/make \
    && case "${IBEX_TOOLCHAIN_PROFILE}" in \
        iverilog) test -x /usr/bin/iverilog && test -x /usr/bin/vvp ;; \
        verilator) test -x /usr/bin/verilator && test -x /usr/bin/verilator_bin ;; \
        *) exit 2 ;; \
    esac

COPY --chown=${COMMAND_UID}:${COMMAND_GID} rg /usr/local/lib/verigym-command-tools/rg

RUN ln -s /usr/local/lib/verigym-command-tools/rg /usr/local/bin/rg

ENV PATH=/usr/local/bin:/usr/bin:/bin
WORKDIR /workspace/repository
USER ${COMMAND_UID}:${COMMAND_GID}

CMD ["/usr/bin/tail", "-f", "/dev/null"]

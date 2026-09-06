# Existing lint image remains unchanged; this image adds the simulation build toolchain.
ARG VERILATOR_BASE=verigym/rtl-verilator:5.052-iverilog12-r1
FROM ${VERILATOR_BASE}

USER root
RUN apt-get update \
    && apt-get install --yes --no-install-recommends g++ make \
    && rm -rf /var/lib/apt/lists/*

LABEL org.opencontainers.image.title="VeriGym RealBench Verilator functional tools"
LABEL org.opencontainers.image.version="5.052-functional-r1"
LABEL org.verigym.runtime.role="rtl-verifier"
LABEL org.verigym.credential_material="absent"
LABEL org.verigym.commercial_assets="absent"

USER 10001:10001
WORKDIR /workspace
CMD ["verilator", "--version"]

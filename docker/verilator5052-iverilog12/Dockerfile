# syntax=docker/dockerfile:1

FROM debian@sha256:020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd AS builder

ARG VERILATOR_COMMIT=ea338be98e1e838d3518809ce8899f85a009963c

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        autoconf \
        bison \
        ca-certificates \
        flex \
        g++ \
        git \
        help2man \
        libfl-dev \
        make \
        perl \
        python3 \
    && rm -rf /var/lib/apt/lists/*

RUN git init /src/verilator \
    && git -C /src/verilator remote add origin https://github.com/verilator/verilator.git \
    && git -C /src/verilator fetch --depth 1 origin "${VERILATOR_COMMIT}" \
    && git -C /src/verilator checkout --detach FETCH_HEAD \
    && test "$(git -C /src/verilator rev-parse HEAD)" = "${VERILATOR_COMMIT}" \
    && cd /src/verilator \
    && autoconf \
    && ./configure --prefix=/opt/verilator \
    && make -j2 \
    && make install \
    && /opt/verilator/bin/verilator --version | grep --fixed-strings 'Verilator 5.052' \
    && git archive --format=tar.gz --prefix="verilator-${VERILATOR_COMMIT}/" \
        --output=/tmp/verilator-source.tar.gz HEAD

RUN rm -f \
        /opt/verilator/bin/verilator_bin_dbg \
        /opt/verilator/bin/verilator_coverage \
        /opt/verilator/bin/verilator_coverage_bin_dbg

FROM ghcr.io/jdzhu19/verigym-rtl-iverilog@sha256:44d5e56dc4ecede0aa9b53fd1dc63b2bdfb153b140084ace6b4847edbb673269 AS runtime

LABEL org.opencontainers.image.title="VeriGym Verilator and Icarus RTL tools"
LABEL org.opencontainers.image.version="verilator5.052-iverilog12-r1"
LABEL org.verigym.runtime.role="rtl-verifier"
LABEL org.verigym.verilator.version="5.052"
LABEL org.verigym.verilator.source.commit="ea338be98e1e838d3518809ce8899f85a009963c"
LABEL org.verigym.iverilog.version="12.0"
LABEL org.verigym.credential_material="absent"
LABEL org.verigym.commercial_assets="absent"

USER root

RUN apt-get update \
    && apt-get install --yes --no-install-recommends perl \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p \
        /usr/share/licenses/verilator \
        /usr/share/verigym/sources \
    && printf '%s\n' \
        'Verilator v5.052 peeled commit: ea338be98e1e838d3518809ce8899f85a009963c' \
        'Icarus runtime base digest: sha256:44d5e56dc4ecede0aa9b53fd1dc63b2bdfb153b140084ace6b4847edbb673269' \
        >> /usr/share/verigym/source-identities.txt

COPY --from=builder /opt/verilator /opt/verilator
COPY --from=builder /src/verilator/LICENSE /usr/share/licenses/verilator/LICENSE
COPY --from=builder /src/verilator/LICENSES /usr/share/licenses/verilator/LICENSES
COPY --from=builder /tmp/verilator-source.tar.gz \
    /usr/share/verigym/sources/verilator-source.tar.gz

ENV PATH=/opt/verilator/bin:/opt/iverilog/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

USER 10001:10001
WORKDIR /workspace

CMD ["verilator", "--version"]

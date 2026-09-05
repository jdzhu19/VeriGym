# syntax=docker/dockerfile:1

# Keep the public artifact independent from a mutable base tag.
FROM debian@sha256:020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd AS builder

ARG IVERILOG_COMMIT=4fd5291632232fbe1ba49b2c26bb6b2bf1c6c9cf

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        autoconf \
        bison \
        ca-certificates \
        flex \
        g++ \
        git \
        gperf \
        make \
    && rm -rf /var/lib/apt/lists/*

RUN git init /src/iverilog \
    && git -C /src/iverilog remote add origin https://github.com/steveicarus/iverilog.git \
    && git -C /src/iverilog fetch --depth 1 origin "${IVERILOG_COMMIT}" \
    && git -C /src/iverilog checkout --detach FETCH_HEAD \
    && test "$(git -C /src/iverilog rev-parse HEAD)" = "${IVERILOG_COMMIT}" \
    && cd /src/iverilog \
    && sh autoconf.sh \
    && ./configure --prefix=/opt/iverilog \
    && make -j2 \
    && make install \
    && git archive --format=tar.gz --prefix="iverilog-${IVERILOG_COMMIT}/" \
        --output=/tmp/iverilog-source.tar.gz HEAD

FROM debian@sha256:020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd AS runtime

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        coreutils \
        libbz2-1.0 \
        libreadline8t64 \
        libstdc++6 \
        libtinfo6 \
        python3-minimal \
        zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && printf 'verigym:x:10001:10001:VeriGym runtime:/home/verigym:/usr/sbin/nologin\n' \
        >> /etc/passwd \
    && printf 'verigym:x:10001:\n' >> /etc/group \
    && mkdir -p \
        /home/verigym \
        /workspace \
        /usr/share/licenses/iverilog \
        /usr/share/verigym/sources \
    && chown -R 10001:10001 /home/verigym /workspace \
    && printf '%s\n' \
        'Icarus v12_0 peeled commit: 4fd5291632232fbe1ba49b2c26bb6b2bf1c6c9cf' \
        > /usr/share/verigym/source-identities.txt \
    && printf '%s\n' \
        'The corresponding Icarus Verilog source archive is bundled in this directory.' \
        > /usr/share/verigym/sources/README

COPY --from=builder /opt/iverilog /opt/iverilog
COPY --from=builder /src/iverilog/COPYING /usr/share/licenses/iverilog/COPYING
COPY --from=builder /tmp/iverilog-source.tar.gz /usr/share/verigym/sources/iverilog-source.tar.gz

ENV PATH=/opt/iverilog/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

USER 10001:10001
WORKDIR /workspace

CMD ["iverilog", "-V"]

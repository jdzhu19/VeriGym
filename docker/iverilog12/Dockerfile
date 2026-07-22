# syntax=docker/dockerfile:1

FROM debian:bookworm-slim AS builder

ARG IVERILOG_TAG=v12_0

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

RUN git clone --branch "${IVERILOG_TAG}" --depth 1 \
        https://github.com/steveicarus/iverilog.git /src/iverilog \
    && cd /src/iverilog \
    && sh autoconf.sh \
    && ./configure --prefix=/opt/iverilog \
    && make -j2 \
    && make install

FROM debian:bookworm-slim AS runtime

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        coreutils \
        libbz2-1.0 \
        libreadline8 \
        libstdc++6 \
        libtinfo6 \
        python3-minimal \
        zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && printf 'verigym:x:10001:10001:VeriGym runtime:/home/verigym:/usr/sbin/nologin\n' \
        >> /etc/passwd \
    && printf 'verigym:x:10001:\n' >> /etc/group \
    && mkdir -p /home/verigym /workspace \
    && chown -R 10001:10001 /home/verigym /workspace

COPY --from=builder /opt/iverilog /opt/iverilog

ENV PATH=/opt/iverilog/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

USER 10001:10001
WORKDIR /workspace

CMD ["iverilog", "-V"]

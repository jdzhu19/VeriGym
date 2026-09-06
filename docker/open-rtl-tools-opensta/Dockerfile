# syntax=docker/dockerfile:1

# This is deliberately independent from docker/open-rtl-tools so the accepted
# iverilog12-yosys067 image is never replaced by the OpenSTA extension.
FROM debian@sha256:020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd AS yosys-builder

ARG YOSYS_RELEASE=v0.67
ARG YOSYS_ARCHIVE_SHA256=608d758a6efc73c9f866b0a822aa2f788c2889fcb70dcdcc0e758009465049f6

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        bison ca-certificates cmake curl flex g++ gawk make ninja-build python3 \
    && rm -rf /var/lib/apt/lists/*

RUN curl --fail --location --retry 3 \
        "https://github.com/YosysHQ/yosys/releases/download/${YOSYS_RELEASE}/yosys.tar.gz" \
        --output /tmp/yosys.tar.gz \
    && printf '%s  %s\n' "${YOSYS_ARCHIVE_SHA256}" /tmp/yosys.tar.gz \
        | sha256sum --check --strict - \
    && mkdir -p /src/yosys \
    && tar --extract --gzip --file /tmp/yosys.tar.gz --directory /src/yosys \
    && test "$(cat /src/yosys/.gitcommit)" = \
        "b8e7da6f40ae8f552c116bf6c359b07c6533e159" \
    && test "$(cat /src/yosys/abc/.gitcommit)" = \
        "e026ed5380f3bdc3beea2ff9ffc23236fc549d5b"

RUN cmake -S /src/yosys -B /src/yosys/build -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/yosys \
        -DBUILD_SHARED_LIBS=OFF \
        -DYOSYS_WITHOUT_LIBFFI=ON \
        -DYOSYS_WITHOUT_READLINE=ON \
        -DYOSYS_WITHOUT_SLANG=ON \
        -DYOSYS_WITHOUT_TCL=ON \
        -DYOSYS_WITHOUT_ZLIB=ON \
    && cmake --build /src/yosys/build --parallel 2 \
    && cmake --install /src/yosys/build --strip \
    && /opt/yosys/bin/yosys -V \
    && /opt/yosys/bin/yosys-abc -c 'version; quit'

FROM debian@sha256:020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd AS iverilog-builder

ARG IVERILOG_COMMIT=4fd5291632232fbe1ba49b2c26bb6b2bf1c6c9cf

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        autoconf bison ca-certificates flex g++ git gperf make \
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

FROM debian@sha256:020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd AS opensta-builder

ARG OPENSTA_COMMIT=be771a0116985d57effb4120668ae98e8a7b0f79
ARG OPENSTA_ARCHIVE_SHA256=3751516f6275197aef4bdb2eadd7385a03641de928c362bc5aae37b9177cbf05
ARG CUDD_ARCHIVE_SHA256=b8e966b4562c96a03e7fbea239729587d7b395d53cadcc39a7203b49cf7eeb69

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        autoconf automake bison ca-certificates cmake curl flex g++ libeigen3-dev \
        libtool make ninja-build swig tcl-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN curl --fail --location --retry 3 \
        https://github.com/davidkebo/cudd/raw/main/cudd_versions/cudd-3.0.0.tar.gz \
        --output /tmp/cudd.tar.gz \
    && printf '%s  %s\n' "${CUDD_ARCHIVE_SHA256}" /tmp/cudd.tar.gz \
        | sha256sum --check --strict - \
    && mkdir -p /src/cudd \
    && tar --extract --gzip --file /tmp/cudd.tar.gz --directory /src/cudd \
        --strip-components=1 \
    && cd /src/cudd \
    && ./configure --prefix=/opt/cudd --enable-shared=no \
    && make -j2 \
    && make install

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libfl-dev \
    && rm -rf /var/lib/apt/lists/*

RUN curl --fail --location --retry 3 \
        "https://codeload.github.com/The-OpenROAD-Project/OpenSTA/tar.gz/${OPENSTA_COMMIT}" \
        --output /tmp/opensta.tar.gz \
    && printf '%s  %s\n' "${OPENSTA_ARCHIVE_SHA256}" /tmp/opensta.tar.gz \
        | sha256sum --check --strict - \
    && mkdir -p /src/opensta \
    && tar --extract --gzip --file /tmp/opensta.tar.gz --directory /src/opensta \
        --strip-components=1 \
    && grep --fixed-strings 'project(STA VERSION 3.1.0' /src/opensta/CMakeLists.txt \
    && cmake -S /src/opensta -B /src/opensta/build -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/opensta \
        -DCUDD_DIR=/opt/cudd \
        -DUSE_TCL_READLINE=OFF \
        -DBUILD_TESTS=OFF \
    && cmake --build /src/opensta/build --parallel 2 \
    && cmake --install /src/opensta/build --strip \
    && test "$(/opt/opensta/bin/sta -version)" = "3.1.0"

FROM debian@sha256:020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd AS runtime

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        coreutils libbz2-1.0 libreadline8t64 libstdc++6 libtcl8.6 libtinfo6 python3-minimal zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && printf 'verigym:x:10001:10001:VeriGym runtime:/home/verigym:/usr/sbin/nologin\n' \
        >> /etc/passwd \
    && printf 'verigym:x:10001:\n' >> /etc/group \
    && mkdir -p \
        /home/verigym \
        /workspace \
        /usr/share/licenses/cudd \
        /usr/share/licenses/iverilog \
        /usr/share/licenses/opensta \
        /usr/share/licenses/yosys \
        /usr/share/verigym/sources \
    && chown -R 10001:10001 /home/verigym /workspace \
    && printf '%s\n' \
        'Yosys release asset: v0.67' \
        'Yosys archive SHA-256: 608d758a6efc73c9f866b0a822aa2f788c2889fcb70dcdcc0e758009465049f6' \
        'Yosys vendored source identity: b8e7da6f40ae8f552c116bf6c359b07c6533e159' \
        'ABC vendored source identity: e026ed5380f3bdc3beea2ff9ffc23236fc549d5b' \
        'Icarus source identity: 4fd5291632232fbe1ba49b2c26bb6b2bf1c6c9cf' \
        'OpenSTA vendored source identity: be771a0116985d57effb4120668ae98e8a7b0f79' \
        > /usr/share/verigym/source-identities.txt \
    && printf '%s\n' \
        'The corresponding source archives for the statically built tools are bundled here.' \
        > /usr/share/verigym/sources/README \
    && printf '%s\n' \
        '#!/bin/sh' \
        'exec cat /usr/share/verigym/source-identities.txt' \
        > /usr/local/bin/verigym-toolchain-identity \
    && chmod 0555 /usr/local/bin/verigym-toolchain-identity

COPY --from=yosys-builder /opt/yosys /opt/yosys
COPY --from=iverilog-builder /opt/iverilog /opt/iverilog
COPY --from=opensta-builder /opt/opensta /opt/opensta
COPY --from=yosys-builder /src/yosys/COPYING /usr/share/licenses/yosys/COPYING
COPY --from=iverilog-builder /src/iverilog/COPYING /usr/share/licenses/iverilog/COPYING
COPY --from=opensta-builder /src/cudd/LICENSE /usr/share/licenses/cudd/LICENSE
COPY --from=opensta-builder /src/opensta/LICENSE /usr/share/licenses/opensta/LICENSE
COPY --from=yosys-builder /tmp/yosys.tar.gz /usr/share/verigym/sources/yosys-v0.67.tar.gz
COPY --from=iverilog-builder /tmp/iverilog-source.tar.gz /usr/share/verigym/sources/iverilog-source.tar.gz
COPY --from=opensta-builder /tmp/cudd.tar.gz /usr/share/verigym/sources/cudd-3.0.0.tar.gz
COPY --from=opensta-builder /tmp/opensta.tar.gz /usr/share/verigym/sources/opensta.tar.gz

RUN printf 'OpenSTA executable SHA-256: %s\n' \
        "$(sha256sum /opt/opensta/bin/sta | cut --delimiter=' ' --fields=1)" \
        >> /usr/share/verigym/source-identities.txt

ENV PATH=/opt/opensta/bin:/opt/yosys/bin:/opt/iverilog/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

USER 10001:10001
WORKDIR /workspace

CMD ["sta", "-version"]

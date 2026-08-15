ARG DOCKER_CLI_BASE
ARG PYTHON_BASE
FROM ${DOCKER_CLI_BASE} AS docker_cli

FROM ${PYTHON_BASE}

ARG VERIGYM_COMMIT
ARG GIT_PACKAGE_VERSION=1:2.30.2-1+deb11u5

LABEL org.opencontainers.image.title="VeriGym trusted rollout controller" \
      org.opencontainers.image.source="https://github.com/jdzhu19/VeriGym" \
      io.verigym.role="rollout-controller" \
      io.verigym.verigym.commit="${VERIGYM_COMMIT}" \
      io.verigym.docker.client="19.03.14" \
      io.verigym.git.client="2.30.2" \
      io.verigym.controller.glibc="2.31"

RUN apt-get update && \
    apt-get install --yes --no-install-recommends "git=${GIT_PACKAGE_VERSION}" && \
    rm -rf /var/lib/apt/lists/*

COPY --from=docker_cli /usr/local/bin/docker /usr/local/bin/docker
COPY wheels /opt/verigym/wheels
COPY run_qwen35_online_repository_broker.py /opt/verigym/bin/

RUN python3 -m pip install --no-cache-dir /opt/verigym/wheels/*.whl && \
    python3 -m pip check && \
    python3 -c 'import importlib.metadata; \
assert importlib.metadata.version("verigym") == "0.1.0"; \
assert importlib.metadata.version("verigym-hwe-bench") == "0.1.0"; \
assert importlib.metadata.version("verigym-training-reference") == "0.3.0"' && \
    python3 -c 'import platform,threading; \
assert platform.libc_ver() == ("glibc", "2.31"); \
thread = threading.Thread(target=lambda: None); thread.start(); thread.join()' && \
    git --version | grep -F 'git version 2.30.2' && \
    docker --version | grep -F 'Docker version 19.03.14'

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /work
ENTRYPOINT ["python3", "/opt/verigym/bin/run_qwen35_online_repository_broker.py"]
CMD ["--help"]

ARG PYTHON_BASE
FROM ${PYTHON_BASE}

ARG PYTHON_BASE_ID
ARG VLLM_WHEEL_SHA256
ARG GCC_PACKAGE_VERSION
ARG LIBC6_DEV_PACKAGE_VERSION

LABEL org.opencontainers.image.title="VeriGym vLLM 0.22.1 CUDA 12.9 service" \
      org.opencontainers.image.source="https://github.com/jdzhu19/VeriGym" \
      io.verigym.python.base_id="${PYTHON_BASE_ID}" \
      io.verigym.vllm.version="0.22.1" \
      io.verigym.vllm.cuda_variant="cu129" \
      io.verigym.vllm.wheel_sha256="${VLLM_WHEEL_SHA256}"

RUN python3 -c 'import urllib.request; \
urllib.request.urlretrieve( \
"https://github.com/vllm-project/vllm/releases/download/v0.22.1/" \
"vllm-0.22.1%2Bcu129-cp38-abi3-manylinux_2_28_x86_64.whl", \
"/opt/vllm-0.22.1+cu129-cp38-abi3-manylinux_2_28_x86_64.whl")' && \
    echo "365ee929afd73bb5d146235b65053fa948788ec2ee00a2c3e957d3f43bf2b0cd  /opt/vllm-0.22.1+cu129-cp38-abi3-manylinux_2_28_x86_64.whl" \
      | sha256sum --check --strict && \
    python3 -m pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cu129 \
      "torch==2.11.0+cu129" && \
    python3 -m pip install --no-cache-dir \
      /opt/vllm-0.22.1+cu129-cp38-abi3-manylinux_2_28_x86_64.whl && \
    rm /opt/vllm-0.22.1+cu129-cp38-abi3-manylinux_2_28_x86_64.whl && \
    python3 -m pip check && \
    python3 -c 'import importlib.metadata,torch,vllm; \
assert importlib.metadata.version("vllm").split("+")[0] == "0.22.1"; \
assert torch.__version__.split("+")[0] == "2.11.0"; \
assert torch.version.cuda == "12.9"; \
assert vllm.__version__.split("+")[0] == "0.22.1"'

# vLLM's dependency resolution uses the default index after the cu129 torch install. Re-seal the
# compiled vision/audio extensions from the matching PyTorch index and import them so a metadata-
# only `pip check` cannot hide a CUDA wheel ABI mismatch.
RUN python3 -m pip install --no-cache-dir --force-reinstall --no-deps \
      --index-url https://download.pytorch.org/whl/cu129 \
      "torchvision==0.26.0+cu129" \
      "torchaudio==2.11.0+cu129" && \
    python3 -c 'import torch,torchaudio,torchvision; \
assert torch.__version__.split("+")[0] == "2.11.0"; \
assert torchvision.__version__ == "0.26.0+cu129"; \
assert torchaudio.__version__ == "2.11.0+cu129"'

# Triton compiles small launchers and model-specific kernels when vLLM initializes the engine.
# Keep the minimum C toolchain in the runtime image and pin its requested Debian package versions.
LABEL io.verigym.runtime.gcc_package_version="${GCC_PACKAGE_VERSION}" \
      io.verigym.runtime.libc6_dev_package_version="${LIBC6_DEV_PACKAGE_VERSION}"
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      "gcc=${GCC_PACKAGE_VERSION}" \
      "libc6-dev=${LIBC6_DEV_PACKAGE_VERSION}" && \
    rm -rf /var/lib/apt/lists/* && \
    printf '#include <Python.h>\nint verigym_cc_smoke(void) { return 0; }\n' \
      > /tmp/verigym-cc-smoke.c && \
    cc -shared -fPIC $(python3-config --includes) \
      /tmp/verigym-cc-smoke.c -o /tmp/verigym-cc-smoke.so && \
    rm /tmp/verigym-cc-smoke.c /tmp/verigym-cc-smoke.so

RUN mkdir -p /opt/verigym && \
    python3 -m pip freeze --all | LC_ALL=C sort > /opt/verigym/vllm-service-pip-freeze.txt && \
    dpkg-query -W -f='${Package}\t${Version}\n' gcc libc6-dev \
      > /opt/verigym/vllm-service-os-packages.txt && \
    cc --version > /opt/verigym/vllm-service-compiler-version.txt

ARG VERIGYM_COMMIT
LABEL org.opencontainers.image.revision="${VERIGYM_COMMIT}"

RUN mkdir -p /work /cache && chmod 1777 /work /cache

ENV HF_HOME=/cache/huggingface \
    VLLM_CACHE_ROOT=/cache/vllm \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /work
ENTRYPOINT []
CMD ["python3", "-m", "vllm.entrypoints.openai.api_server", "--help"]

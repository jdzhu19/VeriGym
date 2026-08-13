ARG VLLM_BASE
FROM ${VLLM_BASE}

ARG RLLM_COMMIT
ARG VERIGYM_COMMIT

LABEL org.opencontainers.image.title="VeriGym Qwen multi-turn SFT trainer" \
      org.opencontainers.image.source="https://github.com/jdzhu19/VeriGym" \
      io.verigym.rllm.commit="${RLLM_COMMIT}" \
      io.verigym.verigym.commit="${VERIGYM_COMMIT}" \
      io.verigym.verl.version="0.8.0" \
      io.verigym.vllm.version="0.22.1"

COPY rllm /opt/rllm
COPY wheels /opt/verigym/wheels
COPY train_qwen35_multiturn_sft.py /opt/verigym/bin/train_qwen35_multiturn_sft.py

RUN python3 -m pip uninstall --yes \
      vllm lmcache opencv-python-headless cupy-cuda13x pygobject && \
    python3 -m pip install --no-cache-dir "verl==0.8.0" /opt/rllm /opt/verigym/wheels/*.whl && \
    python3 -m pip check && \
    python3 -c 'import importlib.metadata,subprocess; \
assert importlib.metadata.version("verl") == "0.8.0"; \
assert subprocess.check_output(["git", "-C", "/opt/rllm", "rev-parse", "HEAD"], \
text=True).strip() == "1d1109a655e291b3001d8526d7c9ecc5b9328226"'

RUN mkdir -p /work /cache && chmod 1777 /work /cache

ENV HF_HOME=/cache/huggingface \
    VLLM_CACHE_ROOT=/cache/vllm \
    RLLM_HOME=/cache/rllm \
    VERIGYM_VLLM_SERVICE_VERSION=0.22.1 \
    PYTHONUNBUFFERED=1

WORKDIR /work
ENTRYPOINT []
CMD ["python3", "/opt/verigym/bin/train_qwen35_multiturn_sft.py", "--help"]

# VeriGym DeepSeek Harness integration

This optional integration runs the pinned official DeepSeek Harness controller outside an
isolated HWE-Bench task container. The controller reaches the task only through VeriGym's six
typed repository actions over an owner-only Unix socket; the task runtime receives no provider
credential and has no network access.

The integration supports the bounded three-task collection pilot documented in
[`docs/hwe_deepseek_harness_collection.md`](../../docs/hwe_deepseek_harness_collection.md). It
does not enable training, retries, context compaction, or benchmark-scale collection by default.

Install it from the repository root with:

```bash
python -m pip install --no-build-isolation -e integrations/verigym-deepseek-harness
```

Credential-free tests, including a fake-provider conformance test against the pinned controller
image, run with `pytest` from this directory.

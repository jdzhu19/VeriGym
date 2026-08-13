# verigym-openhands

Optional OpenHands SDK 1.42.1 inference harness for repository tasks. It exposes only the six
canonical VeriGym broker tools. OpenHands receives no repository mount, terminal, file editor,
Docker socket, hidden asset, reference solution, plugin, or skill.

Real runs are opt in and require Python 3.12, `VERIGYM_OPENHANDS_BROKER_ROOT`, and the configured
model endpoint environment variables.

The development comparison is intentionally two samples, not a benchmark score. Freeze distinct
base and adapter policy manifests with `scripts/freeze_openhands_sft_agent_versions.py`, then run
`scripts/run_openhands_cva6_development_pilot.py` against the two frozen CVA6 validation tasks.
Both commands reject held-out/training split drift; the pilot stops on infrastructure-invalid
results and never retries an episode.

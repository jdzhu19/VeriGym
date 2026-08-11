# HWE repo-level held-out v1 campaign

- Date: 2026-08-11
- Status: infrastructure-invalid early stop; not a benchmark score
- Code commit: `7764ba7b1707d506bc2c2558b7d65e3b5ae9232c`
- Agent: `codex-luna-max-hwe-heldout-v1`, `gpt-5.6-luna`, reasoning `max`
- Split: `hwe-repo-heldout-v1`
- Sampling: one sample per task, base seed 3, no retry, no best-of-K

## Freeze

The frozen agent-version hash is
`1b01f7385eb242a9ac94bf7621738e0e24d788f67dc523a16ed189574a724ea7`. It binds
the committed core, Codex bridge, HWE integration, and training-reference wheel hashes; the
common repository-agent and outer-runtime images; and each selected task's suite-managed official
image ID. The content-free repository freeze has manifest hash
`51f1e086ae08b655aa0a00621ed1baa0707f9c804eebc8b380650db2638d1705` and split
manifest hash `b8fea2ea5cac55c5f30f6e0db4948e336e71b57286df98c590e3eef33468e7af`.
It contains exactly Ibex PR222, CVA6 PR2945, and Rocket Chip PR3065, with an empty training and
validation split. No repository contents, hidden assets, or reference solutions are in the freeze.

Zero-call Codex capability and authentication preflights passed. They observed Codex CLI 0.146.0,
the inherited ChatGPT-session semantic, zero diagnostic model calls, no copied credential files,
and no credential contents accessed by VeriGym.

## Campaign outcome

The frozen plan hash is `871c462b53f16a4d1e7e9bf7c74c7b5a40710844805073a6f11cf4b03e016efe`.
The first Ibex sample started and the upstream model service terminated the turn with the typed
`serverOverloaded` condition, reporting that the selected model was at capacity. The external
process was not timed out and its terminal event and cleanup were observed. It produced no patch.

The official Ibex verifier still ran in the locked image with network disabled and returned the
ordinary `test_failed` result for the unchanged base candidate. That verifier result was not an
infrastructure failure. The overall scorecard is infrastructure-invalid because the model episode
did not complete, so the campaign atomically recorded one attempted sample and stopped before any
CVA6 or Rocket model call, as required by the frozen no-retry policy.

| Planned task order | Attempted | Outcome |
| --- | --- | --- |
| Ibex PR222 | yes | infrastructure-invalid: upstream model capacity |
| CVA6 PR2945 | no | not started after early stop |
| Rocket PR3065 | no | not started after early stop |

The sampling summary hash is
`f8107ae788cb9250984656f8a83b650eda2dbb7dfefdcec1f0fd949e129571cc`; its file
SHA-256 is `bc26df062e6dd2824a0a719ce8bdfcfc1a205db9d9b1b86d138658452def0407`.
The scorecard file SHA-256 is
`02b15847fd6d22b369de56b75a1b05b887e270f08007e542bc35fe141860886c`.

## Offline post-processing and safety

Visible-episode replay passed. Observable trajectory export, dataset validation, and source replay
then completed with zero additional model, network, runtime, verifier, or public-launcher calls.
The dataset hash is `3697e5c1402b1252771f289e119ebc8ff2123b504108abcbef1cc14b106738f2`.
It contains one held-out record, zero eligible records, and explicitly excludes the run as
`infrastructure_invalid`.

A training-reference preparation check rejected the dataset with no eligible training records and
created no training bundle. Its report hash is
`547e6354b9f90de7fa418f122adf6abf2625c0f2f4f16ece8e023b178308cd2e`.
The context-aware artifact scan covered 240 files and 2,580,883 bytes. It passed with zero hard
secret leaks and zero scanner errors; its report hash is
`347716a8f2b4692496c84a81c88d93d353a3804982dfde104d907cb62f04b824`.
No suite verifier container or labeled ephemeral cache volume remained after the run.

This result validates the freeze, early-stop, replay, exclusion, and artifact-safety paths. It does
not provide a completed three-task held-out result or a model-quality claim. A future attempt would
be a new explicitly authorized campaign, not a retry within this frozen no-retry run.

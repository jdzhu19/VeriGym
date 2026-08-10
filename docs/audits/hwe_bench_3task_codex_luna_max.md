# HWE-Bench three-task Codex pilot

- Date: 2026-08-10
- Scope: three official tasks, one sample each, no retry or best-of-K selection
- Agent: Codex CLI 0.146.0, observed `gpt-5.6-luna`, reasoning effort `max`
- Runtime: credential-free Docker repository agent plus digest-locked suite verifiers
- Tasks: Ibex PR167, CVA6 PR2170, and Ibex PR1735

Both newly added tasks first reproduced base-FAIL/reference-PASS with zero model calls. The Ibex
PR167 smoke report is SHA-256
`4c9933a84df12c967334c2f9172fb27d3ef3f80be5ffe31af608abdd4dbb6546`; the CVA6 PR2170 report is
`838dca653103dde0167bf69bf4911e300cce705dd04653462b693d40b1367a03`. PR167 uses the image's
synthetic runtime commit while retaining a verified link to official base
`59254498489d441f64c24e6b344fce73d0d8bbce`. CVA6 preparation safely materialized internal file
symlinks; the resulting agent workspace contains no symlinks.

## Agent campaign result

The frozen v2 plan completed all three samples with zero infrastructure-invalid outcomes:

| Task | Outcome | Candidate delta | Tokens (input/output) | Wall time |
| --- | --- | --- | ---: | ---: |
| Ibex PR167 | resolved | `rtl/ibex_controller.sv` (+8/-2) | 36,602 / 877 | 177.9 s |
| CVA6 PR2170 | eligible negative | `core/cache_subsystem/miss_handler.sv` (+8/-0) | 174,102 / 1,611 | 783.9 s |
| Ibex PR1735 | eligible negative | two RTL files (+57/-13) | 226,443 / 2,123 | 1,334.5 s |

The plan, result list, and final summary hashes are
`934b050dcea7c53da171b83b5f878d432ab971ad0f5894af35b08b538d492f08`,
`31236e8faf529264037ba47010f02261e37fd6fde9606e6bec61c55b1893d92e`, and
`4b1ee8e9622ff999163d97dca5cfe4e6ad4667cb148cfc092149133f4a3d050b`. An earlier v1 launch lacked
the required public authentication-mode label and was rejected before any model call; it is not
pooled with v2. The sampler now validates this label before creating an output and persists a typed
infrastructure failure if orchestration raises.

## Observable trajectory dataset

All three runs exported as eligible `observable_repo_trajectory_v1` records. Offline export,
validation, and source replay made zero model, runtime, verifier, network, or public-launcher calls.

- Dataset hash: `ebf18f03852b62fa6daa3d5907c090fe30767e8e7294778c1940d1f937b076fd`
- Agent-version hash: `cd96965005a3f1580b8d5f6ba68f73632982924617d3249cd2576fb0bb8f3a39`
- Split-manifest hash: `d7a4241b27d580259f20b79a55e5b761c8395417e4e8fff8e3d6e9ecec57cfe5`
- `dataset-manifest.json`: `6233721ae575faf3d97108a3b65a65f65c8b4985764742528ece19e1a70bd646`
- `SHA256SUMS`: `8a16257e25be83e9d7d017eefb2f1e0e79f6ba0d0907318d7dfc09c794d6d572`

The context-aware scan covered 17 files and 161,440 bytes: zero hard secret leaks, zero scanner
errors, no persisted proxy values, and no raw suspected values. This pilot establishes platform
compatibility and trajectory production only; one resolved sample out of three is not a benchmark
score or a general model-quality claim.

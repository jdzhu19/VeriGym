# MVP Stabilization Baseline

Baseline captured on 2026-07-23 before tracked source changes. This document records observed
behavior; it does not treat skipped or unavailable checks as passing.

Current-host note (2026-08-28): Icarus 12 is now the default interactive tool, with the former
Icarus 13 installation retained side by side. The entries below deliberately preserve the
historical 2026-07-23 baseline and must not be read as the current AgentEval qualification.

## Source and environment

- Package: `verigym 0.1.0`
- Git branch/commit: `main` at `ab6ddd29563bf8fb2e578745142043f67c17238e`
- Commit tree: `6c82151c79f676d80d56859fdd6c2f27286d41cf`
- Tracked checkout: clean. The local audit prompt and `AGENTS.md` were ignored, untracked inputs
  and therefore did not participate in the commit tree or package build.
- Runtime: CPython 3.11.13 on Linux x86_64. Python 3.12 and 3.13 were unavailable.
- Docker: client/server 23.0.4, API 1.42, Linux/amd64, non-rootless daemon.
- Icarus/VVP on the host: development 13.0, source identity
  `s20221226-554-g25a84d5cf`.
- Yosys on the host: `0.45+139`, Git `4d581a97d`; the usable companion executable was
  `yosys-abc`.
- Icarus image:
  `sha256:5b95472e7fbfa80eb0cf173099254ef5285fcd78f7c3c78b42678ae9181dd96e`.
- Open-tools image:
  `sha256:77aa99d8afc4143f6168f749075a20f387f46d38080f228b7e7ff8e85fcbeaa6`.
  It resolved Yosys 0.67 (`b8e7da6f…`), ABC 1.01 (`e026ed53…`), declared profile
  `d68b5be9…`, and resolved profile `fe425493…`.
- No user-supplied external VerilogEval checkout was configured.

No Docker containers or volumes carrying VeriGym ownership labels remained after the baseline.

## Executed baseline checks

| Check | Result | Evidence summary |
|---|---|---|
| Ruff format/lint | Pass | 152 files formatted; all checks passed |
| Strict mypy | Pass | 119 source files |
| Ordinary pytest | Pass | 241 passed, 20 skipped, 261 collected |
| Local Yosys | Pass | 2 passed |
| Docker Icarus | Partial | 8 passed; real external VerilogEval case skipped |
| Docker Yosys | Pass | 5 passed |
| Synthetic VerilogEval batch | Pass | 1 passed |
| Docker batch | **Fail** | child/plan mismatch: `runtime, profiles` |
| Profile-enabled Yosys batch | **Fail** | child/plan mismatch: `runtime` |
| Real external VerilogEval | **Blocked** | no pinned user-supplied checkout |
| Python 3.12/3.13 | **Blocked** | interpreters unavailable |

Direct local CLI evidence also passed toy ChatEval, scripted AgentEval, ReAct AgentEval, sequential
and two-worker eight-child batches, zero-work resume, report regeneration, replay, reverification,
and synthetic two-sample canonical pass@k (`pass@1=0.5`, `pass@2=1`). Known-bad and malformed
outputs returned normal exit code 1; injected model exhaustion returned 4; invalid configuration
returned 2; a missing host tool returned 3. A missing Docker image returned 4 before model lookup,
which does not match the target missing-dependency category.

## Distribution baseline

The declared `python -m build` command could not run because the `build` frontend was not
installed or declared in development dependencies. Direct `setuptools.build_meta` hooks produced
a 144-member wheel and 196-member sdist. An isolated wheel installation (with inherited
dependencies) passed `pip check`, CLI help, doctor, import, and a toy public-API run.

With identical clean Git archives and `SOURCE_DATE_EPOCH=1784712454`, two wheels were
byte-identical:

```text
2c2ca17c84d109c48c00b2a92a6905bafde3c010961c3888c032e89f43602118
```

The sdists were not byte-identical:

```text
0bb74525e0d43f10c754581c7ae9d99cfa2c294cfa5137008d8adcb0d2c80b13
145859af36fc322b76fde54ff9a37ab90af4c778c86e66955824ee5389515f3e
```

Generated directory, `PKG-INFO`, egg-info, and `setup.cfg` mtimes differed. Package metadata used
Apache-2.0 and Python `>=3.11`, but had no project URLs and emitted a setuptools license-table
deprecation warning.

## Contract, provenance, documentation, and licensing findings

- Persisted run, sampling, experiment, report, trace, scorecard, task, profile, tool-result, and
  verifier-result objects use schema `1.0`. Verifier `request.json` objects have no
  `schema_version`; there is no general compatibility dispatcher, exported JSON-Schema set, or
  golden compatibility corpus.
- Standalone manifests write `verigym_commit: null`. The wheel contains no embedded source/build
  provenance, and doctor does not report one.
- Runs and experiment parents have no integrity manifest. Replay/report loaders therefore cannot
  cryptographically bind the complete required artifact set.
- The public top-level API exports only `VeriGym`, `RunConfig`, `RunResult`, and `__version__`.
  External entry-point plugin installation and installed-wheel discovery have no acceptance
  evidence.
- Existing documentation covers Docker, Yosys, profiles, experiments, reporting, VerilogEval,
  models/agents, and one experiment-plan ADR. Most release-audit contract documents, extension
  guides, compatibility/provenance docs, `CONTRIBUTING.md`, and `CHANGELOG.md` are absent.
- The project Apache-2.0 `LICENSE` and the first-party educational Liberty `NOTICE` are present.
  No repository-level third-party notice or machine-readable distribution inventory exists.
- The wheel contains first-party toy tasks/candidates/hidden tests, the educational Liberty asset,
  and generic VerilogEval workspace scaffolding. It contains no synthetic or external VerilogEval
  corpus, credentials, audit outputs, or host paths.

The untouched baseline is not a release candidate.

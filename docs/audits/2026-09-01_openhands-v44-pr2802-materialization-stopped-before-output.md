# OpenHands v44 PR-2802 materialization stopped before output

Date: 2026-09-01

Status: infrastructure-invalid, zero Docker builds and provider calls, v44 permanently sealed.

## Authorization and stop boundary

PR #69 merged the v44 authorization as
`76e024d9f2b24a05e6c859e72abaf729b1296980`. Post-merge `main` Actions run
`33488596586` passed all eight required job classes. The frozen authorization hash was
`0d696630052b212bd320d32b42222a7d644a77395b37a642ef64f8f292662958`.

The documented command was invoked once from that exact clean tracked commit after execution-time
checks reconfirmed that `HEAD` equalled `origin/main`, the authorized output did not exist, both
legacy Docker images existed, Docker used `/data/docker`, approximately 353 GiB and 250 million
inodes were available, and all ten exact v44 evidence tests passed.

The process then stopped at its first repository-package import, before runner `main`, output
creation, scratch allocation, a Docker command, or a task loop. The authorized output path remains
absent. There are therefore zero command images, scans, locks, task attempts, model processes,
provider episodes, and provider calls attributable to v44. No formal collection, training, GPU
work, or held-out load started.

## Root cause

The documented command used the shell's unqualified `python`, which resolved to the host Conda
Python 3.11 environment. That environment contained a stale editable installation at:

`/home/jzhu484/miniconda3/envs/agent/lib/python3.11/site-packages/__editable__.verigym-0.1.0.pth`

The path entry pointed at an older temporary checkout:

`/data/jzhu484/Agent/.verigym-tmp/VeriGym-rtl-agenteval-v1/src`

Consequently `verigym` resolved from that checkout instead of the authorized main tree. Its older
`verigym.hwe.image_lock` did not export `HweCommandImageLock`, so Python raised `ImportError`
before the v44 code could validate its merged-path or source-identity gates.

This is a launcher/import-isolation defect, not a PR-2802 build, verifier, security, benchmark, or
model result. Python documents that `site` processes `.pth` path-configuration files and adds their
entries to `sys.path`:
<https://docs.python.org/3/library/site.html>. pip likewise documents that editable installs add
the development directory to Python's import path:
<https://pip.pypa.io/en/stable/topics/local-project-installs/>.

The repository `.venv` does not inherit system site-packages and resolves `verigym` from the
current repository, but merely changing the command and retrying v44 would violate the immutable
one-invocation authorization.

## Frozen stop evidence

The sanitized receipt is external at:

`/data/jzhu484/Agent/experiments/openhands-hwe-v44-pr2802-canary-materialization-pre-output-stop-v1`

Its identities are:

- receipt hash:
  `a8445d99f0d60935a8653b5c89df29caa947cb07c37928dff8dd037beab53d4f`;
- receipt file SHA-256:
  `a6cacd86ff63646a43af0c17154d5d13a464b28c880b2de1b6a291f60e1d5a28`; and
- evidence tree hash:
  `e54bb5c868bf09a620fec78b50ccf60f54d36efa88cc7188bf547c5a386b19c9`.

The receipt persists only the sanitized failure category, exact public/local source identities,
zero-action accounting, and terminal flags. It contains no concrete provider endpoint or key,
proxy value, raw traceback, benchmark asset, model content, prompt, or hidden data.

## Disposition and successor requirements

V44 must not be rerun, even though its authorized output is absent. PR-2802 and PR-3204 remain
fresh because no task execution or image construction began.

The next materialization must use a separately reviewed v45 identity and bind this receipt, its
merged audit commit, and green post-merge main run. It must:

- invoke the repository's isolated `.venv/bin/python`, not an ambient interpreter;
- bootstrap the current repository `src` ahead of site-package paths before importing `verigym`;
- fail before output if the loaded `verigym` package or required modules are not under the exact
  merged repository;
- regression-test startup with a deliberately stale competing `verigym` path; and
- retain v44's PR-2802 inputs, PR-3204 reuse, headroom, v2 scan, network-none, zero-provider, and
  atomic receipt rules.

The future provider canary identity therefore advances from v45 to v46 without changing task
order, protocol, model, budget, seed 495, or sample index 11.

Terminal state remains:

- `formal_collection_allowed=false`;
- `formal_collection_started=false` and `collection_started=false`;
- `training_started=false` and `production_training_ready=false`.

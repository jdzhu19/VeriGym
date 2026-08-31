# VeriGym

VeriGym is a benchmark-neutral, toolchain-aware evaluation environment for RTL agents. It
normalizes benchmark tasks, agent harnesses, tools, and runtimes into versioned contracts, runs a
policy-controlled episode, and writes replayable traces and correctness-first evaluation summaries.

```text
SuiteAdapter -> VeriTask -> AgentProtocol -> Tool/Runtime Profile
             -> Verifier DAG -> Trace + ScoreCard + Evaluation Summary
```

VeriGym supports three bounded evaluation protocols. **ChatEval** makes one model call without
tool feedback. **AgentEval** permits budgeted multi-turn actions and tools. **EvolvingAgentEval**
compares immutable agent versions produced from allowed observable history on a sealed held-out
split. The current evolving bridge supports context-memory versions and external trainer manifests;
it does not claim built-in model training or autonomous self-improvement. See the
[architecture overview](docs/architecture.md).

## Install

Python 3.11+ is required. `LocalRuntime` verification also needs host `iverilog` and `vvp`;
DockerRuntime obtains them from its explicitly selected image.

Use one virtual environment per Git worktree so an editable install cannot resolve to a sibling
checkout:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,openai-compatible]'
python -c 'from pathlib import Path; import verigym; print(Path(verigym.__file__).resolve())'
verigym doctor
```

Optional integrations are separate packages maintained in this monorepo. Install only the ones an
experiment needs:

```bash
python -m pip install -e integrations/verigym-codex-cli
python -m pip install -e integrations/verigym-claude-cli
python -m pip install -e integrations/verigym-rtl-repo
python -m pip install -e integrations/verigym-verilog-eval-codecomplete
python -m pip install -e integrations/verigym-rtllm
python -m pip install -e integrations/verigym-synopsys
verigym suites inspect verilog-eval-code-complete
```

The VerilogEval and RTL-Repo packages contain adapters but no benchmark tasks; users provide the
upstream data explicitly. See the
[VerilogEval source guide](integrations/verigym-verilog-eval-codecomplete/README.md) and
[RTL-Repo adapter guide](docs/rtl_repo.md).

The optional [external training reference](docs/external_training_reference.md) covers
verifier-filtered strong-model SFT and a bounded rLLM/VeriGym/verl GRPO path. Training frameworks,
GPU runtimes, model weights, and credentials remain outside the evaluator package.

`pytest` runs the ordinary no-tool suite. Select an opt-in marker explicitly after provisioning
its dependency, for example `pytest -m requires_iverilog`; Docker and Yosys markers additionally
require the environment guards shown below.

`LocalRuntime` is explicitly labeled `local_trusted`. It is suitable only for trusted toy
tasks and development; it is not an untrusted-workload security boundary.

Docker isolation is optional and uses the external Docker CLI; no Docker Python package or extra
is required for the base installation. See [DockerRuntime](docs/docker_runtime.md) and the
[security policy](SECURITY.md) before running untrusted inputs.

## Stable platform contracts

New runs and experiments record source/build provenance and include hash-bound artifact
manifests. Older Milestones 0–9 artifacts remain readable with an explicit `legacy_unverified`
integrity status. Persistent JSON Schema is exported under
[`docs/schemas/`](docs/schemas/); unsupported schema versions fail distinctly from candidate and
infrastructure errors.

Reusable integrations should import [`verigym.api`](docs/python_api.md). Plugin authors should
use the versioned [`verigym.plugin_api`](docs/plugin_api.md) entry-point contract. The installable
conformance fixture proves external suite, tool, and agent discovery while core task policy and
runtime controls continue to enforce paths, visibility, budgets, and hidden-data separation.

## Cross-mode campaign summary

Completed chat, agent, and evolving-agent experiments can be combined without rerunning any model
or tool. A campaign validates the frozen input identities and writes one JSON/CSV/Markdown matrix:

```bash
cp examples/campaigns/rtllm-platform-matrix.example.yaml campaign.yaml
verigym campaign validate --config campaign.yaml
verigym campaign generate --config campaign.yaml
```

The report keeps correctness denominators, costs, usage, agent versions, and exact PPA profile
partitions separate. See [cross-mode evaluation campaigns](docs/campaigns.md).

## Five-minute batch experiment

Milestone 9 adds deterministic, resumable experiments while keeping every child as an ordinary
independently replayable VeriGym run. The included baseline expands to two toy tasks × two
scripted systems × two base seeds = eight child runs:

```bash
cp examples/experiments/toy-milestone9-baseline.yaml /tmp/toy-m9.yaml
# Edit output.root if that path already exists.
verigym batch --config /tmp/toy-m9.yaml --dry-run
verigym batch --config /tmp/toy-m9.yaml
```

The experiment root contains `reports/aggregate.json`, `reports/runs.csv`, and
`reports/report.md`. Regenerate one format without calling a model, tool, or runtime:

```bash
verigym report generate runs/experiments/toy-milestone9-baseline \
  --format markdown \
  --output /tmp/toy-m9-report.md

verigym batch --resume runs/experiments/toy-milestone9-baseline
```

Resume validates the frozen plan and reuses valid terminal children, including normal unresolved
candidates. See [experiment configuration](docs/experiments.md), the
[batch runner](docs/batch_runner.md), and [report semantics](docs/reporting.md).

Planning is capped by `execution.max_plan_items` (default 10,000; hard maximum 100,000) and fails
before creating an experiment directory or invoking a model when expansion exceeds the cap.

## Repository-level RTL repair

The first-party `repo-rtl` suite exercises frozen multi-file repository repair with three
Apache-2.0 synthetic tasks. Public feedback is available only through the hash-bound
`verigym-public-test` launcher; hidden tests remain in a separate verifier session. Candidate
repositories are frozen as deterministic unified patches and independently reapplied before
hidden verification.

Run the zero-model scripted acceptance matrix through the ordinary planner and batch runner:

```bash
verigym batch --config examples/experiments/repo-rtl-scripted.yaml --dry-run
verigym batch --config examples/experiments/repo-rtl-scripted.yaml
```

See [repository-level RTL repair](docs/repository_rtl_repair.md) for task bundles, path policy,
Docker role separation, candidate artifacts, and replay semantics.

The optional `verigym-hwe-bench` package is the first real-repository slice. It prepares only
explicitly selected official HWE-Bench PRs, keeps golden patches and testbench scripts outside the
package and agent workspace, and verifies candidates with a digest-locked per-PR image. The
executable slice covers Ibex and CVA6; it never bulk-pulls the approximately 417 published images.
See [HWE-Bench integration](docs/hwe_bench.md).

The current OpenHands HWE campaign remains pre-canary. Five public CVA6 tasks were qualified in
the sealed v28 evidence, v29 materialized the original static canary inputs, and v30 stopped during
a zero-provider Docker preflight. The Codex-free command runtime is now merged. A local v31
pre-authorization diagnostic exposed that `git diff --quiet` does not reject an untracked runner;
it was stopped before any provider call and is not reusable. The authorized v32 materialization
then stopped fail-closed during the first command-image security scan, also before any provider
call. It produced no image lock or successor canary contract and is not reusable. No provider
canary, trajectory collection, SFT, inference evaluation, or held-out access is authorized.
The generic successor guard records content-free, assertion-level command-image failures and
checks absolute filesystem byte/inode headroom before construction; this repair does not itself
authorize a new campaign identity or a retry of v32.

## Run the toy RTL task

The original deterministic scripted AgentEval remains available:

```bash
verigym run \
  --suite toy-rtl \
  --task counter-basic \
  --mode agent \
  --agent scripted \
  --runtime local \
  --output runs/
```

ChatEval uses `SingleTurnAgent`, exactly one offline model call, and zero tool access:

```bash
verigym run \
  --suite toy-rtl \
  --task counter-basic \
  --mode chat \
  --agent single-turn \
  --model static-counter-good \
  --runtime local \
  --output runs/
```

AgentEval uses the deliberately small `ReferenceReActAgent` baseline and an offline static
response sequence:

```bash
verigym run \
  --suite toy-rtl \
  --task counter-basic \
  --mode agent \
  --agent react \
  --model static-react-counter-good \
  --runtime local \
  --output runs/
```

A model client produces normalized text and usage; an agent harness converts model responses
into evaluation actions. They are selected independently and recorded separately as `model`
and `agent_harness` in `run_manifest.json`. `ReferenceReActAgent` is a testable baseline, not
a production coding-agent framework.

List the installed choices with:

```bash
verigym models list
verigym agents list
```

The offline fixtures include `static-counter-good`, `static-counter-good-fenced`,
`static-counter-bad`, `static-and-gate-mixed`, `static-react-counter-good`,
`static-react-malformed`, and `static-exhausted`. They need neither a network endpoint nor an
API key.

## Optional DockerRuntime

Build the Icarus 12 reference image explicitly; VeriGym never builds an image automatically:

```bash
docker build \
  -f docker/iverilog12/Dockerfile \
  -t verigym/rtl-iverilog:12.0 \
  docker/iverilog12
```

Run the same toy AgentEval vertical slice under fail-closed Docker isolation:

```bash
verigym run \
  --suite toy-rtl \
  --task counter-basic \
  --mode agent \
  --agent scripted \
  --runtime docker \
  --docker-image verigym/rtl-iverilog:12.0 \
  --output runs/
```

The default pull policy is `never`. DockerRuntime resolves the requested reference once, records
the actual immutable image ID and inside-image Icarus versions, and uses that ID for separate agent
and verifier sessions. Containers run non-root with network disabled, a read-only root filesystem,
dropped capabilities, `no-new-privileges`, resource limits, an allowlisted environment, bounded
output, and labeled cleanup. Docker shares the host kernel and is not a virtual-machine boundary.

Inspect a local image without pulling or building it, then replay a completed run using its exact
stored image ID:

```bash
verigym doctor --docker-image verigym/rtl-iverilog:12.0
verigym replay runs/<run-id> --verify
```

Real Docker tests are opt-in and ordinary tests need no daemon:

```bash
VERIGYM_RUN_DOCKER_TESTS=1 \
VERIGYM_DOCKER_IMAGE=verigym/rtl-iverilog:12.0 \
pytest -m docker
```

## Optional Yosys mapped-area profile

Milestone 8 adds an area-only Yosys `ToolPlugin` and a pinned educational Liberty profile. It
does not add timing, power, OpenROAD, or signoff PPA. Generic cell count remains a structural
synthesis statistic and is never presented as area. Ranked area is emitted only after functional
verification succeeds and both the candidate and suite reference RTL synthesize with the exact
same resolved profile.

Build the combined Icarus/Yosys reference image explicitly; `verigym run` never builds or pulls it:

```bash
docker build \
  -f docker/open-rtl-tools/Dockerfile \
  -t verigym/open-rtl-tools:iverilog12-yosys067 \
  docker/open-rtl-tools
```

Validate and resolve the declared profile before running a model or agent:

```bash
verigym profiles list
verigym profiles validate open-yosys-toy-area-v1
verigym profiles resolve open-yosys-toy-area-v1 \
  --runtime docker \
  --docker-image verigym/open-rtl-tools:iverilog12-yosys067
```

Run the toy vertical slice and compare only compatible, eligible runs:

```bash
verigym run \
  --suite toy-rtl \
  --task counter-basic \
  --mode agent \
  --agent scripted \
  --runtime docker \
  --docker-image verigym/open-rtl-tools:iverilog12-yosys067 \
  --toolchain-profile open-yosys-toy-area-v1 \
  --output runs/

verigym report compare runs/<left-run> runs/<right-run>
```

The scorecard reports `reference_area / candidate_area`, so values above one mean the candidate
uses less mapped area than the reference under that exact profile. This Yosys profile keeps timing
and power JSON `null`. A declared profile identifies the intended contract; its resolved hash
also covers the exact image, tools, Liberty bytes, generated script, flow, units, and reference
semantics. Results from different profile IDs or resolved hashes are deliberately incomparable.

See [Yosys synthesis](docs/yosys.md), [PPA profile semantics](docs/ppa_profiles.md), and the
[commercial-tool template policy](docs/commercial_tools.md). Real Yosys tests are opt-in:

```bash
VERIGYM_RUN_YOSYS_TESTS=1 pytest -m yosys

VERIGYM_RUN_DOCKER_YOSYS_TESTS=1 \
VERIGYM_DOCKER_YOSYS_IMAGE=verigym/open-rtl-tools:iverilog12-yosys067 \
pytest -m docker_yosys
```

## Optional RTLLM and Synopsys pilot

The `verigym-rtllm` integration exposes pinned external RTLLM `counter_12` and
`up_down_counter` tasks without redistributing the benchmark. Their chat and agent modes share a
verifier-only VCS regression. A user-supplied `synopsys.dc.synth` profile can add
correctness-gated area, cell-count, delay, WNS, explicit-activity power, and QoR summaries. The
same optional package also
provides `synopsys.formality.equivalence` for verifier-only RTL equivalence checks:

```bash
verigym suites validate --suite rtllm --source /path/to/RTLLM --variant counter_12
verigym suites validate --suite rtllm --source /path/to/RTLLM --variant up_down_counter
verigym run --suite rtllm --task counter_12 --suite-source /path/to/RTLLM \
  --mode chat --agent single-turn --model YOUR_MODEL --runtime local \
  --toolchain-profile site-synopsys-dc \
  --toolchain-profile-file /private/profiles/dc.yaml --output runs/
```

Both integrations are separate installable packages. No benchmark files, commercial binaries,
libraries, or license values are present in the core distribution. See the
[commercial-tool integration policy](docs/commercial_tools.md). The Synopsys package also provides
a restricted verifier-only MCP stdio service and `synopsys.dc.mcp` synthesis backend for a
dedicated licensed host. A sanitized client profile lets normal `verigym run` use the service; it
accepts only server-approved profiles and hash-bound RTL, not arbitrary commands or Tcl.

## External VerilogEval V2

Milestone 6 supports externally supplied VerilogEval V2 specification-to-RTL triplets. VeriGym
does not bundle, locate, clone, or download the benchmark. Validate and list a local checkout:

```bash
verigym suites validate \
  --suite verilog-eval \
  --source /path/to/verilog-eval \
  --variant v2-spec-to-rtl

verigym tasks list \
  --suite verilog-eval \
  --source /path/to/verilog-eval \
  --variant v2-spec-to-rtl
```

Run one ChatEval sample or an independent sample set:

```bash
verigym run \
  --suite verilog-eval \
  --suite-source /path/to/verilog-eval \
  --suite-variant v2-spec-to-rtl \
  --task Prob001_zero \
  --mode chat \
  --agent single-turn \
  --model openai-compatible \
  --runtime local \
  --output runs/

verigym run \
  --suite verilog-eval \
  --suite-source /path/to/verilog-eval \
  --suite-variant v2-spec-to-rtl \
  --task Prob001_zero \
  --mode chat \
  --agent single-turn \
  --model openai-compatible \
  --samples 20 \
  --pass-k 1 \
  --pass-k 5 \
  --runtime local \
  --output runs/
```

See [VerilogEval V2 adapter and pass@k](docs/verilog_eval.md) for source layout, provenance,
native verifier semantics, aggregate validity, and limitations.

## Artifacts and replay

Each run contains `run_manifest.json`, `task_snapshot.json`, `trace.jsonl`, `scorecard.json`,
`workspace_diff.patch`, a frozen `candidate/`, structured logs, and verifier artifacts.
Prompts and model events are bounded and credential-free. Hidden verifier files are never
placed in model prompts, observations, traces, ordinary agent logs, or agent workspaces.

Replay never calls the model. `--verify` reruns only the frozen candidate's verifier stages:

```bash
verigym replay runs/<run-id>
verigym replay runs/<run-id> --verify
```

## Optional OpenAI-compatible client

HTTP support is optional and is not needed by the package or test suite:

```bash
pip install -e '.[openai-compatible]'
# Set VERIGYM_MODEL_TOKEN securely in the process environment first.
verigym run \
  --suite toy-rtl \
  --task counter-basic \
  --mode chat \
  --agent single-turn \
  --model openai-compatible \
  --model-base-url https://models.example.test/v1 \
  --model-id example-model \
  --model-api-key-env VERIGYM_MODEL_TOKEN \
  --runtime local \
  --output runs/
```

Only the environment-variable name is configured; its value and authorization header are
excluded from manifests, traces, logs, and configuration fingerprints. Credential-bearing
URLs are rejected. See [Milestone 5 model and agent details](docs/milestone5-models-and-agents.md).

Provider-backed repository agents can bind the strict, multi-turn
[`repository_action.v2`](docs/repository_action_protocol.md) protocol. Its action registry,
transport, representation-only normalizer, turn budget, and state transitions are plan-bound and
replayed offline. The independent `repo-api-protocol` suite supplies three Apache-2.0 conformance
tasks without reusing the Milestone 11 task identities.

The repository-level environment supports deterministic export of bounded observable trajectories,
decomposed offline rewards, and immutable context-memory agent versions. See
[the evolving-agent bridge guide](docs/evolving_agent_bridge.md). The independently installable
[external training reference](docs/external_training_reference.md) demonstrates a sealed training
handoff, an online completion-to-reward oracle, and checkpoint provenance without embedding an RL
framework in the evaluator. Reference images and Docker
profiles are Linux-first. Quality reporting remains profile-relative educational synthesis
area, timing, and optional power—not physical PPA or signoff. Site-local commercial execution is
supported through optional plugins; proprietary tools and licenses are never distributed.
OpenROAD-based physical design,
property checking beyond RTL equivalence, distributed scheduling, built-in model-weight training,
and continuously evolving benchmark releases remain out of scope for this alpha.

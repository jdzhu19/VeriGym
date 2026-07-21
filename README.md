# VeriGym

VeriGym is an executable interoperability layer for RTL LLM evaluation. It turns a
benchmark task into a versioned task IR, runs a policy-controlled evaluation episode,
verifies the resulting RTL in a separate hidden-test context, and writes a replayable trace
and correctness-first scorecard.

```text
SuiteAdapter -> VeriTask -> Agent workspace -> Verifier DAG -> Trace + ScoreCard
```

## Install

Python 3.11+ and Icarus Verilog (`iverilog` and `vvp`) are required for RTL verification.

```bash
pip install -e .
verigym doctor
```

`LocalRuntime` is explicitly labeled `local_trusted`. It is suitable only for trusted toy
tasks and development; it is not an untrusted-workload security boundary.

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
`static-counter-bad`, `static-react-counter-good`, `static-react-malformed`, and
`static-exhausted`. They need neither a network endpoint nor an API key.

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

This repository implements Milestone 6 on top of the preserved Milestones 0–5 behavior. Docker
isolation, Yosys/PPA, broader benchmark adapters, general batch execution, external agent
frameworks, and RL integrations remain out of scope.

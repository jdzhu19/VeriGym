# VeriGym VerilogEval Code-Completion Plugin

This independently installable package adds the official VerilogEval V2
`dataset_code-complete-iccad2023` layout to VeriGym without modifying VeriGym core. It contains no
benchmark tasks. Users supply a local checkout of
[`NVlabs/verilog-eval`](https://github.com/NVlabs/verilog-eval), which is validated read-only and
bound to content, license, and Git identities.

## Install and discover

```bash
python -m pip install -e /path/to/VeriGym -e .
verigym doctor
verigym suites inspect verilog-eval-code-complete
```

## Validate and run

```bash
verigym suites validate \
  --suite verilog-eval-code-complete \
  --source /path/to/verilog-eval \
  --variant v2-code-complete-iccad2023

verigym tasks list \
  --suite verilog-eval-code-complete \
  --source /path/to/verilog-eval \
  --variant v2-code-complete-iccad2023

verigym run \
  --suite verilog-eval-code-complete \
  --suite-source /path/to/verilog-eval \
  --suite-variant v2-code-complete-iccad2023 \
  --task Prob001_zero \
  --mode chat --agent single-turn --model openai-compatible \
  --runtime local --output runs/
```

`LocalRuntime` is trusted-only. Use VeriGym's documented Docker runtime for untrusted model output.
The plugin reuses VeriGym's verifier-only Icarus tools and keeps reference RTL and testbenches out
of prompts, traces, and agent workspaces. VerilogEval remains MIT-licensed upstream content and is
never downloaded, copied, or redistributed by this package.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
mypy src
pytest
```

Set `VERIGYM_VERILOG_EVAL_CODE_COMPLETE_ROOT` to run the opt-in official-checkout conformance test.

For a credential-free, explicitly non-scored end-to-end check against official task
`Prob001_zero`, run:

```bash
python scripts/run_official_smoke.py \
  --source /path/to/verilog-eval \
  --output runs/official-smoke \
  --runtime docker \
  --docker-image verigym/rtl-iverilog:12.0
```

This known-answer smoke exists only to exercise install, execution, hidden verification, report,
and replay boundaries. It is not a model evaluation result. VerilogEval's reference environment
uses Icarus v12; other local Icarus versions are recorded but may reject upstream testbenches.

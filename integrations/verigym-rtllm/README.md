# VeriGym RTLLM Integration

This optional package exposes a pinned RTLLM pilot task through VeriGym without redistributing the
benchmark. It currently supports `Control/Counter/counter_12` at commit
`41b26896e33b536940116a975626455eed3de65e` and verifies every required upstream file by SHA-256.

```bash
git clone https://github.com/hkust-zhiyao/RTLLM.git /path/to/RTLLM
git -C /path/to/RTLLM checkout 41b26896e33b536940116a975626455eed3de65e
python -m pip install -e ./integrations/verigym-rtllm
python -m pip install -e ./integrations/verigym-synopsys
verigym suites validate rtllm --source /path/to/RTLLM --variant counter_12
```

The packaged workspace contains only a known-incomplete candidate skeleton and instructions. The
prompt, hidden VCS testbench, and normalized reference are loaded from the external checkout after
hash validation. Both chat and agent modes use the same verifier graph. A separate user-supplied
Design Compiler profile can enable hash-bound area/timing evaluation after VCS correctness passes.

RTLLM is MIT-licensed. Synopsys tools and licenses are neither included nor required by ordinary
VeriGym CI; commercial execution is site-local and opt-in.

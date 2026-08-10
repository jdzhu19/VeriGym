# HWE-Bench Ibex PR 1735 smoke

- Date: 2026-08-10
- Scope: one official task, two verifier executions, zero model processes
- Task: `lowRISC/ibex:pr-1735`
- Base commit: `23806e2ad7d0d6fab429ae227d9a45cbd42f0fb3`
- Official HWE-Bench source commit: `10c78a87e1f92695d78d15b1464a6107dcac8837`
- Image manifest: `sha256:232e68ea1da5f93158cc0f04f183822cfddda567cba2b25cecbd59af4fef88f5`
- Image ID: `sha256:56cc7b8e911d455e16bdf904dc654d36a16f6f49211e932766b6b4ade57d70f0`

The zero-model probe froze an empty, exactly replayable repository patch. Its hidden regression
reported 0/1 PASS, `test_failed`, and no infrastructure error. The official reference candidate
then reported 1/1 PASS with the same digest-locked image. Containers used `network=none`, dropped
all capabilities, and enabled `no-new-privileges`. Raw verifier output was hashed but not persisted;
a scan of the run snapshot, trace, logs, and artifacts found no hidden script fragments.

This is base-FAIL/reference-PASS qualification for the adapter boundary, not an agent-quality result
and not a full HWE-Bench campaign. The selected image was the only per-PR image downloaded: about
766 MB compressed and 1.85 GB expanded. The prepared one-task source occupied about 15 MB.

## Reproduction shape

```bash
verigym-hwe-bench prepare-source \
  --dataset <official-lowRISC__ibex.jsonl> \
  --output <prepared-source> \
  --task lowRISC/ibex:pr-1735 \
  --official-source-commit 10c78a87e1f92695d78d15b1464a6107dcac8837
verigym-hwe-bench smoke --source <prepared-source> --output <experiment-root>
```

## Sealed result hashes

- `smoke-report.json`: `d59771376fe6330ab08d3efe597abdd75c128cf4a1e2933ed2aa02939f35c454`
- reference `result.json`: `af2fee949dcd99163a7650d7dda909f2105aa363d78ee6556dba918997698205`
- base `run_manifest.json`: `95d8e5f06ded450e66bc064b8e0ea3d3766d2c9188163096c2cdfa0406ad837c`
- base `scorecard.json`: `9b3d5de5af0512e7b38fbf5b8ed3cbe7c7e04f2d518765d1a6f7c85cd661baf3`
- base `trace.jsonl`: `9880b3ce65ed6b25a76e43b566a2b9b85c2cab5bc18b29f9211710917369df66`

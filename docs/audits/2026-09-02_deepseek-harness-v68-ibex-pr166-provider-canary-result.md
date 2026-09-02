# DeepSeek Harness v68 audit of the Ibex PR-166 provider canary result

Date: 2026-09-02

## Result

The single v67-authorized DeepSeek Harness episode for
`hwe-bench/repo-repair-v1/lowRISC__ibex__pr-166` ran with seed 501 and sample index 17 after the
authorization merged and post-merge `main` run `33644917129` passed all eight required job
classes. The exact bounded public marker establishes that the provider boundary was crossed.
PR-166 is consumed, permanently frozen, and must not be retried.

The canary passed all six admission planes:

- benchmark verifier: pass;
- agent protocol: pass;
- trajectory eligibility: pass;
- infrastructure: valid;
- security: valid;
- SFT admission: pass.

This is one successful canary, not a benchmark score. No model response, public rationale text,
tool observation, private audit stream, credential, endpoint, proxy value, patch, source tree,
Docker layer, or trajectory row is committed by this audit.

## Bounded accounting and trajectory

- provider/model: `deepseek-official` / `deepseek-v4-flash`;
- provider hidden thinking: disabled;
- provider calls: 25 of 64;
- provider input/output/total tokens: 18,637 / 4,958 / 23,595;
- provider and whole-episode retries: zero;
- decision-level SFT rows: 23;
- maximum exact decision length: 24,035 of 65,536 tokens;
- overlength rows: zero;
- truncation applied: false;
- decision-only loss mask: true;
- public rationale supervised: true;
- failed-tool and content-only recovery decisions supervised: false;
- sibling targets split: false.

The exact frozen Qwen tokenizer independently re-tokenized all 23 rows after collection. Record
hashes, the dataset manifest, and loader dry-run receipts matched. The task patch is non-empty and
the official benchmark scorecard resolved true.

## Marker, security, and artifact receipts

The public trace contains exactly one provider-start marker with only these bounded fields:
`provider_request_started=true`, `provider_request_count_lower_bound=1`,
`credential_values_persisted=false`, and `content_truncated=false`.

- report hash: `53b5f60fbde1a7cc3a35dd0233bc29473d4f11b4a3c60f14eaa3a686c04e338c`;
- report file SHA-256:
  `eb10f2abec6b6c7bb1cd4fa3fceaec427b822f327fe9b05f838088a11b322870`;
- attempt file SHA-256:
  `cbab0a82f94196d153902dbfdd3fa355a38de347ebb04b7a39eb04eceeb70ea6`;
- run hash: `619dae1078c8e96d73e7b47a62b4015ae57f88bb51e054d83d32f151871e7016`;
- transcript hash: `e5146c7c0077bba00625ca844036b40a8967d980c096eba986fb52d693157eee`;
- trace file SHA-256:
  `1817e2372c884950fd37f1bfc8b229563d06dec508123f7a758b6cedbe54cda8`;
- scorecard file SHA-256:
  `a491cc0fd1dabee70ed23e929eaa4da15f4d232d48da26ab4da9db03f049c3b3`;
- security report hash:
  `0ac1f8636caa94058f30d64e2693f87727e19b748247a1e255efe3570e349072`;
- security report file SHA-256:
  `1ca131432886e7cd2df0d203d25c4feb14424803bac64c0a378d18eaac8dae85`;
- dataset hash: `86d30cfbe9a7b44ac76710dfebc965c39e4cc2b6f86ba128354ef949981cd966`;
- dataset manifest file SHA-256:
  `6588f12727b5ba213be70b130dbf4efebc1d0cf0a742e91a4676757e5a3cf0f3`;
- decision JSONL SHA-256:
  `f76658b3cacf1de344bfdfc2b14eb4ea89055153a4523f0e66e75624e5bd7e94`;
- loader dry-run file SHA-256:
  `7c32cc7d2271aab75d245a84e50459f517cef8289a9f81746b194dbf0a7c16e3`.

The committed security scan gate is represented only by its sanitized receipt and hash. The two
private launch sidecars were mode 0600 and a direct value comparison found neither provider
credential nor endpoint. Command and verifier execution remained `network=none`. The VPN state and
independent public-image downloader were not changed.

## Collection disposition

The successful trajectory remains immutable under
`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v67-ibex-pr166-provider-canary-v1` and
may later be imported without re-execution after a separate formal-readiness audit. This result
does not authorize or start formal collection or training:

- `formal_collection_allowed=false`;
- `formal_collection_started=false`;
- `collection_started=false`;
- `training_started=false`;
- `production_training_ready=false`.

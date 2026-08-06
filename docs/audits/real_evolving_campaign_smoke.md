# Real evolving campaign smoke evidence

Date: 2026-08-06 (Asia/Shanghai)

This bounded experiment replaces the earlier scripted evolving control with a real DeepSeek,
RTLLM, VCS, and Design Compiler flow. It demonstrates the complete VeriGym platform matrix:
ChatEval, AgentEval, and EvolvingAgentEval. It is a platform smoke, not a full RTLLM benchmark or
a statistical performance claim. Review the generated [JSON](real_evolving_campaign_smoke/campaign_report.json),
[CSV](real_evolving_campaign_smoke/campaign_report.csv), and
[Markdown](real_evolving_campaign_smoke/campaign_report.md) reports.

## Frozen evolving flow

- Experiment code was commit `a342dccc6503d7c2c06d81f32174923ac8449d02`; final reporting
  used clean commit `3d40a9146b8f2e4653454e93fd01ac3f35d676ad`.
- RTLLM was pinned at `41b26896e33b536940116a975626455eed3de65e`. Development used
  `rtllm/up_down_counter`; held-out evaluation used `rtllm/counter_12`.
- The resolved local runtime, tool policy, DeepSeek `deepseek-v4-flash` model configuration,
  `react-context` implementation, and version-neutral prompt contract were identical across v0
  and v1. Execution order was counterbalanced over three samples per version.
- The single development episode resolved in five model calls, 15,326 tokens, and 37.114 s. One
  separate memory-builder call used 1,743 tokens and 11.186 s. It produced memory hash
  `b524d6418682ac36147be41f87ef2c814cb8c56fa9a26164574a729040247fb8`.
- v0 hash is `9151f970e75169aeec1c9c244f7accb93f59372436efc59b112745899242a5ae`;
  v1 hash is `1218b64d9a627dd45c975590ef423f57a79433a94cdbbec08df98a754b9d873b`.
  The [update](real_evolving_campaign_smoke/agent_update.json),
  [memory-builder result](real_evolving_campaign_smoke/memory_builder_result.json), and
  [sanitized training summary](real_evolving_campaign_smoke/sanitized_training_summary.json)
  preserve their lineage without raw trajectories.
- The post-v1 [split](real_evolving_campaign_smoke/full_task_split.json) and
  [contamination scan](real_evolving_campaign_smoke/contamination_scan.json) bind four training
  and four held-out files. The scan passed with zero hard findings.

## Held-out and commercial-tool results

All six held-out runs were evaluable and resolved. Both v0 and v1 achieved pass@1/2/3 of `1.0`.
v0 averaged 14,848 tokens, 3.667 tool calls, and 138.645 s; v1 averaged 16,354.667 tokens,
4 tool calls, and 129.454 s. Thus accuracy delta was zero, v1 used 1,506.667 more tokens on
average, and observed wall time was 9.191 s lower. The
[evolving report](real_evolving_campaign_smoke/evolving_evaluation.json) explicitly records
`establishes_general_improvement=false`.

Every original held-out run passed VCS, candidate DC, reference DC, and quality projection. One
sample per version was also verifier-only replayed; both replays passed VCS and DC in about 108 s
without a model call. Tools were VCS `V-2023.12-SP2-2` and Design Compiler `T-2022.03-SP1`.
All four campaign PPA rows share exact partition
`cf70ac24a484bdcea8b2a95038f2ce6f21aa204789484cdfb5c0b38aa8f00b91`.
Candidate/reference area was `153.8976/153.8976 um^2`, delay was
`0.810319/0.810319 ns`, and WNS was `0.0/0.0 ns`.

## Integrity and limits

Campaign `campaign-9c68cca77d7a031c` has report hash
`9b791db711cee6b49f12caec097e185a6105397b6d0597d63c310ef70e5fce0a`. Two independent
offline generations were byte-identical:

- JSON: `cbc929a5f074b453dfb9fc23e6f038aa62b3df53458de7442d27df8ee00a793a`
- CSV: `2f942795531c2b738dd66fe5234d74c16044a2f0aea37cdbe690a92ba1dd5f59`
- Markdown: `ec8cac7032dc40a7ee91f453c0118c51e5c052470efbadb3d5f238a856df105c`

Reporting made zero model and zero tool calls. Committed evidence contains no credentials, license
values, commercial-library bytes, raw host paths, run workspaces, or tool logs. Provider cost was
not available. The one-task development/held-out counter study is intentionally minimal; it does
not establish general improvement, cross-family transfer, or signoff-quality timing.

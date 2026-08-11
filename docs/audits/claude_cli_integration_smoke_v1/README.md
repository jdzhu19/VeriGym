# Claude CLI integration development smoke v1

This audit records a non-held-out integration qualification, not a benchmark score. The task was
`toy-rtl/counter-basic`, seed 3, using the locally pinned Icarus 12 Docker image with task commands
and verification on `network=none`.

The successful run used Claude Code 2.1.168 as a multi-turn host control plane, requested
`deepseek-v4-flash[1m]` with explicit `max` effort, and resolved the gateway as the distinct
`anthropic_auth_token_env` semantic. Claude reported a 1,000,000-token context window and a
32,000-token per-response upstream output ceiling. VeriGym configured no internal turn,
model-call, model-token, or dollar limit.

The final run completed in 17.40 seconds with 3,098 input and 695 output tokens. Seven MCP calls
crossed the private broker, one file was written, the ordinary hidden verifier passed 1/1 tests,
offline reverification passed, and the context-aware scan found no hard secret leak or scanner
error across 45 persisted files. Raw prompts, model messages, reasoning, tool payloads, stdout,
credentials, and proxy values are not included here.

Qualification used three provider calls while the integration was being debugged. The first was
invalidated by an identity-accounting schema error. The second was invalidated after an absolute
command path was rejected; its candidate happened to pass the hidden test, but that does not turn
the sample into a valid result. Both development runs remain only under the experiment root. The
third run is the passing qualification recorded in `qualification.json`.

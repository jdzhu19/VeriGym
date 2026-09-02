# OpenHands v58 Ibex PR-54 provider-canary authorization

## Decision

Authorize exactly one OpenHands SDK 1.42.1 provider episode for public Ibex PR-54 after this
authorization merges and its post-merge `main` workflow passes all eight required job classes.
This authorization does not start formal collection or training and does not authorize a retry.

The predecessor qualification was merged as `0a71773a3acb52414739bebbb6e4e73a7d2ab37c`.
Post-merge `main` run `33618065213` passed quality, reproducible-build, package,
Python 3.11/3.12/3.13, OpenHands 3.12, and Docker external-agent security.

## Frozen episode

- task: `hwe-bench/repo-repair-v1/lowRISC__ibex__pr-54`;
- role: training canary;
- model transport: `openai/deepseek-v4-flash`;
- provider hidden thinking: disabled;
- seed: 498;
- sample index: 14;
- temperature: 0;
- provider calls: at most 64;
- provider tokens: at most 1,000,000;
- context: 65,536 tokens;
- output: 2,048 tokens;
- provider retries and whole-episode retries: zero.

The v23 protocol uses provider-default `auto` for ordinary turns. It permits public concise
rationale and one or more typed sibling calls. All siblings are validated before ordered serial
dispatch. A single same-session content-only recovery uses `required`; recovery and failed-tool
decisions remain context-only and are not supervised. Private reasoning fields fail closed.

## Frozen public environment

- task hash: `b03b430845b6bb97a0b0443c52d337817b4ff33e3cc1b3ea15800bb8bfb4a14a`;
- source hash: `5393fbc4261f1a8e19ba7af7b1501367a6c1f3c28bed72f556291f734d095914`;
- command-image lock: `3f7e090239e1230054620a7a51330a16bef54e084a395dcd294e60de003bb798`;
- command image: `sha256:6f88fdae127f75326407b4ebff529fea5f87aeb64997970d4408678fab942c3b`;
- verifier image: `sha256:a35075b506d4d8b4e9434e31f38ee0699afdb18f7119e324d49bee60565f5bfa`;
- security scan: `1bd004e75bdf245596bd1bcd3021d184123203711c30fda24969d040656ed281`;
- command and verifier runtime network: `none`.

The preflight must revalidate the source lock, command lock, security scan, local image identity,
control-plane paths, command container startup, and adapter bridge before the provider service is
constructed. Credentials stay in environment variables and are neither printed, persisted, nor
hashed. A post-run artifact scan rejects any concrete provider value.

The first local zero-call preflight safely stopped because the fixed broker control directory did
not yet exist. The runner now creates that exact non-symlink directory before resolving it. A fresh
preflight then passed `control_plane`, `command_image`, and `adapter_start`; its receipt hash is
`6609c39274720841c945e7827b2a8b5b32b3c2ba302fc3f700a7cca1586c9474`, with zero provider calls.

## Admission and stop policy

A usable trajectory requires all six planes: benchmark verifier, v23 protocol, trajectory,
infrastructure, security, and SFT admission. Every supervised decision must be exact-64K eligible,
untruncated, decision-only loss masked, and retain its complete sibling target. Public rationale is
supervised; content-only recovery and failed-tool decisions are not.

Any pre-provider infrastructure failure leaves PR-54 unconsumed. Once the provider episode starts,
PR-54 is frozen regardless of outcome. A task, no-progress, stuck, empty-patch, verifier, protocol,
security, trajectory, or exact-64K failure cannot be retried under v58. Formal collection,
collection, SFT training, and production readiness remain false even if this canary succeeds.

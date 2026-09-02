# RTLLM asynchronous FIFO behavior-contract audit v2

Date: 2026-09-02

This audit is diagnostic only and makes no benchmark-score claim. It records a zero-model offline
reclassification; no historical episode, task ID, candidate, or v1 verifier identity was changed.

## Contract difference

The v2 derived specification fixes `WIDTH=8` and `DEPTH=16`. A write is accepted on `wclk` only
when `winc && !wfull`; a read is accepted on `rclk` only when `rinc && !rempty`; accepted values
leave in FIFO order. Both domain resets are active-low and asynchronous. Read data follows the
synchronous RAM read behavior. A one-domain reset invalidates the logical queue contents, so
normal recovery requires coordinated reset.

The old verifier compared `wfull`, `rempty`, and `rdata` against golden per-cycle trace files. That
made legal synchronizer depth, pointer-registration, and flag-registration choices observable.
The v2 checker instead owns an independent queue scoreboard and allows a remote pointer effect to
become visible within two through four target-clock edges. It covers offset clock phases,
concurrent traffic, wrap-around, full/empty blocking, and coordinated/domain reset. The v2 task
mounts one verifier-only checker and does not mount `wfull.txt`, `rempty.txt`, or `tdata.txt`.

## Frozen identities and results

- Public behavior smoke SHA-256:
  `8cd60f6b52ba4cf4e22d8961c15ce59bc2798f2b23c520f581b552a0f02917c8`.
- Hidden behavior-checker SHA-256:
  `055ed0703bda4ce358fdc57b739b89388c26a666e1b39a2aa0b371aa23ffd1f5`.
- Reference: accepted by both independently authored public and hidden behavior checks.
- Twelve FIFO mutation controls: rejected by both checks (24 expected verdicts).
- Nine frozen historical FIFO candidates: all nine accepted by the new hidden checker; their RTL
  digests were distinct, and at least three therefore satisfy the independent-implementation gate.
- Reclassification: nine old-checker false rejections and zero behavior-contract design
  rejections. These are offline verdicts, not retries or new model samples.
- VCS/MCP qualification repeated the behavior classification through the new commercial profile:
  one reference accepted, twelve controls rejected, and all nine historical candidates accepted
  in 22 jobs for the initially published v2 control sources. It made zero model calls and zero
  automatic retries, and private staging cleanup reported no residual paths.

The final feedback-v2 source-hardening pass changed the eight task-keyed FIFO control byte streams,
but not the behavior checker, reference, historical candidates, task ID, or profile identities.
All 13 current FIFO cases passed the public and hidden Icarus 12 matrix. A commercial replay of the
current eight source changes stopped during profile resolution, before any VCS job, because the
host root filesystem was full. The earlier 22-job result remains immutable; the stopped replay is
an infrastructure event and is not counted as a retry or candidate verdict.

The finite tests establish a measurable mutation and behavior-coverage threshold; they do not
claim exhaustive correctness.

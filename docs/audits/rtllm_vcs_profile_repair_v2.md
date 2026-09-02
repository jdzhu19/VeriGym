# RTLLM VCS/MCP profile repair audit v2

Date: 2026-09-02

The observed failure was a server/client canonical declared-profile and contract-hash drift. The
VCS `-ID` probe remained healthy at `V-2023.12-SP2-2_Full64`; the repair is therefore classified as
profile identity drift, not a VCS or license failure. Frozen v1 files were not edited.

Three new v2 identities were issued and resolved twice. Site paths, wrapper bytes, hidden checker
contents, environment values, and commercial assets are omitted from this audit.

| Profile | Server declared | Contract | Transport | Server resolved | Client resolved |
| --- | --- | --- | --- | --- | --- |
| counter | `edffa04ba2e8…ffd5` | `707454f1eea6…ce3` | `e794a0f9fd51…100c` | `365773c2689a…88a6` | `79ef5d9e05d9…7605` |
| up/down | `9b5bb2f6acd0…64e9e` | `7c257cb831f3…762d` | `fa8001566157…ad38` | `283d1fb3aa80…5746` | `c67ae0c08afe…aca` |
| FIFO behavior | `db86d6e3fe7d…613e1d` | `9ccd4cb4ac7d…bd1d` | `db04ad497943…55ba` | `482d5641f9ff…79d71` | `0c814c8dedaf…b71` |

The client maps approved mismatch failures to stable safe reason codes and returns no verifier
path or hidden content. `VERIGYM_VCS_MCP_PROFILE_V2` now takes precedence in doctor/health lookup;
the v1 environment name remains only as a historical fallback.

The FIFO v2 client then resolved stably to `0c814c8dedaf…30b71` and completed the independent
behavior-checker qualification: 1/1 reference accepted, 12/12 mutation controls rejected, and 9/9
distinct historical candidates accepted. All 22 VCS jobs used the same fixed profile, made no
model calls, made no automatic retries, and left no private staging paths. This commercial rerun
confirms the new checker path without changing the earlier Icarus reclassification.

A default `verigym doctor` run with only `VERIGYM_VCS_MCP_PROFILE_V2` configured reported
`synopsys.vcs.mcp` healthy. No legacy environment alias was needed for that check.

During final source-hardening requalification on 2026-09-03, the frozen transport still listed the
same server identity but its VCS identity probe could not complete after the host root filesystem
reached full capacity. Resolution stopped before a simulation job. A direct `VCS -ID` probe using
an existing dedicated `/data` scratch root still returned `V-2023.12-SP2-2_Full64`, confirming an
infrastructure-local temporary-space failure rather than license loss or profile drift. The client
and direct VCS launch paths now forward only a pre-existing, non-symlink, writable `TMPDIR` chosen
by the trusted process environment; verifier requests still cannot select it. The already frozen
wrapper continues to load its deployment snapshot and was not modified in place.

# DeepSeek Harness v187 audit of the v186 diagnostic-context refinement

Date: 2026-09-06

## Decision

Freeze the sole v186 invocation as a successfully completed, task-free diagnostic refinement.
Its bounded classifier uniquely identified the missing executable as the closed-dictionary enum
`git` in the fixed `posix_sh_command_not_found` context. The corresponding result category is
`missing_builder_prerequisite`. Do not retry, resume, reconstruct, or relabel v186.

This evidence is sufficient to authorize a separately versioned, minimal builder-dependency
repair whose only functional change is making a locked `git` executable available while building
the otherwise exact open-tool image. It is not evidence that any other unavailable probe command
is required. The repair must lock the git package closure, source, version, binary and archive
hashes; must use a new dependency-only builder and fresh one-use resource identities; and must run
the final image build offline with the exact v186 Dockerfile and upstream inputs. If those inputs
are not already complete locally, their acquisition requires an explicit, bounded command whose
route is verified not to use the VPN, using `verigym-hwe-net` rather than Docker's broken default
bridge. No partial input or implicit registry download is allowed.

V187 does not authorize HWE image import, PR-1816 source preparation, either verifier route, a
model process, a DeepSeek call, or a qualification contract. Those remain behind a successful
repair result, a later independent audit, and a new post-merge `main` run with all eight workflow
classes green. PR-1816 remains task- and provider-unconsumed. Formal collection, SFT mixing,
training, GPU work, benchmark-score claims, and production readiness remain false.

## Authorization and execution binding

The v186 implementation commit is `1f77248946c3e72fcc060079d1b8b96e28d9e58c`, merged by PR
213 as `acf2d18ef40a184728d84e10b59f5a5fb95b5d9e`. Post-merge `main` run `34000582990`
completed all eight workflow classes successfully before the sole invocation.

The manifest content hash is
`ecd09827a84b35c9284ee80253575d374642d683b1dd5f54099936db39497cbc`; its file SHA-256 is
`dc09a2ee38dac33a7678b2ab2710e39752ef59f1522cfcd9f096cab4231b20d5`. The runner SHA-256 is
`69a8529358a24aea7501809bc1d6860e93666346e23b226b7db6e73cedd5a875`; the v186 contract
SHA-256 is `83031172d711da5d7210b4aac9b68599299bc5cc1235046c47ce31343efb0b8e`.

The launcher was invoked exactly once from clean merged `main` with the expected seven unrelated
user-owned untracked files. It revalidated the complete v184 result, the v185 audit, the exact
v184 Dockerfile, accepted open-tool base, local builder archive, Verilator and ripgrep archives,
and Docker 23.0.6 DinD identity. The headroom receipt recorded 9,740,783,616 available
control-root bytes against a 9,663,676,416-byte threshold and 35,933,103,652,864 available
`/data2` bytes against a 53,687,091,200-byte threshold. All bulk state was placed on `/data2`.

The control-root margin at launch was only 77,107,200 bytes. A post-cleanup observation found the
available value below the 9-GiB threshold. That later observation is not part of the sealed v186
headroom receipt, but it means no successor execution may start until its own fresh, absolute
capacity gate passes. The threshold must not be lowered to accommodate the repair.

## Bounded diagnostic result

The isolated DinD daemon passed mount inspection with outer `network=none`, no host Docker socket,
and no provider or proxy environment. The accepted open-tool image and dependency-only builder
were the only imported images. The exact final Dockerfile ran with `--network none`,
`--pull=false`, plain progress, a 3,600-second timeout, and a 16-MiB aggregate output bound.

The client returned 1 within both bounds. It produced zero stdout bytes and 105,853 stderr bytes.
The active-value and secret-marker scan passed. Only the empty-stdout SHA-256
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` and safe stderr
SHA-256 `60c6d9f71fd65e9d01ec954bd41a2e008aff6581357116accba90118c89de133`
were retained; no raw bytes are recoverable.

In-memory parsing found exactly two contextual markers, both in the fixed POSIX-sh grammar. It
found no bash, Make, unscoped, mixed, or unknown-dictionary marker. Both occurrences resolved to
one closed-dictionary enum, `git`. The isolated 119-command builder probe independently recorded
`git=false`, so `command_available_before_build=false`. The probe ran mount-free with
`network=none`, a read-only root, non-root identity, cap-drop `ALL`, and no-new-privileges. Its
hash is `7899880f5dacc13ee69d4f8c0cbfb7b59e3ba272482f6825e17313d359a70832`.

Other dictionary commands were also absent, but the bounded build emitted no accepted marker for
them. V187 therefore neither classifies them as prerequisites nor authorizes adding them. The
fixed diagnostic hash is
`732b4302324ddd96b0b619bc2f50c6c8d03b5c29cddb99312fbed9d920eb7225`; terminal report hash
is `071037cbd272918abf29ea00571e2cef8f2b836659884479af07aaaf320b7150`.

## Cleanup and frozen evidence

The inspected cleanup helper used `network=none`, a read-only root, one writable exact backing
bind, cap-drop `ALL`, only `CHOWN`, `DAC_OVERRIDE`, and `FOWNER`, and no-new-privileges. It removed
both named volumes, all v186-owned containers, the backing parent, scratch, and any final inner
image. Independent post-run inspection found none of those resources or the final host image.
Cleanup hash:
`f825e253b4a9d0a8a855223049b860ebbedff259351dcb90b92b125b9c43f3b1`.

The frozen result root is:

`/data2/jiadongzhu/Agent/experiments/deepseek-harness-hwe-v186-diagnostic-context-refinement-v1`

It has tree hash `1ccc0e8757f06da4c064939b7d52d375855ca5fcd7a3374855f6f8232689f8b7`,
mode `0700`, owner UID/GID `1004:100`, and exactly nine ordinary mode-`0600` files:

- `cleanup.json`: `8b6c41594d1e004d2327878c61c287dc953051a99f0db71bfd7527a2a0e9cb5d`;
- `command-dictionary-probe.json`:
  `c081f0565f18d677d81e366cae92a2fe3b5bc6bf0b3d946f17761a1c94e8026d`;
- `diagnostic-context.json`:
  `64a7cdf7badb493c3b7009339c3485dd19a21062858242e7013b18cdd5b0280d`;
- `dind-runtime.json`:
  `41d23fd6bf1bd02b39231a323a7631b3299e27cc1db2bfc84bd70f6f1f3302a0`;
- `headroom.json`: `f135387d73d62bf9299cc9c975d634dcb09ad07a5f9f134c989ef71b2afd55ff`;
- `local-builder-archive.json`:
  `3f2579abf4eb5da2d9886735489da1046b7f9855af9cd5ce3b85c149e0a93e68`;
- `local-builder-binding.json`:
  `d16525a88d4fc7a0aca121fe2df42792f3dc5a1d34c41fba3823615c37720fec`;
- `materialization-progress.json` and byte-identical `zero-provider-report.json`:
  `1a5f1e1dda5844adc4d50a907d413f6a97d3dcfd039b9605308831c8ffe3c496` each.

All nine embedded receipt, diagnostic, cleanup, probe, and report hashes validate. No raw output,
raw matching line, arbitrary token or token hash, path, argv, or environment name/value was
persisted. There is no final-image lock, security scan, HWE archive receipt, task source,
candidate, verifier result, trajectory, qualification contract, or SFT-admission receipt.

## Narrow successor boundary

After this audit is merged and a new post-merge `main` run passes all eight classes, a new v188
identity may implement and invoke one task-free, zero-provider minimal repair. Its dependency-only
builder must add only the locked git package closure; its final image build must reuse the exact
v186 Dockerfile, Verilator 5.008, Icarus 12, Yosys 0.67, ripgrep 15.2.0, accepted open-tool base,
and build bounds. It must use fresh `/data2` output, scratch, backing, volume, image, and archive
identities and satisfy a new 9-GiB control-root and 50-GiB `/data2` headroom receipt.

Any required acquisition must be isolated from the final build, checksum-verified, bounded to the
new builder input, and proven to bypass the VPN without printing proxy values. The final build and
all probes remain `network=none`; cleanup and terminal-report requirements remain unchanged. A
successful build must undergo the existing v2 image security scan and lock every image, tool, and
package identity. A failure must retain only bounded, secret-scanned classifications and clean all
owned resources.

V188 may not import an HWE image, prepare PR-1816, run a verifier, start a model, call a provider,
publish a qualification contract, or begin collection/training. Only a later independent audit
may interpret its result and decide whether to authorize the PR-1816 dual-route qualification.


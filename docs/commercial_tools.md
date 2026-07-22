# Future commercial synthesis profiles

Milestone 8 provides documentation and a non-executable template only. It does not implement a
licensed-host runtime, vendor tool plugin, license integration, commercial execution, or signoff
validation. VeriGym does not distribute proprietary executables, libraries, PDKs, vendor scripts,
credentials, license files, or license-server addresses.

The example at `examples/profiles/commercial-synthesis.example.yaml` shows the intended contract.
A future site integration would provide, outside the repository:

- a site-owned profile ID/version with `site_specific` or `private` reproducibility scope;
- executable/version checks and an isolation/runtime declaration;
- hashes and re-resolution locators for user-owned scripts, Liberty files, and PDK inputs;
- an allowlist containing only license-configuration environment-variable *names*;
- a bounded, versioned machine-readable parser/output contract;
- explicit metric units/semantics and a frozen reference strategy.

Secret values must be supplied by the site's execution boundary at run time. They must never enter
YAML, command arguments, manifests, traces, logs, diagnostics, hashes, or artifacts. A portable
record may state that an allowlisted variable name was available, but it must not record its value.
Private asset bytes should not be copied into public run bundles; retain only logical identity and
cryptographic hash unless the owner explicitly configures a private artifact store.

Results are labeled site-specific/private. Absolute results are comparable only when the complete
resolved profile identity matches. A matching profile ID is not enough if executable identity,
script bytes, Liberty/PDK bytes, runtime, units, flow, or reference semantics differ. Cross-profile
conversion or ranking is unsafe and must be refused.

Parsing a vendor report establishes only that the output satisfied the declared parser contract.
It does not make a flow signoff-quality, validate constraints, prove library/PDK suitability, or
certify the vendor tool. Timing, power, physical design, corners, derates, and signoff remain
outside Milestone 8.

Before a future implementation can execute this template, it needs a separately reviewed runtime
and threat model, secret transport, license-failure classification, tool-specific plugin and
parser, immutable identity/resolution policy, artifact-retention policy, and opt-in tests at the
owning site. The checked-in example deliberately contains placeholders and cannot be registered or
executed.

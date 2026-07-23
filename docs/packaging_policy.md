# Packaging policy

The wheel contains Python modules plus explicitly declared first-party runtime assets: toy tasks,
the VerilogEval adapter metadata, built-in profiles, and the educational toy Liberty file. The
sdist additionally contains source, tests, documentation, Docker recipes, scripts, and the
installable plugin-conformance fixture.

Included fixtures are small, synthetic, and explicitly licensed. Packages must not contain an
external VerilogEval checkout, commercial binaries, PDKs, proprietary cell libraries, model
weights, credentials, audit runs, caches, virtual environments, Docker layers, private
configuration, or host-specific absolute paths. User-supplied benchmark and licensed-tool assets
are referenced only by safe logical identity and hashes.

Runtime dependencies have lower and upper bounds; optional HTTP support is isolated in the
`openai-compatible` extra. Package metadata uses SPDX `Apache-2.0`, includes `LICENSE` and
`NOTICE`, declares Python 3.11+, and publishes repository/documentation/issue URLs.

Before a candidate build, inspect both archive member lists, validate `METADATA`, scan names and
text for forbidden paths/secrets, install the wheel in an isolated environment, run `pip check`,
and compare two builds made with the same `SOURCE_DATE_EPOCH`.

The local audit driver is `python scripts/run_release_audit.py --output release_audit`. It never
publishes, tags, pushes, pulls images, or downloads a benchmark. Existing output is preserved
rather than overwritten, and unavailable required resources remain blocked/skipped evidence that
fails the candidate gate.

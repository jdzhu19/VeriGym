# Build and source provenance

New run and experiment manifests include `BuildProvenance`. In a checkout, VeriGym records the
verified Git commit, a deterministic SHA-256 over tracked and non-ignored project inputs, file
count, and dirty state. It uses Git plumbing through argument arrays; it never substitutes a
branch name or best-effort environment variable for a commit.

The PEP 517 backend writes the same data into `_build_provenance.json` while building a wheel or
sdist. Installed wheels load that embedded record and add a hash of installed `METADATA`.
Unknown provenance remains representable for old/unusual installations, but it fails the
release-candidate gate.

`SOURCE_DATE_EPOCH` fixes archive timestamps. Wheel members and sdist tar/gzip metadata are
normalized and ordered. `docs/audits/reproducible_build.json` is intentionally excluded from the
source identity and sdist because it contains the hashes of the archives it audits; substantive
source and documentation remain included.

The source-tree identity describes exact local bytes, not remote service behavior. Dirty builds
are labeled honestly. Remote model IDs and provider fingerprints are observations with an
explicit mutable-service scope, not an immutable reproduction guarantee.

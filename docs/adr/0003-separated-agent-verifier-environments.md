# ADR 0003: Separate agent and verifier environments

- Status: accepted

## Decision

Agents receive only public/editable assets. Submission freezes a canonical candidate, which is
copied into a distinct verifier session where hidden assets are staged. The live agent workspace
is never reused for verification.

## Consequences

Hidden lookup and post-submission mutation are blocked by construction. Verification costs an
extra session and copy. `LocalRuntime` still trusts the host; Docker containment is not a proof
against a hostile kernel or daemon.

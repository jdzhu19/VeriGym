# ADR 0001: Immutable plans and explicit aggregate denominators

- Status: accepted
- Scope: Milestone 9 experiment execution and reporting

## Context

A loop over mutable CLI arguments cannot prove what a long experiment intended to run. Completion
order, changing source trees or image tags, retries, partial artifacts, and ambiguous “success
rate” denominators can silently change conclusions. A separate batch evaluator would also drift
from the replayable single-run contract.

## Decision

Before execution, VeriGym expands strict configuration into a complete, canonically ordered plan.
Each item binds all evaluation-relevant identities and receives a content-derived ID; the ordered
plan, normalized config, task set, and source receive separate hashes. Runtime image/profile/source
identities are frozen before model lookup. Execution calls the existing Python orchestrator, and
every child remains an ordinary run. Mutable parent state is an atomic audit/index layer, not an
alternative source of scoring truth.

Resume reuses only a valid terminal child whose manifest, scorecard, files, and identities match
its plan item. Corrupt attempts are preserved and excluded. Reports are rebuilt offline from
validated artifacts.

Aggregates always retain coverage and explicit numerator/denominator pairs. “Resolved over
evaluable,” “resolved over planned,” and “evaluation completion” remain different measures.
Zero denominators are null. Canonical pass@k is per exact base-seed sample group and invalidates on
infrastructure failure. Area is correctness-gated and exact-profile-partitioned. No universal score
combines correctness, cost, and area.

## Consequences

Planning does more work up front and immutable changes create a new experiment. Parent JSONL is
rewritten atomically because experiments are intentionally local and bounded in this milestone.
In return, scheduling order cannot change identity, valid failures are not accidentally retried,
partial attempts remain auditable, and every published percentage exposes its population.

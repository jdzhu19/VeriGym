# ADR 0009: Explicit persistent-schema compatibility

- Status: accepted

## Decision

Every persistent top-level object has a schema version. Readers dispatch supported versions
before strict model validation, reject unknown majors, and add minor compatibility only through
reviewed code. Writers emit one current form.

## Consequences

Candidate and infrastructure failures cannot masquerade as format errors. Prior Milestones 0–9
artifacts stay readable through narrow compatibility paths rather than permissive parsing.

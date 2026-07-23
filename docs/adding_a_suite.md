# Adding a suite

Implement `SuiteAdapter` using types from `verigym.plugin_api`, then register it in
`verigym.suites`. A suite must provide a versioned descriptor, deterministic discovery,
`VeriTask` loading, separated public/hidden asset resolution, and read-only source validation.

Use stable task IDs such as `my-suite/task-001`. Reject incomplete, ambiguous, linked, oversized,
or escaping input before a model call. Never put reference RTL or hidden tests in a task prompt,
trace, candidate directory, wheel, or report.

Add conformance tests for discovery ordering, hashes, known-good and known-bad candidates, hidden
separation, source mutation, replay, and licensing. External datasets remain user-supplied unless
redistribution is explicitly documented. The conformance plugin provides a minimal first-party
example; it is not a production benchmark.

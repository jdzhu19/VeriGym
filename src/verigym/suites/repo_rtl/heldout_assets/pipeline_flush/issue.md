# Repair complete pipeline flushing

Asserting `flush` for a clock edge must discard all valid items held anywhere in the two-stage
pipeline. No item present before that edge may later appear with `out_valid`. Data entering while
flush is asserted is also discarded. Normal two-cycle transfer behavior must resume on following
cycles, and reset must clear both stages.

The repair requires consistent behavior in the reusable stage and its top-level wiring. Modify only
the editable RTL sources and use the public-test launcher for visible validation.

# Hold must dominate a simultaneous load

The visible `valid_register` incorrectly replaces its data when `hold` and `load` are asserted on
the same rising edge. Repair the sequential priority so reset remains highest priority, `hold`
preserves both outputs, and a load updates the data and marks it valid only when not held. Keep the
module interface unchanged.

# Counter must wrap instead of saturating

The four-bit enabled counter in `repository/rtl/wrap_counter.sv` currently
saturates at `4'hf`. Repair it so an enabled increment wraps naturally from
`4'hf` to `4'h0`. Preserve the active-high synchronous reset and the
enable-low hold behavior. Do not change the module interface.

# Rotation does not advance beyond the latest winner

When multiple clients remain asserted, the same client is granted repeatedly. The arbiter should
start the next arbitration at the client after the latest winner, with wraparound. Preserve the
one-hot grant contract, request masking, idle behavior, and active-low synchronous reset.

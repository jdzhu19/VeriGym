# Arbiter reset and recovery are incorrect

The two-request round-robin arbiter in `repository/rtl/rr_arbiter.sv` may
assert a grant while reset is active and chooses the wrong first winner after
reset. Repair reset behavior so grant is zero during reset and simultaneous
requests choose requester 0 first after recovery. Thereafter simultaneous
requests must alternate fairly. Preserve single-request behavior and the
module interface.

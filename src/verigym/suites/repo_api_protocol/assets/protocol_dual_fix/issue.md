# Restore reset polarity and wrapping accumulation

The accumulator repository contains two independent visible defects. The top-level active-low
reset is wired to the core with the wrong polarity, and the core saturates instead of using normal
eight-bit wraparound arithmetic. Repair both RTL files. Preserve interfaces, synchronous clear,
and enable-low hold behavior.

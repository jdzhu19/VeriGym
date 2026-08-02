# Flush must invalidate the buffered pipeline word

The single-stage pipeline keeps `out_valid` asserted when a synchronous `flush` arrives while the
downstream is stalled. Repair the stage so reset or flush invalidates the buffered word before any
load/hold decision. Keep the ready/valid interface and top-level wiring unchanged.

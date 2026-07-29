# Repair pipeline stall and backpressure handling

The two-stage ready/valid pipeline loses throughput and can mishandle a stall.
`repository/rtl/pipeline_stage.sv` must accept a replacement item when its
current output is consumed, and `repository/rtl/pipeline_top.sv` must connect
the first stage's backpressure to the second stage rather than directly to the
external sink. Preserve ordering, data, and all module interfaces.

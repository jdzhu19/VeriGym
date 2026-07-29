module enable_gate (
    input  logic enable,
    input  logic inhibit,
    output logic gated_enable
);
    assign gated_enable = enable & ~inhibit;
endmodule

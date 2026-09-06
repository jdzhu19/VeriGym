module multi_pipe_8bit #(
    parameter size = 8
) (
    input wire clk,
    input wire rst_n,
    input wire [size-1:0] mul_a,
    input wire [size-1:0] mul_b,
    input wire mul_en_in,
    output reg mul_en_out,
    output reg [(size*2)-1:0] mul_out
);
    // Implement the complete design here.
endmodule

module RAM (
    input wire clk,
    input wire rst_n,
    input wire write_en,
    input wire [7:0] write_addr,
    input wire [5:0] write_data,
    input wire read_en,
    input wire [7:0] read_addr,
    output reg [5:0] read_data
);
    // Implement the complete depth-8, width-6 dual-port RAM here.
endmodule

// SPDX-License-Identifier: Apache-2.0
module valid_register (
    input  logic       clk,
    input  logic       rst,
    input  logic       load,
    input  logic       hold,
    input  logic [7:0] data_in,
    output logic [7:0] data_q,
    output logic       valid_q
);
    always_ff @(posedge clk) begin
        if (rst) begin
            data_q <= 8'h00;
            valid_q <= 1'b0;
        end else if (load) begin
            data_q <= data_in;
            valid_q <= 1'b1;
        end else if (hold) begin
            data_q <= data_q;
            valid_q <= valid_q;
        end
    end
endmodule

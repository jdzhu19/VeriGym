// SPDX-License-Identifier: Apache-2.0
module accumulator_core (
    input  logic       clk,
    input  logic       clear,
    input  logic       step,
    input  logic [7:0] delta,
    output logic [7:0] total
);
    always_ff @(posedge clk) begin
        if (clear) begin
            total <= 8'h00;
        end else if (step) begin
            total <= total + delta;
        end
    end
endmodule

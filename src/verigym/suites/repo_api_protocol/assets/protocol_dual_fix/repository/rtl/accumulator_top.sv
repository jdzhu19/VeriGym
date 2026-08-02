// SPDX-License-Identifier: Apache-2.0
module accumulator_top (
    input  logic       clk,
    input  logic       reset_n,
    input  logic       enable,
    input  logic [7:0] increment,
    output logic [7:0] total
);
    accumulator_core u_core (
        .clk(clk),
        .clear(reset_n),
        .step(enable),
        .delta(increment),
        .total(total)
    );
endmodule

// SPDX-License-Identifier: Apache-2.0
module rr_arbiter (
    input  logic       clk,
    input  logic       rst,
    input  logic [1:0] request,
    output logic [1:0] grant
);
    logic last_grant;

    always_comb begin
        grant = 2'b00;
        case (request)
            2'b01: grant = 2'b01;
            2'b10: grant = 2'b10;
            2'b11: grant = last_grant ? 2'b01 : 2'b10;
            default: grant = 2'b00;
        endcase
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            last_grant <= 1'b0;
        end else if (grant[0]) begin
            last_grant <= 1'b0;
        end else if (grant[1]) begin
            last_grant <= 1'b1;
        end
    end
endmodule

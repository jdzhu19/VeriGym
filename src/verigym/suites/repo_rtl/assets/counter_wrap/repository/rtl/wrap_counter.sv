// SPDX-License-Identifier: Apache-2.0
module wrap_counter (
    input  logic       clk,
    input  logic       rst,
    input  logic       enable,
    output logic [3:0] count
);
    always_ff @(posedge clk) begin
        if (rst) begin
            count <= 4'h0;
        end else if (enable) begin
            if (count == 4'hf) begin
                count <= 4'hf;
            end else begin
                count <= count + 4'h1;
            end
        end
    end
endmodule

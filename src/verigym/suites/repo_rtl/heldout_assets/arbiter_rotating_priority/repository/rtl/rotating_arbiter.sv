module rotating_arbiter (
    input  logic       clk,
    input  logic       rst_n,
    input  logic [2:0] request,
    output logic [2:0] grant
);
    logic [1:0] first_client;

    always_comb begin
        grant = 3'b000;
        case (first_client)
            2'd0: begin
                if (request[0]) grant = 3'b001;
                else if (request[1]) grant = 3'b010;
                else if (request[2]) grant = 3'b100;
            end
            2'd1: begin
                if (request[1]) grant = 3'b010;
                else if (request[2]) grant = 3'b100;
                else if (request[0]) grant = 3'b001;
            end
            default: begin
                if (request[2]) grant = 3'b100;
                else if (request[0]) grant = 3'b001;
                else if (request[1]) grant = 3'b010;
            end
        endcase
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            first_client <= 2'd0;
        end else if (grant[0]) begin
            first_client <= 2'd0;
        end else if (grant[1]) begin
            first_client <= 2'd1;
        end else if (grant[2]) begin
            first_client <= 2'd2;
        end
    end
endmodule

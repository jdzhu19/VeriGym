module request_filter (
    input  logic       enable,
    input  logic [1:0] request,
    output logic [1:0] filtered_request
);
    assign filtered_request = enable ? request : 2'b00;
endmodule

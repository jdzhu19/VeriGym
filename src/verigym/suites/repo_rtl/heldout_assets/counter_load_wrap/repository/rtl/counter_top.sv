module counter_top (
    input  logic       clk,
    input  logic       rst,
    input  logic       load,
    input  logic       enable,
    input  logic [3:0] load_value,
    output logic [3:0] count
);
    loadable_counter u_counter (
        .clk(clk),
        .rst(rst),
        .load(load),
        .enable(enable),
        .load_value(load_value),
        .count(count)
    );
endmodule

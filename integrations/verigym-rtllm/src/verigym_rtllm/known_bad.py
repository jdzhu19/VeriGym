"""Small, independently authored negative controls for RTLLM qualification."""

from __future__ import annotations

from verigym.plugin_api import ConfigurationError

_COUNTER_BAD = {
    "counter_12": (
        "module counter_12(input rst_n, clk, valid_count, output [3:0] out); "
        "assign out = 4'b0; endmodule\n"
    ),
    "up_down_counter": (
        "module up_down_counter(input clk, reset, up_down, output [15:0] count); "
        "assign count = 16'b0; endmodule\n"
    ),
}

_BAD: dict[str, dict[str, str]] = {
    "radix2_div": {
        "stuck-zero": """
module radix2_div(input clk, rst, input [7:0] dividend, divisor, input sign, opn_valid,
                  output res_valid, input res_ready, output [15:0] result);
  assign res_valid = 1'b0; assign result = 16'b0;
endmodule
""",
        "reset-error": """
module radix2_div(input clk, rst, input [7:0] dividend, divisor, input sign, opn_valid,
                  output reg res_valid, input res_ready, output [15:0] result);
  assign result = {dividend % divisor, dividend / divisor};
  initial res_valid = 1'b1;
  always @(posedge clk) if (opn_valid) res_valid <= 1'b1;
endmodule
""",
        "protocol-latency-error": """
module radix2_div(input clk, rst, input [7:0] dividend, divisor, input sign, opn_valid,
                  output res_valid, input res_ready, output [15:0] result);
  assign res_valid = opn_valid;
  assign result = {dividend % divisor, dividend / divisor};
endmodule
""",
        "functional-error": """
module radix2_div(input clk, rst, input [7:0] dividend, divisor, input sign, opn_valid,
                  output reg res_valid, input res_ready, output [15:0] result);
  reg [7:0] q, r; reg [3:0] count;
  assign result = {q, r};
  always @(posedge clk) begin
    if (rst) begin res_valid <= 0; count <= 0; q <= 0; r <= 0; end
    else if (opn_valid && !res_valid) begin q <= dividend % divisor; r <= dividend / divisor;
      count <= 1; end
    else if (count != 0 && count < 8) count <= count + 1;
    else if (count == 8) begin res_valid <= 1; count <= 0; end
    else if (res_valid && res_ready) res_valid <= 0;
  end
endmodule
""",
    },
    "multi_pipe_8bit": {
        "stuck-zero": """
module multi_pipe_8bit #(parameter size=8)(input clk, rst_n, input [size-1:0] mul_a, mul_b,
  input mul_en_in, output mul_en_out, output [size*2-1:0] mul_out);
  assign mul_en_out = 0; assign mul_out = 0;
endmodule
""",
        "reset-error": """
module multi_pipe_8bit #(parameter size=8)(input clk, rst_n, input [size-1:0] mul_a, mul_b,
  input mul_en_in, output reg mul_en_out, output reg [size*2-1:0] mul_out);
  always @(posedge clk) begin mul_en_out <= mul_en_in; mul_out <= mul_a * mul_b; end
endmodule
""",
        "protocol-latency-error": """
module multi_pipe_8bit #(parameter size=8)(input clk, rst_n, input [size-1:0] mul_a, mul_b,
  input mul_en_in, output reg mul_en_out, output reg [size*2-1:0] mul_out);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) begin mul_en_out <= 0; mul_out <= 0; end
    else begin mul_en_out <= mul_en_in; mul_out <= mul_en_in ? mul_a * mul_b : 0; end
endmodule
""",
        "functional-error": """
module multi_pipe_8bit #(parameter size=8)(input clk, rst_n, input [size-1:0] mul_a, mul_b,
  input mul_en_in, output reg mul_en_out, output reg [size*2-1:0] mul_out);
  reg [2:0] valid; reg [15:0] p0, p1, p2;
  always @(posedge clk or negedge rst_n)
    if (!rst_n) begin valid<=0; p0<=0; p1<=0; p2<=0; mul_en_out<=0; mul_out<=0; end
    else begin valid<={valid[1:0],mul_en_in}; p0<=mul_a+mul_b; p1<=p0; p2<=p1;
      mul_en_out<=valid[2]; mul_out<=valid[2]?p2:0; end
endmodule
""",
    },
    "LIFObuffer": {
        "stuck-zero": """
module LIFObuffer(input [3:0] dataIn, input RW, EN, Rst, Clk,
  output EMPTY, FULL, output [3:0] dataOut);
  assign EMPTY=1; assign FULL=0; assign dataOut=0;
endmodule
""",
        "reset-error": """
module LIFObuffer(input [3:0] dataIn, input RW, EN, Rst, Clk,
  output reg EMPTY=0, FULL=0, output reg [3:0] dataOut=0);
  always @(posedge Clk) if (EN && !RW) dataOut <= dataIn;
endmodule
""",
        "protocol-latency-error": """
module LIFObuffer(input [3:0] dataIn, input RW, EN, Rst, Clk,
  output reg EMPTY, FULL, output reg [3:0] dataOut);
  reg [3:0] last;
  always @(posedge Clk) if (Rst) begin EMPTY<=1; FULL<=0; last<=0; dataOut<=0; end
    else if (EN && !RW) begin last<=dataIn; dataOut<=dataIn; EMPTY<=0; end
    else if (EN && RW) begin dataOut<=last; EMPTY<=1; end
endmodule
""",
        "functional-error": """
module LIFObuffer(input [3:0] dataIn, input RW, EN, Rst, Clk,
  output reg EMPTY, FULL, output reg [3:0] dataOut);
  reg [3:0] mem[0:3]; reg [2:0] count; integer i;
  always @(posedge Clk) if (EN) begin
    if (Rst) begin count=0; EMPTY=1; FULL=0; dataOut=0;
      for(i=0;i<4;i=i+1) mem[i]=0; end
    else if (!RW && !FULL) begin mem[count]=dataIn; count=count+1; EMPTY=0; FULL=(count==4); end
    else if (RW && !EMPTY) begin dataOut=mem[0]; count=count-1; EMPTY=(count==0); FULL=0; end
  end
endmodule
""",
    },
    "asyn_fifo": {
        "stuck-zero": """
module asyn_fifo #(parameter WIDTH=8, DEPTH=16)(input wclk,rclk,wrstn,rrstn,winc,rinc,
  input [WIDTH-1:0] wdata, output wfull,rempty,output [WIDTH-1:0] rdata);
  assign wfull=0; assign rempty=1; assign rdata=0;
endmodule
""",
        "reset-error": """
module asyn_fifo #(parameter WIDTH=8, DEPTH=16)(input wclk,rclk,wrstn,rrstn,winc,rinc,
  input [WIDTH-1:0] wdata, output wfull,rempty,output reg [WIDTH-1:0] rdata=0);
  assign wfull=0; assign rempty=0; always @(posedge rclk) rdata<=wdata;
endmodule
""",
        "protocol-latency-error": """
module asyn_fifo #(parameter WIDTH=8, DEPTH=16)(input wclk,rclk,wrstn,rrstn,winc,rinc,
  input [WIDTH-1:0] wdata, output wfull,rempty,output [WIDTH-1:0] rdata);
  assign wfull=0; assign rempty=!winc; assign rdata=wdata;
endmodule
""",
        "functional-error": """
module asyn_fifo #(parameter WIDTH=8, DEPTH=16)(input wclk,rclk,wrstn,rrstn,winc,rinc,
  input [WIDTH-1:0] wdata, output wfull,rempty,output reg [WIDTH-1:0] rdata);
  reg [WIDTH-1:0] last; reg occupied;
  assign wfull=occupied; assign rempty=!occupied;
  always @(posedge wclk or negedge wrstn) if(!wrstn) occupied<=0;
    else if(winc&&!occupied) begin last<=wdata; occupied<=1; end
  always @(posedge rclk or negedge rrstn) if(!rrstn) rdata<=0;
    else if(rinc&&occupied) begin rdata<=last; occupied<=0; end
endmodule
""",
    },
}


def known_bad_source(name: str, category: str) -> str:
    if name in _COUNTER_BAD and category == "stuck-zero":
        return _COUNTER_BAD[name]
    try:
        return _BAD[name][category].lstrip()
    except KeyError as exc:
        raise ConfigurationError(
            f"RTLLM known-bad case is not declared: {name}/{category}"
        ) from exc


__all__ = ["known_bad_source"]

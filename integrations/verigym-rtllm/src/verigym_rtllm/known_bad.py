"""Small, independently authored negative controls for RTLLM qualification."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

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
                  output reg res_valid, input res_ready, output [15:0] result);
  reg [1:0] wait_count;
  assign result = 16'b0;
  always @(posedge clk) begin
    if (rst) begin res_valid<=0;wait_count<=0; end
    else if(opn_valid && !res_valid) wait_count<=1;
    else if(wait_count==1) begin wait_count<=0;res_valid<=1; end
    else if(res_valid && res_ready) res_valid<=0;
  end
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
                  output reg res_valid, input res_ready, output [15:0] result);
  assign result = {dividend % divisor, dividend / divisor};
  always @(posedge clk) begin
    if(rst) res_valid<=0;
    else if(opn_valid) res_valid<=1;
    else if(res_valid && res_ready) res_valid<=0;
  end
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
  input mul_en_in, output reg mul_en_out, output [size*2-1:0] mul_out);
  reg [2:0] valid;
  assign mul_out = 0;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin valid<=0;mul_en_out<=0; end
    else begin valid<={valid[1:0],mul_en_in};mul_en_out<=valid[2]; end
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
    "adder_pipe_64bit": {
        "stuck-zero": """
module adder_pipe_64bit #(parameter DATA_WIDTH=64, STG_WIDTH=16)(input clk,rst_n,i_en,
  input [DATA_WIDTH-1:0] adda,addb,output [DATA_WIDTH:0] result,output reg o_en);
  reg [3:0] valid;
  assign result=0;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin valid<=0;o_en<=0; end
    else begin valid<={valid[2:0],i_en};o_en<=valid[3]; end
endmodule
""",
        "reset-error": """
module adder_pipe_64bit #(parameter DATA_WIDTH=64, STG_WIDTH=16)(input clk,rst_n,i_en,
  input [DATA_WIDTH-1:0] adda,addb,output reg [DATA_WIDTH:0] result,output reg o_en);
  reg [3:0] valid;
  always @(posedge clk) begin
    valid <= {valid[2:0],i_en}; o_en <= valid[3]; result <= adda+addb;
  end
endmodule
""",
        "protocol-latency-error": """
module adder_pipe_64bit #(parameter DATA_WIDTH=64, STG_WIDTH=16)(input clk,rst_n,i_en,
  input [DATA_WIDTH-1:0] adda,addb,output [DATA_WIDTH:0] result,output o_en);
  assign result=i_en?({1'b0,adda}+{1'b0,addb}):0; assign o_en=i_en;
endmodule
""",
        "functional-error": """
module adder_pipe_64bit #(parameter DATA_WIDTH=64, STG_WIDTH=16)(input clk,rst_n,i_en,
  input [DATA_WIDTH-1:0] adda,addb,output [DATA_WIDTH:0] result,output o_en);
  reg [DATA_WIDTH:0] p0,p1,p2,p3; reg [3:0] valid;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin p0<=0;p1<=0;p2<=0;p3<=0;valid<=0; end
    else begin p0<={1'b0,adda}-{1'b0,addb};p1<=p0;p2<=p1;p3<=p2;
      valid<={valid[2:0],i_en}; end
  assign result=p3; assign o_en=valid[3];
endmodule
""",
    },
    "LFSR": {
        "stuck-zero": """
module LFSR(output [3:0] out,input clk,rst);
  assign out=4'b0000;
endmodule
""",
        "reset-error": """
module LFSR(output reg [3:0] out,input clk,rst);
  wire feedback=~(out[3]^out[2]);
  always @(posedge clk or posedge rst)
    if(rst) out<=4'b1111; else out<={out[2:0],feedback};
endmodule
""",
        "protocol-latency-error": """
module LFSR(output reg [3:0] out,input clk,rst);
  wire feedback=~(out[3]^out[2]);
  reg phase;
  always @(posedge clk or posedge rst)
    if(rst) begin out<=4'b0000;phase<=0; end
    else begin phase<=~phase; if(phase) out<={out[2:0],feedback}; end
endmodule
""",
        "functional-error": """
module LFSR(output reg [3:0] out,input clk,rst);
  wire feedback=~(out[3]^out[1]);
  always @(posedge clk or posedge rst)
    if(rst) out<=4'b0000; else out<={out[2:0],feedback};
endmodule
""",
    },
    "serial2parallel": {
        "stuck-zero": """
module serial2parallel(input clk,rst_n,din_serial,din_valid,
  output [7:0] dout_parallel,output reg dout_valid);
  reg [3:0] count;
  assign dout_parallel=0;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin count<=0;dout_valid<=0; end
    else if(!din_valid) begin count<=0;dout_valid<=0; end
    else if(!dout_valid && count==7) begin count<=0;dout_valid<=1; end
    else if(!dout_valid) count<=count+1;
endmodule
""",
        "reset-error": """
module serial2parallel(input clk,rst_n,din_serial,din_valid,
  output reg [7:0] dout_parallel,output reg dout_valid);
  reg [3:0] count;
  initial begin count=0;dout_valid=0;dout_parallel=0; end
  always @(posedge clk) begin
    if(!din_valid) begin count<=0;dout_valid<=0; end
    else if(!dout_valid && count==7) begin count<=0;dout_valid<=1;dout_parallel<=8'hff; end
    else if(!dout_valid) count<=count+1;
  end
endmodule
""",
        "protocol-latency-error": """
module serial2parallel(input clk,rst_n,din_serial,din_valid,
  output reg [7:0] dout_parallel,output reg dout_valid);
  reg [7:0] shift; reg [2:0] count;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin shift<=0;count<=0;dout_parallel<=0;dout_valid<=0; end
    else if(!din_valid) begin count<=0;dout_valid<=0; end
    else if(!dout_valid) begin shift<={shift[6:0],din_serial};
      if(count==3) begin dout_parallel<={shift[6:0],din_serial};dout_valid<=1;count<=0; end
      else count<=count+1; end
endmodule
""",
        "functional-error": """
module serial2parallel(input clk,rst_n,din_serial,din_valid,
  output reg [7:0] dout_parallel,output reg dout_valid);
  reg [7:0] shift; reg [3:0] count;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin shift<=0;count<=0;dout_parallel<=0;dout_valid<=0; end
    else begin
      if(din_valid) count<=(count==8)?0:count+1; else count<=0;
      if(din_valid && count<=7) shift<={din_serial,shift[7:1]};
      if(count==8) begin dout_parallel<=shift;dout_valid<=1; end else dout_valid<=0;
    end
endmodule
""",
    },
    "sequence_detector": {
        "stuck-zero": """
module sequence_detector(input clk,rst_n,data_in,output sequence_detected);
  assign sequence_detected=1'b0;
endmodule
""",
        "reset-error": """
module sequence_detector(input clk,rst_n,data_in,output sequence_detected);
  reg [3:0] history;
  always @(posedge clk or posedge rst_n)
    if(rst_n) history<=0; else history<={history[2:0],data_in};
  assign sequence_detected=(history==4'b1001);
endmodule
""",
        "protocol-latency-error": """
module sequence_detector(input clk,rst_n,data_in,output reg sequence_detected);
  reg [3:0] history;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin history<=0;sequence_detected<=0; end
    else begin history<={history[2:0],data_in};sequence_detected<=(history==4'b1001); end
endmodule
""",
        "functional-error": """
module sequence_detector(input clk,rst_n,data_in,output sequence_detected);
  reg [3:0] history;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) history<=0; else history<={history[2:0],data_in};
  assign sequence_detected=({history[2:0],data_in}==4'b1011);
endmodule
""",
    },
    "synchronizer": {
        "stuck-zero": """
module synchronizer(input clk_a,clk_b,arstn,brstn,input [3:0] data_in,input data_en,
  output [3:0] dataout);
  assign dataout=0;
endmodule
""",
        "reset-error": """
module synchronizer(input clk_a,clk_b,arstn,brstn,input [3:0] data_in,input data_en,
  output reg [3:0] dataout);
  reg [3:0] data_reg; reg en_one,en_two;
  always @(posedge clk_a or posedge arstn)
    if(arstn) data_reg<=0; else if(data_en) data_reg<=data_in;
  always @(posedge clk_b or posedge brstn)
    if(brstn) begin en_one<=0;en_two<=0;dataout<=0; end
    else begin en_one<=data_en;en_two<=en_one;if(en_two) dataout<=data_reg; end
endmodule
""",
        "protocol-latency-error": """
module synchronizer(input clk_a,clk_b,arstn,brstn,input [3:0] data_in,input data_en,
  output reg [3:0] dataout);
  reg [3:0] data_reg; reg [7:0] enable_pipe;
  always @(posedge clk_a or negedge arstn)
    if(!arstn) data_reg<=0; else data_reg<=data_in;
  always @(posedge clk_b or negedge brstn)
    if(!brstn) begin enable_pipe<=0;dataout<=0; end
    else begin enable_pipe<={enable_pipe[6:0],data_en};
      if(enable_pipe[7]) dataout<=data_reg; end
endmodule
""",
        "functional-error": """
module synchronizer(input clk_a,clk_b,arstn,brstn,input [3:0] data_in,input data_en,
  output reg [3:0] dataout);
  reg [3:0] data_reg; reg en_one,en_two;
  always @(posedge clk_a or negedge arstn)
    if(!arstn) data_reg<=0; else data_reg<=data_in;
  always @(posedge clk_b or negedge brstn)
    if(!brstn) begin en_one<=0;en_two<=0;dataout<=0; end
    else begin en_one<=data_en;en_two<=en_one;if(en_two) dataout<=~data_reg; end
endmodule
""",
    },
    "RAM": {
        "stuck-zero": """
module RAM(input clk,rst_n,write_en,input [7:0] write_addr,input [5:0] write_data,
  input read_en,input [7:0] read_addr,output [5:0] read_data);
  assign read_data=0;
endmodule
""",
        "reset-error": """
module RAM(input clk,rst_n,write_en,input [7:0] write_addr,input [5:0] write_data,
  input read_en,input [7:0] read_addr,output reg [5:0] read_data);
  reg [5:0] mem[0:7]; integer i;
  always @(posedge clk or posedge rst_n)
    if(rst_n) begin read_data<=0;for(i=0;i<8;i=i+1) mem[i]<=0; end
    else begin if(write_en) mem[write_addr]<=write_data;
      read_data<=read_en?mem[read_addr]:0; end
endmodule
""",
        "protocol-latency-error": """
module RAM(input clk,rst_n,write_en,input [7:0] write_addr,input [5:0] write_data,
  input read_en,input [7:0] read_addr,output reg [5:0] read_data);
  reg [5:0] mem[0:7]; reg pending; reg [7:0] delayed_addr; integer i;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin read_data<=0;pending<=0;delayed_addr<=0;
      for(i=0;i<8;i=i+1) mem[i]<=0; end
    else begin if(write_en) mem[write_addr]<=write_data;
      if(pending) read_data<=mem[delayed_addr]; else read_data<=0;
      pending<=read_en;delayed_addr<=read_addr; end
endmodule
""",
        "functional-error": """
module RAM(input clk,rst_n,write_en,input [7:0] write_addr,input [5:0] write_data,
  input read_en,input [7:0] read_addr,output reg [5:0] read_data);
  reg [5:0] mem[0:7]; integer i;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin read_data<=0;for(i=0;i<8;i=i+1) mem[i]<=0; end
    else begin if(write_en) mem[write_addr]<=write_data+1'b1;
      read_data<=read_en?mem[read_addr]:0; end
endmodule
""",
    },
}

# These controls deliberately stay small and independent of the upstream implementation.  The
# reset-error category is an initial/reset-boundary error for combinational tasks.  The protocol
# category is a clock-driven free-running response for sequential tasks and an input-wiring error
# for combinational tasks.  Each is compile-shaped but observably wrong under both public and
# hidden qualification.
_GENERATED_CONTROL_SHAPES: dict[str, tuple[tuple[str, ...], str | None, str | None]] = {
    "counter_12": (("out",), "clk", "valid_count"),
    "up_down_counter": (("count",), "clk", "up_down"),
    "accu": (("valid_out", "data_out"), "clk", "data_in"),
    "adder_16bit": (("y", "Co"), None, "a"),
    "adder_32bit": (("S", "C32"), None, "A"),
    "adder_8bit": (("sum", "cout"), None, "a"),
    "adder_bcd": (("Sum", "Cout"), None, "A"),
    "comparator_3bit": (("A_greater", "A_equal", "A_less"), None, "A"),
    "comparator_4bit": (("A_greater", "A_equal", "A_less"), None, "A"),
    "div_16bit": (("result", "odd"), None, "A"),
    "multi_16bit": (("yout", "done"), "clk", "ain"),
    "multi_8bit": (("product",), None, "A"),
    "multi_booth_8bit": (("p", "rdy"), "clk", "a"),
    "multi_pipe_4bit": (("mul_out",), "clk", "mul_a"),
    "fixed_point_adder": (("c",), None, "a"),
    "fixed_point_substractor": (("c",), None, "a"),
    "float_multi": (("z",), "clk", "a"),
    "sub_64bit": (("result", "overflow"), None, "A"),
    "JC_counter": (("Q",), "clk", "rst_n"),
    "ring_counter": (("out",), "clk", "reset"),
    "fsm": (("MATCH",), "CLK", "IN"),
    "barrel_shifter": (("out",), None, "in"),
    "right_shifter": (("q",), "clk", "d"),
    "freq_div": (("CLK_50", "CLK_10", "CLK_1"), "CLK_in", "RST"),
    "freq_divbyeven": (("clk_div",), "clk", "rst_n"),
    "freq_divbyfrac": (("clk_div",), "clk", "rst_n"),
    "freq_divbyodd": (("clk_div",), "clk", "rst_n"),
    "calendar": (("Hours", "Mins", "Secs"), "CLK", "RST"),
    "edge_detect": (("rise", "down"), "clk", "a"),
    "parallel2serial": (("valid_out", "dout"), "clk", "d"),
    "pulse_detect": (("data_out",), "clk", "data_in"),
    "traffic_light": (("clock", "red", "yellow", "green"), "clk", "pass_request"),
    "width_8to16": (("valid_out", "data_out"), "clk", "data_in"),
    "ROM": (("dout",), None, "addr"),
    "alu": (("r", "zero", "carry", "negative", "overflow", "flag"), None, "a"),
    "clkgenerator": (("clk",), None, None),
    "instr_reg": (("ins", "ad1", "ad2"), "clk", "data"),
    "pe": (("c",), "clk", "a"),
    "signal_generator": (("wave",), "clk", "rst_n"),
    "square_wave": (("wave_out",), "clk", "freq"),
    # The following tasks have hand-written historical controls in ``_BAD``.  Their interface
    # shapes are also frozen here so feedback-v2 can build additional independent controls from
    # the public scaffold without reading the upstream reference implementation.
    "radix2_div": (("res_valid", "result"), "clk", "dividend"),
    "multi_pipe_8bit": (("mul_en_out", "mul_out"), "clk", "mul_a"),
    "LIFObuffer": (("EMPTY", "FULL", "dataOut"), "Clk", "dataIn"),
    "asyn_fifo": (("wfull", "rempty", "rdata"), "wclk", "wdata"),
    "adder_pipe_64bit": (("result", "o_en"), "clk", "adda"),
    "LFSR": (("out",), "clk", "rst"),
    "serial2parallel": (("dout_parallel", "dout_valid"), "clk", "din_serial"),
    "sequence_detector": (("sequence_detected",), "clk", "data_in"),
    "synchronizer": (("dataout",), "clk_b", "data_in"),
    "RAM": (("read_data",), "clk", "write_data"),
}


def _control_scaffold(name: str) -> str:
    assets = Path(__file__).parent / "assets"
    if name == "counter_12":
        path = assets / "workspace" / "rtl" / "counter_12.v"
    elif name == "up_down_counter":
        path = assets / "workspace_up_down" / "rtl" / "up_down_counter.v"
    else:
        path = assets / "workspace_l2_full" / "rtl" / f"{name}.v"
    source = path.read_text(encoding="utf-8")
    match = re.fullmatch(r"(?s)(.*?\);\s*).*?endmodule\s*", source)
    if match is None:
        raise ConfigurationError(f"RTLLM control scaffold is malformed: {name}")
    return match.group(1).replace("output reg", "output wire")


def _generated_control_source(name: str, category: str) -> str:
    outputs, clock, probe = _GENERATED_CONTROL_SHAPES[name]
    header = _control_scaffold(name)
    if category == "stuck-zero" and name == "multi_booth_8bit":
        body = [
            "    reg [2:0] control_count;",
            "    initial control_count = 0;",
            "    always @(posedge clk) begin",
            "        if (reset) control_count <= 0;",
            "        else if (control_count < 3) control_count <= control_count + 1'b1;",
            "    end",
            "    assign p = '0;",
            "    assign rdy = control_count == 2;",
        ]
    elif category == "stuck-zero" and name == "parallel2serial":
        body = [
            "    reg [2:0] control_phase;",
            "    always @(posedge clk or negedge rst_n)",
            "        if (!rst_n) control_phase <= 0;",
            "        else if (control_phase == 4) control_phase <= 0;",
            "        else control_phase <= control_phase + 1'b1;",
            "    assign valid_out = control_phase == 0;",
            "    assign dout = 1'b0;",
        ]
    elif category == "stuck-zero":
        body = [f"    assign {output} = '0;" for output in outputs]
    elif category == "reset-error" and name.startswith("comparator_"):
        body = [
            "    assign A_greater = 1'b0;",
            "    assign A_equal = 1'b0;",
            "    assign A_less = 1'b1;",
        ]
    elif category == "reset-error":
        body = [f"    assign {output} = '1;" for output in outputs]
    elif category == "protocol-latency-error" and name == "square_wave":
        body = [
            "    reg [4:0] control_state;",
            "    initial control_state = 0;",
            "    always @(posedge clk) begin",
            "        if (control_state == 15) control_state <= 0;",
            "        else control_state <= control_state + 1'b1;",
            "    end",
            "    assign wave_out = control_state < 12;",
        ]
    elif category == "protocol-latency-error" and clock is not None:
        body = [
            "    reg [63:0] control_state;",
            "    initial control_state = 64'h0123456789abcdef;",
            f"    always @(posedge {clock}) control_state <= control_state + 64'd1;",
            *[f"    assign {output} = control_state;" for output in outputs],
        ]
    elif category == "protocol-latency-error" and probe is not None:
        if name in {"fixed_point_adder", "fixed_point_substractor"}:
            body = [f"    assign {outputs[0]} = 32'h12345678;"]
        else:
            body = [
                f"    wire control_probe = ^{probe};",
                *[f"    assign {output} = {{64{{control_probe}}}};" for output in outputs],
            ]
    elif category == "protocol-latency-error":
        body = [
            "    reg control_clock;",
            "    initial begin control_clock = 1'b0; forever begin",
            "        #1 control_clock = ~control_clock; #2 control_clock = ~control_clock;",
            "    end end",
            *[f"    assign {output} = control_clock;" for output in outputs],
        ]
    elif category == "functional-error":
        if name == "multi_booth_8bit":
            body = [
                "    reg [2:0] control_count;",
                "    initial control_count = 0;",
                "    always @(posedge clk) begin",
                "        if (reset) control_count <= 0;",
                "        else if (control_count < 3) control_count <= control_count + 1'b1;",
                "    end",
                "    assign p = 16'h5555;",
                "    assign rdy = control_count == 2;",
            ]
        elif name == "parallel2serial":
            body = [
                "    reg [2:0] control_phase;",
                "    always @(posedge clk or negedge rst_n)",
                "        if (!rst_n) control_phase <= 0;",
                "        else if (control_phase == 4) control_phase <= 0;",
                "        else control_phase <= control_phase + 1'b1;",
                "    assign valid_out = control_phase == 0;",
                "    assign dout = ~d[control_phase[1:0]];",
            ]
        else:
            body = [
                f"    assign {output} = 64'h{('55' if index % 2 == 0 else 'aa') * 8};"
                for index, output in enumerate(outputs)
            ]
    else:
        raise ConfigurationError(f"RTLLM known-bad category is unknown: {category}")
    return header + "\n" + "\n".join(body) + "\nendmodule\n"


def task_specific_bad_source(
    name: str,
    *,
    mutation_id: str,
    obligation: str,
    base_control: str,
) -> str:
    """Build an observable task-interface mutant without consulting the golden RTL."""

    try:
        outputs, clock, _ = _GENERATED_CONTROL_SHAPES[name]
    except KeyError as exc:
        raise ConfigurationError(f"RTLLM task-specific control shape is unknown: {name}") from exc
    source = known_bad_source(name, base_control)
    header_end = source.find(");")
    if header_end < 0:
        raise ConfigurationError(f"RTLLM task-specific control source is malformed: {name}")
    header_end += 2
    tag = int.from_bytes(hashlib.sha256(f"{name}/{mutation_id}".encode()).digest()[:8], "big")
    corruption = tag | 1
    corruption_literal = f"64'h{corruption:016x}"

    support = [f"    // Observable {obligation} mutation: {mutation_id}."]
    if name == "square_wave":
        activation = tag & 0xFF
        support.extend(
            (
                "    wire [63:0] verigym_control_value;",
                (
                    "    assign verigym_control_value = "
                    f"(freq == 8'h{activation:02x}) ? {corruption_literal} : 64'd0;"
                ),
            )
        )
    elif clock is None:
        support.extend(
            (
                "    wire [63:0] verigym_control_value;",
                f"    assign verigym_control_value = {corruption_literal};",
            )
        )
    else:
        support.extend(
            (
                "    reg [63:0] verigym_control_value;",
                f"    initial verigym_control_value = {corruption_literal};",
                f"    always @(posedge {clock})",
                "        verigym_control_value <= verigym_control_value + 64'd1;",
            )
        )
    signal = "verigym_control_value"

    status_fragments = ("valid", "en", "done", "rdy", "full", "empty", "flag", "clock")
    target = min(
        outputs,
        key=lambda output: (any(fragment in output.lower() for fragment in status_fragments),),
    )
    body = source[header_end:]
    patterns = (
        rf"(\bassign\s+{re.escape(target)}\s*=\s*)([^;]+)(;)",
        rf"(\b{re.escape(target)}\s*<=\s*)([^;]+)(;)",
        rf"(\b{re.escape(target)}\s*=\s*)([^;]+)(;)",
    )
    replacements = 0
    for pattern in patterns:
        matches = list(re.finditer(pattern, body))
        if matches:
            match = matches[-1]
            replacement = f"{match.group(1)}({match.group(2)}) ^ {signal}{match.group(3)}"
            body = body[: match.start()] + replacement + body[match.end() :]
            replacements = 1
            break
    if replacements != 1:
        raise ConfigurationError(
            f"RTLLM task-specific control output is not assignable: {name}/{target}"
        )
    return source[:header_end] + "\n" + "\n".join(support) + "\n" + body


def known_bad_source(name: str, category: str) -> str:
    if name in _COUNTER_BAD and category == "stuck-zero":
        return _COUNTER_BAD[name]
    if name in _GENERATED_CONTROL_SHAPES and name not in _BAD:
        return _generated_control_source(name, category)
    if name in _COUNTER_BAD:
        return _generated_control_source(name, category)
    try:
        return _BAD[name][category].lstrip()
    except KeyError as exc:
        raise ConfigurationError(
            f"RTLLM known-bad case is not declared: {name}/{category}"
        ) from exc


__all__ = ["known_bad_source", "task_specific_bad_source"]

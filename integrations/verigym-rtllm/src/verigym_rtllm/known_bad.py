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
    "adder_pipe_64bit": {
        "stuck-zero": """
module adder_pipe_64bit #(parameter DATA_WIDTH=64, STG_WIDTH=16)(input clk,rst_n,i_en,
  input [DATA_WIDTH-1:0] adda,addb,output [DATA_WIDTH:0] result,output o_en);
  assign result=0; assign o_en=0;
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
  output [7:0] dout_parallel,output dout_valid);
  assign dout_parallel=0; assign dout_valid=0;
endmodule
""",
        "reset-error": """
module serial2parallel(input clk,rst_n,din_serial,din_valid,
  output reg [7:0] dout_parallel,output reg dout_valid);
  reg [7:0] shift; reg [3:0] count;
  always @(posedge clk or posedge rst_n)
    if(rst_n) begin shift<=0;count<=0;dout_parallel<=0;dout_valid<=0; end
    else if(din_valid) begin shift<={shift[6:0],din_serial};count<=count+1;
      dout_valid<=0; end
endmodule
""",
        "protocol-latency-error": """
module serial2parallel(input clk,rst_n,din_serial,din_valid,
  output reg [7:0] dout_parallel,output reg dout_valid);
  reg [7:0] shift; reg [2:0] count;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin shift<=0;count<=0;dout_parallel<=0;dout_valid<=0; end
    else begin dout_valid<=0; if(din_valid) begin shift<={shift[6:0],din_serial};
      if(count==7) begin dout_parallel<={shift[6:0],din_serial};dout_valid<=1;count<=0; end
      else count<=count+1; end end
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

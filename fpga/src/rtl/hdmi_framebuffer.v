`timescale 1ns/1ps
// 720p60 timing; two RGB332 640x360 frames, each in a 256 KiB bank.
module hdmi_framebuffer(
 input wire pixel_clk, input wire resetn,
 input wire [1:0] control,
 output wire [1:0] status,
 output reg [18:0] mem_addr=0,
 input wire [31:0] mem_data,
 output reg [23:0] rgb,
 output reg de, output reg hsync, output reg vsync
);
 reg [10:0] x=0; reg [9:0] y=0;
 (* ASYNC_REG="TRUE" *) reg [1:0] control_meta=0, control_sync=0;
 reg [1:0] active=0;
 reg [1:0] lane=0;
 reg [1:0] lane2=0;
 reg [15:0] row_offset=0;
 reg de2=0, hs2=0, vs2=0;
 reg de_delay=0, hs_delay=0, vs_delay=0;
 wire visible=(x<1280 && y<720);
 wire [15:0] word_offset=row_offset+(x>>3);
 assign status=active;
 wire [7:0] pixel=mem_data>>(lane2*8);
 wire [7:0] red={pixel[7:5],pixel[7:5],pixel[7:6]};
 wire [7:0] green={pixel[4:2],pixel[4:2],pixel[4:3]};
 wire [7:0] blue={pixel[1:0],pixel[1:0],pixel[1:0],pixel[1:0]};
 always @(posedge pixel_clk) begin
  control_meta<=control; control_sync<=control_meta;
  if(!resetn) begin
   x<=0; y<=0; active<=0; lane<=0; lane2<=0; row_offset<=0; mem_addr<=0;
   de2<=0; hs2<=0; vs2<=0;
   de_delay<=0; hs_delay<=0; vs_delay<=0;
   rgb<=0; de<=0; hsync<=0; vsync<=0;
  end else begin
   if(x==1649) begin
    x<=0;
    if(y==749) begin y<=0; row_offset<=0; active<=control_sync; end
    else begin y<=y+1'b1; if(y[0]) row_offset<=row_offset+160; end
   end else x<=x+1'b1;
   lane<=x[2:1];
   lane2<=lane;
   // AXI BRAM Controller configures the native B port with BYTE addresses.
   mem_addr<={active[0],word_offset,2'b00};
   de_delay<=visible;
   hs_delay<=(x>=1390 && x<1430);
   vs_delay<=(y>=725 && y<730);
   de2<=de_delay; hs2<=hs_delay; vs2<=vs_delay;
   de<=de2; hsync<=hs2; vsync<=vs2;
   // Digilent rgb2dvi expects R,B,G (not R,G,B).
   rgb<=active[1] ? {red,blue,green} : 24'b0;
  end
 end
endmodule

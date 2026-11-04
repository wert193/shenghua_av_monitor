`timescale 1ns/1ps
module tb_hdmi_framebuffer;
 reg clk=0; always #5 clk=~clk;
 reg resetn=0; reg [1:0] control=0;
 wire [1:0] status; wire [18:0] addr;
 reg [31:0] data=0;
 wire [23:0] rgb; wire de,hs,vs;
 hdmi_framebuffer dut(clk,resetn,control,status,addr,data,rgb,de,hs,vs);
 always @(posedge clk) data<=32'he01c03ff;
 integer count_de=0,count_hs=0,count_vs=0,i;
 initial begin
  repeat(4) @(negedge clk);
  resetn=1; control=2;
  repeat(1650*750+5) @(negedge clk);
  if(status!==2) $fatal(1,"Frame bank did not latch");
  for(i=0;i<1650*750;i=i+1) begin
   @(negedge clk);
   if(de) count_de=count_de+1;
   if(hs) count_hs=count_hs+1;
   if(vs) count_vs=count_vs+1;
   if(de && rgb!==24'hffffff && rgb!==24'h00ff00 && rgb!==24'h0000ff && rgb!==24'hff0000)
    $fatal(1,"Unexpected RGB byte lane or channel order");
  end
  if(count_de!=1280*720 || count_hs!=40*750 || count_vs!=5*1650)
   $fatal(1,"Timing counts incorrect %d %d %d",count_de,count_hs,count_vs);
  control=3;
  repeat(100) @(negedge clk);
  if(status!==2) $fatal(1,"Bank changed during active frame");
  repeat(1650*750) @(negedge clk);
  if(status!==3 || addr[18]!==1 || addr[1:0]!==0) $fatal(1,"Bank switch failed");
  $display("PASS: 720p timing, RGB332 expansion and frame-boundary bank switching");
  $finish;
 end
endmodule

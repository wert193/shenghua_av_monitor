`timescale 1ns/1ps
module tb_video_smooth;
 reg clk=0;always #5 clk=~clk;
 reg resetn=0;reg [31:0] config_word=0;
 reg [31:0] s_data=0;reg s_last=0,s_valid=0,m_ready=0;
 wire s_ready,m_valid,m_last;wire [31:0] m_data;
 wire [31:0] ai_data;wire [3:0] ai_keep,m_keep;wire ai_last,ai_valid,ao_ready;
 reg [31:0] source[0:254];reg [31:0] expected[0:194];
 integer sent=0,received=0,cycle=0,round=0;
 video_smooth_router dut(.clk(clk),.resetn(resetn),.config_word(config_word),
 .s_data(s_data),.s_keep(4'hf),.s_last(s_last),.s_valid(s_valid),.s_ready(s_ready),
 .m_data(m_data),.m_keep(m_keep),.m_last(m_last),.m_valid(m_valid),.m_ready(m_ready),
 .ai_data(ai_data),.ai_keep(ai_keep),.ai_last(ai_last),.ai_valid(ai_valid),.ai_ready(1'b1),
 .ao_data(32'h12345678),.ao_keep(4'hf),.ao_last(1'b1),.ao_valid(1'b1),.ao_ready(ao_ready));
 always @(posedge clk) if(resetn && config_word[31]) begin
   if(s_valid && s_ready)sent=sent+1;
   if(m_valid && m_ready)begin
     if(received>=195 || m_data!==expected[received] || m_keep!==4'hf || m_last!==(received==194))
       $fatal(1,"Mismatch round %d pixel %d: got %h expected %h last %b",round,received,m_data,expected[received],m_last);
     received=received+1;
   end
 end
 initial begin
   $readmemh("video_input.hex",source);$readmemh("video_expected.hex",expected);
   repeat(4)@(negedge clk);resetn=1;
   for(round=0;round<3;round=round+1)begin
     config_word=0;m_ready=1;s_valid=1;s_data=32'h87654321;s_last=1;
     #1;if(m_data!==32'h12345678 || ai_data!==32'h87654321 || !ai_valid || !ao_ready)$fatal(1,"Audio routing failed");
     repeat(3)@(negedge clk);
     config_word=32'h8000000d;sent=0;received=0;cycle=0;s_valid=0;
     while(received<195 && cycle<10000)begin
       @(negedge clk);cycle=cycle+1;
       // Hold valid data until accepted; generate source and sink stalls.
       s_valid=(sent<255) && (cycle%7!=0);
       s_data=sent<255 ? source[sent] : 0;s_last=(sent==254);
       m_ready=(cycle%5!=0 && cycle%5!=1);
     end
     if(received!=195 || sent!=255)$fatal(1,"Timeout");
     @(negedge clk);s_valid=0;config_word=0;
   end
   $display("PASS: RGB smoothing, border pixels, backpressure, TLAST, repeat frames, audio routing");$finish;
 end
 initial begin #2000000;$fatal(1,"Simulation timeout");end
endmodule

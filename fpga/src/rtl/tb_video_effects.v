`timescale 1ns/1ps
module tb_video_effects;
 reg clk=0;always #5 clk=~clk;
 reg resetn=0;reg [31:0] config_word=0;
 reg [31:0] s_data=0;reg s_last=0,s_valid=0,m_ready=0;
 wire s_ready,m_valid,m_last;wire [31:0] m_data;
 wire [31:0] ai_data;wire [3:0] ai_keep,m_keep;wire ai_last,ai_valid,ao_ready;
 reg [31:0] vectors[0:699999];
 integer sent=0,received=0,cycle=0,round=0,pos=1,src=0,exp=0,n=0,count=0,w=0,mode=0,issued=-1;
 video_smooth_router dut(.clk(clk),.resetn(resetn),.config_word(config_word),
 .s_data(s_data),.s_keep(4'hf),.s_last(s_last),.s_valid(s_valid),.s_ready(s_ready),
 .m_data(m_data),.m_keep(m_keep),.m_last(m_last),.m_valid(m_valid),.m_ready(m_ready),
 .ai_data(ai_data),.ai_keep(ai_keep),.ai_last(ai_last),.ai_valid(ai_valid),.ai_ready(1'b1),
 .ao_data(32'h12345678),.ao_keep(4'hf),.ao_last(1'b1),.ao_valid(1'b1),.ao_ready(ao_ready));
 always @(posedge clk) if(resetn && config_word[31]) begin
   if(s_valid && s_ready)sent=sent+1;
   if(m_valid && m_ready)begin
     if(received>=count || m_data!==vectors[exp+received] || m_keep!==4'hf || m_last!==(received==count-1))
       $fatal(1,"Mismatch case %d mode %d pixel %d got %h expected %h",round,mode,received,m_data,vectors[exp+received]);
     received=received+1;
   end
 end
 initial begin
   $readmemh("vectors.hex",vectors);
   repeat(4)@(negedge clk);resetn=1;
   for(round=0;round<vectors[0];round=round+1)begin
     if(round%2==0)begin
       config_word=0;m_ready=1;s_valid=1;s_data=32'h87654321;s_last=1;
       #1;if(m_data!==32'h12345678 || ai_data!==32'h87654321 || !ai_valid || !ao_ready)$fatal(1,"Audio route");
       repeat(3)@(negedge clk);
     end
     w=vectors[pos];mode=vectors[pos+1];n=vectors[pos+2];count=vectors[pos+3];src=pos+4;exp=src+n;pos=exp+count;
     config_word=32'h80000000|(mode<<20)|w;sent=0;received=0;cycle=0;s_valid=0;issued=-1;
     while(received<count && cycle<500000)begin
       @(negedge clk);cycle=cycle+1;
       if(!s_valid || issued!=sent)begin
         s_valid=(sent<n)&&(cycle%7!=0);issued=sent;
         s_data=sent<n ? vectors[src+sent] : 0;s_last=(sent==n-1);
       end
       m_ready=(cycle%5!=0 && cycle%5!=1);
     end
     if(received!=count || sent!=n)$fatal(1,"Timeout");
     @(negedge clk);s_valid=0;
     $display("PASS case %d mode %d pixels %d",round,mode,count);
   end
   $display("PASS: all effects, full-size, tiny/1D frames, saturation, borders, backpressure, consecutive frames and audio routing");$finish;
 end
 initial begin #50000000;$fatal(1,"Simulation timeout");end
endmodule

`timescale 1ns/1ps
// Shared DMA: audio FIR or BGR888 smooth/Sobel/sharpen/original video.
// Video input is edge-padded by one pixel on all sides. Output is unpadded.
module video_smooth_router(
 (* X_INTERFACE_PARAMETER="ASSOCIATED_BUSIF S_AXIS:M_AXIS:AUDIO_IN:AUDIO_OUT, ASSOCIATED_RESET resetn" *)
 input wire clk,
 (* X_INTERFACE_PARAMETER="POLARITY ACTIVE_LOW" *) input wire resetn,
 input wire [31:0] config_word,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TDATA" *) input wire [31:0] s_data,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TKEEP" *) input wire [3:0] s_keep,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TLAST" *) input wire s_last,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TVALID" *) input wire s_valid,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 S_AXIS TREADY" *) output wire s_ready,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TDATA" *) output wire [31:0] m_data,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TKEEP" *) output wire [3:0] m_keep,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TLAST" *) output wire m_last,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TVALID" *) output wire m_valid,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 M_AXIS TREADY" *) input wire m_ready,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 AUDIO_IN TDATA" *) output wire [31:0] ai_data,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 AUDIO_IN TKEEP" *) output wire [3:0] ai_keep,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 AUDIO_IN TLAST" *) output wire ai_last,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 AUDIO_IN TVALID" *) output wire ai_valid,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 AUDIO_IN TREADY" *) input wire ai_ready,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 AUDIO_OUT TDATA" *) input wire [31:0] ao_data,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 AUDIO_OUT TKEEP" *) input wire [3:0] ao_keep,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 AUDIO_OUT TLAST" *) input wire ao_last,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 AUDIO_OUT TVALID" *) input wire ao_valid,
 (* X_INTERFACE_INFO="xilinx.com:interface:axis:1.0 AUDIO_OUT TREADY" *) output wire ao_ready
);
 wire video=config_word[31];
 wire [9:0] width=config_word[9:0];
 reg [9:0] x=0;
 reg [9:0] y=0;
 wire [1:0] mode=config_word[21:20];
 // Top byte carries the exact ARM integer luminance for Sobel.
 wire [15:0] gray_sum=16'd29*s_data[7:0]+16'd150*s_data[15:8]+16'd77*s_data[23:16]+16'd128;
 // Separate luminance, window arithmetic and saturation into three stages.
 reg [31:0] current=0;
 reg current_last=0,emit_pixel=0;
 reg [1:0] phase=0,mode_hold=0;
 reg signed [11:0] gx_hold=0,gy_hold=0;
 reg [23:0] original_hold=0;
 reg [29:0] top_hold=0,mid_hold=0,bot_hold=0;
 reg [38:0] sharp_hold=0;
 (* ram_style="distributed" *) reg [31:0] row1[0:511];
 (* ram_style="distributed" *) reg [31:0] row2[0:511];
 wire [31:0] mr=row1[x[8:0]],tr=row2[x[8:0]],br=current;
 reg [31:0] tl=0,tc=0,ml=0,mc=0,bl=0,bc=0;
 wire signed [11:0] gx=$signed({4'b0,tr[31:24]})+($signed({4'b0,mr[31:24]})<<<1)+$signed({4'b0,br[31:24]})
                            -$signed({4'b0,tl[31:24]})-($signed({4'b0,ml[31:24]})<<<1)-$signed({4'b0,bl[31:24]});
 wire signed [11:0] gy=$signed({4'b0,bl[31:24]})+($signed({4'b0,bc[31:24]})<<<1)+$signed({4'b0,br[31:24]})
                            -$signed({4'b0,tl[31:24]})-($signed({4'b0,tc[31:24]})<<<1)-$signed({4'b0,tr[31:24]});
 wire [11:0] abs_x=gx_hold[11] ? -gx_hold : gx_hold;
 wire [11:0] abs_y=gy_hold[11] ? -gy_hold : gy_hold;
 wire [12:0] edge_sum={1'b0,abs_x}+{1'b0,abs_y}+13'd2;
 wire [7:0] edge_pixel=(edge_sum>>2)>255 ? 8'd255 : edge_sum[9:2];
 wire [23:0] filtered;
 genvar c;
 generate for(c=0;c<3;c=c+1) begin: channels
   wire [9:0] top={2'b0,tl[c*8+:8]}+{1'b0,tc[c*8+:8],1'b0}+{2'b0,tr[c*8+:8]};
   wire [9:0] mid={2'b0,ml[c*8+:8]}+{1'b0,mc[c*8+:8],1'b0}+{2'b0,mr[c*8+:8]};
   wire [9:0] bot={2'b0,bl[c*8+:8]}+{1'b0,bc[c*8+:8],1'b0}+{2'b0,br[c*8+:8]};
   wire [11:0] sum={2'b0,top_hold[c*10+:10]}+{1'b0,mid_hold[c*10+:10],1'b0}+{2'b0,bot_hold[c*10+:10]}+12'd8;
   wire signed [12:0] sharp=($signed({5'b0,mc[c*8+:8]})<<<2)+$signed({5'b0,mc[c*8+:8]})
     -$signed({5'b0,tc[c*8+:8]})-$signed({5'b0,bc[c*8+:8]})-$signed({5'b0,ml[c*8+:8]})-$signed({5'b0,mr[c*8+:8]});
   wire signed [12:0] sharp_value=sharp_hold[c*13+:13];
   wire [7:0] sharp_pixel=sharp_value<0 ? 8'd0 : sharp_value>255 ? 8'd255 : sharp_value[7:0];
   always @(posedge clk) if(resetn && video && phase==1) begin
     top_hold[c*10+:10]<=top;mid_hold[c*10+:10]<=mid;bot_hold[c*10+:10]<=bot;
     sharp_hold[c*13+:13]<=sharp;
   end
   assign filtered[c*8+:8]=mode_hold==0 ? sum[11:4] : mode_hold==1 ? edge_pixel : mode_hold==2 ? sharp_pixel : original_hold[c*8+:8];
 end endgenerate
 reg [31:0] result=0;
 reg valid=0,last=0;
 wire accept=video && s_valid && s_ready;
 assign ai_data=s_data;assign ai_keep=s_keep;assign ai_last=s_last;
 assign ai_valid=s_valid && !video;
 assign ao_ready=m_ready && !video;
 assign s_ready=video ? (phase==0 && (!valid || m_ready)) : ai_ready;
 assign m_data=video ? result : ao_data;
 assign m_keep=video ? 4'hf : ao_keep;
 assign m_valid=video ? valid : ao_valid;
 assign m_last=video ? last : ao_last;
 always @(posedge clk) begin
   if(!resetn || !video) begin
     x<=0;y<=0;tl<=0;tc<=0;ml<=0;mc<=0;bl<=0;bc<=0;valid<=0;last<=0;
     phase<=0;emit_pixel<=0;
   end else begin
     if(valid && m_ready) valid<=0;
     if(accept) begin
       current<={gray_sum[15:8],s_data[23:0]};current_last<=s_last;
       mode_hold<=mode;phase<=1;
     end
     if(phase==1) begin
       gx_hold<=gx;gy_hold<=gy;original_hold<=mc[23:0];
       emit_pixel<=(x>=2 && y>=2);phase<=2;
       row1[x[8:0]]<=current;
       row2[x[8:0]]<=mr;
       tl<=tc;tc<=tr;ml<=mc;mc<=mr;bl<=bc;bc<=br;
       if(current_last) begin x<=0;y<=0;tl<=0;tc<=0;ml<=0;mc<=0;bl<=0;bc<=0;end
       else if(x==width+1) begin x<=0;y<=y+1'b1;tl<=0;tc<=0;ml<=0;mc<=0;bl<=0;bc<=0;end
       else x<=x+1'b1;
     end
     if(phase==2) begin
       if(emit_pixel) begin result<={8'b0,filtered};valid<=1;last<=current_last;end
       phase<=0;
     end
   end
 end
endmodule

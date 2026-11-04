set fir_root_dir [file normalize [file join [file dirname [info script]] ..]]
set_param general.maxThreads 4
create_project -force video_effects [file join $fir_root_dir build video_effects] -part xc7z020clg400-1
set_property ip_repo_paths [list [file join $fir_root_dir build fir_accel solution1 impl ip] [file join $fir_root_dir vendor audio_fifo_ctrl_v1.0] [file join $fir_root_dir vendor rgb2dvi_v1_2]] [current_project]
update_ip_catalog
add_files -norecurse [file join $fir_root_dir rtl hdmi_framebuffer.v]
add_files -norecurse [file join $fir_root_dir rtl video_smooth_router.v]
create_bd_design fir_system
create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7_0
source [file join $fir_root_dir scripts ps7_preset.tcl]
set_property -dict [list CONFIG.PCW_USE_M_AXI_GP0 {1} CONFIG.PCW_USE_M_AXI_GP1 {0} \
    CONFIG.PCW_USE_S_AXI_GP0 {0} CONFIG.PCW_USE_S_AXI_GP1 {0} \
    CONFIG.PCW_USE_S_AXI_HP0 {1} CONFIG.PCW_USE_S_AXI_HP1 {0} \
    CONFIG.PCW_USE_S_AXI_HP2 {0} CONFIG.PCW_USE_S_AXI_HP3 {0} \
    CONFIG.PCW_USE_FABRIC_INTERRUPT {0} CONFIG.PCW_IRQ_F2P_INTR {0} \
    CONFIG.PCW_GPIO_EMIO_GPIO_ENABLE {0} CONFIG.PCW_I2C1_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_I2C0_GRP_INT_ENABLE {0} CONFIG.PCW_EN_CLK1_PORT {0} \
    CONFIG.PCW_EN_CLK2_PORT {0} CONFIG.PCW_EN_CLK3_PORT {0} \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100}] [get_bd_cells ps7_0]
make_bd_intf_pins_external [get_bd_intf_pins ps7_0/DDR]
make_bd_intf_pins_external [get_bd_intf_pins ps7_0/FIXED_IO]
create_bd_cell -type ip -vlnv shenghua.org:audio:audio_fir:1.0 audio_fir_0
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma:7.1 axi_dma_0
set_property -dict [list CONFIG.c_include_sg {0} CONFIG.c_sg_length_width {23} \
    CONFIG.c_include_mm2s_dre {1} CONFIG.c_include_s2mm_dre {1} \
    CONFIG.c_m_axi_mm2s_data_width {32} CONFIG.c_m_axi_s2mm_data_width {32} \
    CONFIG.c_m_axis_mm2s_tdata_width {32} CONFIG.c_s_axis_s2mm_tdata_width {32}] [get_bd_cells axi_dma_0]
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 control_bus
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {8}] [get_bd_cells control_bus]
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 memory_bus
set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {1}] [get_bd_cells memory_bus]
create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 reset_0
set_property -dict [list CONFIG.C_EXT_RESET_HIGH {0} CONFIG.C_AUX_RESET_HIGH {1}] [get_bd_cells reset_0]
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 one
set_property CONFIG.CONST_VAL {1} [get_bd_cells one]
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 zero
set_property CONFIG.CONST_VAL {0} [get_bd_cells zero]
connect_bd_net [get_bd_pins one/dout] [get_bd_pins reset_0/dcm_locked]
connect_bd_net [get_bd_pins zero/dout] [get_bd_pins reset_0/aux_reset_in] [get_bd_pins reset_0/mb_debug_sys_rst]
connect_bd_net [get_bd_pins ps7_0/FCLK_RESET0_N] [get_bd_pins reset_0/ext_reset_in]
connect_bd_intf_net [get_bd_intf_pins ps7_0/M_AXI_GP0] [get_bd_intf_pins control_bus/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins control_bus/M00_AXI] [get_bd_intf_pins axi_dma_0/S_AXI_LITE]
connect_bd_intf_net [get_bd_intf_pins control_bus/M01_AXI] [get_bd_intf_pins audio_fir_0/s_axi_control]
connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXI_MM2S] [get_bd_intf_pins memory_bus/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXI_S2MM] [get_bd_intf_pins memory_bus/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins memory_bus/M00_AXI] [get_bd_intf_pins ps7_0/S_AXI_HP0]
create_bd_cell -type module -reference video_smooth_router video_filter
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 video_control
set_property -dict [list CONFIG.C_GPIO_WIDTH {32} CONFIG.C_ALL_OUTPUTS {1}] [get_bd_cells video_control]
connect_bd_intf_net [get_bd_intf_pins control_bus/M07_AXI] [get_bd_intf_pins video_control/S_AXI]
connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins video_control/s_axi_aclk] [get_bd_pins video_filter/clk]
connect_bd_net [get_bd_pins reset_0/peripheral_aresetn] [get_bd_pins video_control/s_axi_aresetn] [get_bd_pins video_filter/resetn]
connect_bd_net [get_bd_pins video_control/gpio_io_o] [get_bd_pins video_filter/config_word]
connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXIS_MM2S] [get_bd_intf_pins video_filter/S_AXIS]
connect_bd_intf_net [get_bd_intf_pins video_filter/AUDIO_IN] [get_bd_intf_pins audio_fir_0/input_r]
connect_bd_intf_net [get_bd_intf_pins audio_fir_0/output_r] [get_bd_intf_pins video_filter/AUDIO_OUT]
connect_bd_intf_net [get_bd_intf_pins video_filter/M_AXIS] [get_bd_intf_pins axi_dma_0/S_AXIS_S2MM]
foreach pin {ps7_0/M_AXI_GP0_ACLK ps7_0/S_AXI_HP0_ACLK audio_fir_0/ap_clk \
             axi_dma_0/s_axi_lite_aclk axi_dma_0/m_axi_mm2s_aclk axi_dma_0/m_axi_s2mm_aclk reset_0/slowest_sync_clk} {
    connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins $pin]
}
foreach cell {control_bus memory_bus} {
    foreach pin [get_bd_pins -of_objects [get_bd_cells $cell] -filter {TYPE == clk}] {
        connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] $pin
    }
    foreach pin [get_bd_pins -of_objects [get_bd_cells $cell] -filter {TYPE == rst}] {
        connect_bd_net [get_bd_pins reset_0/peripheral_aresetn] $pin
    }
}
connect_bd_net [get_bd_pins reset_0/peripheral_aresetn] [get_bd_pins axi_dma_0/axi_resetn] [get_bd_pins audio_fir_0/ap_rst_n]

make_bd_intf_pins_external [get_bd_intf_pins ps7_0/IIC_1]
set_property name IIC_1 [get_bd_intf_ports IIC_1_0]
create_bd_cell -type ip -vlnv xilinx.com:user:audio_codec_ctrl:1.0 audio_codec_ctrl_0
create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 clk_wiz_10MHz
set_property -dict [list CONFIG.PRIM_IN_FREQ {100} CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {10} CONFIG.RESET_TYPE {ACTIVE_LOW} CONFIG.RESET_PORT {resetn}] [get_bd_cells clk_wiz_10MHz]
connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins clk_wiz_10MHz/clk_in1] [get_bd_pins audio_codec_ctrl_0/s_axi_aclk]
connect_bd_net [get_bd_pins reset_0/peripheral_aresetn] [get_bd_pins clk_wiz_10MHz/resetn] [get_bd_pins audio_codec_ctrl_0/s_axi_aresetn]
foreach name {bclk lrclk sdata_o} {
 create_bd_port -dir O $name
 connect_bd_net [get_bd_ports $name] [get_bd_pins audio_codec_ctrl_0/$name]
}
create_bd_port -dir I sdata_i
connect_bd_net [get_bd_ports sdata_i] [get_bd_pins audio_codec_ctrl_0/sdata_i]
create_bd_port -dir O -from 1 -to 0 codec_addr
connect_bd_net [get_bd_ports codec_addr] [get_bd_pins audio_codec_ctrl_0/codec_address]
create_bd_port -dir O -type clk audio_clk_10MHz
connect_bd_net [get_bd_ports audio_clk_10MHz] [get_bd_pins clk_wiz_10MHz/clk_out1]
connect_bd_intf_net [get_bd_intf_pins control_bus/M02_AXI] [get_bd_intf_pins audio_codec_ctrl_0/S_AXI]
foreach {name port index input} {btns_gpio btns_4bits 03 1 leds_gpio leds_4bits 04 0} {
 create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 $name
 set_property -dict [list CONFIG.C_GPIO_WIDTH {4} CONFIG.C_ALL_INPUTS $input CONFIG.C_ALL_OUTPUTS [expr {!$input}] CONFIG.C_INTERRUPT_PRESENT {0}] [get_bd_cells $name]
 make_bd_intf_pins_external [get_bd_intf_pins $name/GPIO]
 set_property name $port [get_bd_intf_ports GPIO_0]
 connect_bd_intf_net [get_bd_intf_pins control_bus/M${index}_AXI] [get_bd_intf_pins $name/S_AXI]
 connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins $name/s_axi_aclk]
 connect_bd_net [get_bd_pins reset_0/peripheral_aresetn] [get_bd_pins $name/s_axi_aresetn]
}

create_bd_cell -type ip -vlnv xilinx.com:ip:axi_bram_ctrl:4.1 screen_bram
set_property -dict [list CONFIG.DATA_WIDTH {32} CONFIG.SINGLE_PORT_BRAM {1} CONFIG.ECC_TYPE {0}] [get_bd_cells screen_bram]
create_bd_cell -type ip -vlnv xilinx.com:ip:blk_mem_gen:8.4 screen_memory
set_property -dict [list CONFIG.Memory_Type {True_Dual_Port_RAM} CONFIG.Use_Byte_Write_Enable {true} CONFIG.Byte_Size {8} CONFIG.Write_Width_A {32} CONFIG.Read_Width_A {32} CONFIG.Write_Depth_A {131072} CONFIG.Write_Width_B {32} CONFIG.Read_Width_B {32} CONFIG.Register_PortB_Output_of_Memory_Primitives {false} CONFIG.Enable_B {Use_ENB_Pin}] [get_bd_cells screen_memory]
connect_bd_intf_net [get_bd_intf_pins screen_bram/BRAM_PORTA] [get_bd_intf_pins screen_memory/BRAM_PORTA]
connect_bd_intf_net [get_bd_intf_pins control_bus/M05_AXI] [get_bd_intf_pins screen_bram/S_AXI]
connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins screen_bram/s_axi_aclk]
connect_bd_net [get_bd_pins reset_0/peripheral_aresetn] [get_bd_pins screen_bram/s_axi_aresetn]
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 screen_control
set_property -dict [list CONFIG.C_IS_DUAL {1} CONFIG.C_GPIO_WIDTH {2} CONFIG.C_ALL_OUTPUTS {1} CONFIG.C_GPIO2_WIDTH {2} CONFIG.C_ALL_INPUTS_2 {1}] [get_bd_cells screen_control]
connect_bd_intf_net [get_bd_intf_pins control_bus/M06_AXI] [get_bd_intf_pins screen_control/S_AXI]
connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins screen_control/s_axi_aclk]
connect_bd_net [get_bd_pins reset_0/peripheral_aresetn] [get_bd_pins screen_control/s_axi_aresetn]
create_bd_cell -type module -reference hdmi_framebuffer screen_raster
connect_bd_net [get_bd_pins screen_control/gpio_io_o] [get_bd_pins screen_raster/control]
connect_bd_net [get_bd_pins screen_raster/status] [get_bd_pins screen_control/gpio2_io_i]
create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 screen_clock
set_property -dict [list CONFIG.PRIM_IN_FREQ {100} CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {74.25} CONFIG.CLKOUT2_USED {true} CONFIG.CLKOUT2_REQUESTED_OUT_FREQ {371.25} CONFIG.RESET_TYPE {ACTIVE_LOW} CONFIG.RESET_PORT {resetn}] [get_bd_cells screen_clock]
connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins screen_clock/clk_in1]
connect_bd_net [get_bd_pins reset_0/peripheral_aresetn] [get_bd_pins screen_clock/resetn]
connect_bd_net [get_bd_pins screen_clock/clk_out1] [get_bd_pins screen_raster/pixel_clk] [get_bd_pins screen_memory/clkb]
connect_bd_net [get_bd_pins screen_clock/locked] [get_bd_pins screen_raster/resetn]
connect_bd_net [get_bd_pins screen_raster/mem_addr] [get_bd_pins screen_memory/addrb]
connect_bd_net [get_bd_pins screen_memory/doutb] [get_bd_pins screen_raster/mem_data]
connect_bd_net [get_bd_pins one/dout] [get_bd_pins screen_memory/enb]
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 screen_zero4
set_property -dict [list CONFIG.CONST_WIDTH {4} CONFIG.CONST_VAL {0}] [get_bd_cells screen_zero4]
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 screen_zero32
set_property -dict [list CONFIG.CONST_WIDTH {32} CONFIG.CONST_VAL {0}] [get_bd_cells screen_zero32]
connect_bd_net [get_bd_pins screen_zero4/dout] [get_bd_pins screen_memory/web]
connect_bd_net [get_bd_pins screen_zero32/dout] [get_bd_pins screen_memory/dinb]
connect_bd_net [get_bd_pins zero/dout] [get_bd_pins screen_memory/rstb]
create_bd_cell -type ip -vlnv digilentinc.com:ip:rgb2dvi:1.2 hdmi_encoder
set_property -dict [list CONFIG.kClkRange {2} CONFIG.kGenerateSerialClk {false} CONFIG.kRstActiveHigh {false}] [get_bd_cells hdmi_encoder]
connect_bd_net [get_bd_pins screen_clock/clk_out1] [get_bd_pins hdmi_encoder/PixelClk]
connect_bd_net [get_bd_pins screen_clock/clk_out2] [get_bd_pins hdmi_encoder/SerialClk]
connect_bd_net [get_bd_pins screen_clock/locked] [get_bd_pins hdmi_encoder/aRst_n]
foreach {src dst} {rgb vid_pData de vid_pVDE hsync vid_pHSync vsync vid_pVSync} {
 connect_bd_net [get_bd_pins screen_raster/$src] [get_bd_pins hdmi_encoder/$dst]
}
foreach {name pin} {hdmi_out_clk_p TMDS_Clk_p hdmi_out_clk_n TMDS_Clk_n} {
 create_bd_port -dir O $name
 connect_bd_net [get_bd_ports $name] [get_bd_pins hdmi_encoder/$pin]
}
foreach {name pin} {hdmi_out_data_p TMDS_Data_p hdmi_out_data_n TMDS_Data_n} {
 create_bd_port -dir O -from 2 -to 0 $name
 connect_bd_net [get_bd_ports $name] [get_bd_pins hdmi_encoder/$pin]
}
create_bd_port -dir O -from 0 -to 0 hdmi_out_hpd
connect_bd_net [get_bd_pins one/dout] [get_bd_ports hdmi_out_hpd]

assign_bd_address
foreach {name offset} {axi_dma_0 0x40400000 audio_fir_0 0x43C10000 audio_codec_ctrl_0 0x43C00000 btns_gpio 0x41210000 leds_gpio 0x41250000 video_control 0x41270000} {
 set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces ps7_0/Data] -filter "NAME =~ *${name}*"]
 set_property offset $offset $seg
}
set_property range 512K [get_bd_addr_segs ps7_0/Data/SEG_screen_bram_Mem0]
set_property offset 0x42000000 [get_bd_addr_segs ps7_0/Data/SEG_screen_bram_Mem0]
set_property offset 0x41260000 [get_bd_addr_segs ps7_0/Data/SEG_screen_control_Reg]
validate_bd_design
save_bd_design
set_property synth_checkpoint_mode None [get_files fir_system.bd]
generate_target all [get_files fir_system.bd]
set wrapper [make_wrapper -files [get_files fir_system.bd] -top]
add_files -norecurse $wrapper
add_files -fileset constrs_1 [file join $fir_root_dir vendor hdmi_audio.xdc]
set_property top fir_system_wrapper [current_fileset]
update_compile_order -fileset sources_1
set ext_clocks [get_files -all -quiet *rgb2dvi_clocks.xdc]
if {[llength $ext_clocks]} {set_property IS_ENABLED false $ext_clocks}
synth_design -top fir_system_wrapper -part xc7z020clg400-1
# Control is held stable by software until frame-boundary acknowledgement.
# Only the first stage of the explicit two-flop CDC is asynchronous.
set sync_inputs [get_pins -hier -filter {NAME =~ */control_meta_reg*/D}]
if {[llength $sync_inputs] != 2} {error "Expected two HDMI control synchronizers"}
set_false_path -to $sync_inputs
opt_design
place_design
route_design
set out [file join $fir_root_dir build video_effects_output]
file mkdir $out
report_timing_summary -report_unconstrained -file [file join $out timing.rpt]
report_utilization -file [file join $out utilization.rpt]
report_drc -file [file join $out drc.rpt]
if {[get_property SLACK [get_timing_paths -delay_type max -max_paths 1]] < 0} {error "Timing failed"}
write_checkpoint -force [file join $out routed.dcp]
write_bitstream -force [file join $out audio_live.bit]
file copy -force [file join $fir_root_dir build video_effects video_effects.gen sources_1 bd fir_system hw_handoff fir_system.hwh] [file join $out audio_live.hwh]
set ok [open [file join $out BUILD_OK] w]
puts $ok "Combined FIR, codec, buttons and LEDs."
close $ok
exit

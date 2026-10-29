set fir_root_dir [file normalize [file join [file dirname [info script]] ..]]
cd $fir_root_dir
open_project -reset build/fir_accel
set_top audio_fir
open_solution -reset solution1 -flow_target vivado
add_files -cflags "-I[file join $fir_root_dir hls]" hls/fir_kernel.cpp
add_files -tb -cflags "-I[file join $fir_root_dir hls]" hls/test_audio_fir.cpp
# This Windows installation serializes design files with an incorrect relative
# path and tb="false"; normalize the generated project metadata before reopening.
close_project
set fir_app_path [file join $fir_root_dir build fir_accel hls.app]
set fir_fd [open $fir_app_path r]
set fir_app_text [read $fir_fd]
close $fir_fd
regsub {name="[^"]*fir_kernel.cpp"} $fir_app_text "name=\"[file join $fir_root_dir hls fir_kernel.cpp]\"" fir_app_text
set fir_app_text [string map {tb="false" tb="0" blackbox="false" blackbox="0"} $fir_app_text]
set fir_fd [open $fir_app_path w]
puts $fir_fd $fir_app_text
close $fir_fd
open_project [file join $fir_root_dir build fir_accel]
open_solution solution1 -flow_target vivado
set_part xc7z020clg400-1
create_clock -period 10 -name default
csynth_design
csim_design
cosim_design -rtl verilog -trace_level none
export_design -format ip_catalog -rtl verilog -vendor shenghua.org -library audio -version 1.0
exit





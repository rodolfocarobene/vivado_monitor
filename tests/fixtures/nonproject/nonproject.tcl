# Non-project flow: vivado -mode batch -source nonproject.tcl -tclargs <part> <outdir>
set part [lindex $argv 0]
set out [lindex $argv 1]
set_param general.maxThreads 4
file mkdir $out
read_verilog [file normalize ../../src/top.v]
read_xdc [file normalize ../../src/top.xdc]
synth_design -top top -part $part
write_checkpoint -force $out/post_synth.dcp
report_utilization -file $out/post_synth_util.rpt
opt_design
place_design
report_utilization -file $out/post_place_util.rpt
phys_opt_design
route_design
report_timing_summary -file $out/post_route_timing_summary.rpt
report_utilization -file $out/post_route_util.rpt
write_checkpoint -force $out/post_route.dcp
if {[string match xcv* $part]} { write_device_image -force $out/top.pdi } else { write_bitstream -force $out/top.bit }

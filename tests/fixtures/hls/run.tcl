open_project -reset dot_prj
set_top dot
add_files dot.cpp
open_solution -reset sol1 -flow_target vivado
set_part xc7a35tcpg236-1
create_clock -period 5
csynth_design
export_design -format ip_catalog
exit

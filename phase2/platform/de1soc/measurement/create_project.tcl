# quartus_sh -t create_project.tcl REPO_ROOT MEASUREMENT_DIRECTORY BUILD_DIRECTORY
package require ::quartus::project
if {[llength $quartus(args)] != 3} {
    error "Usage: create_project.tcl REPO_ROOT MEASUREMENT_DIRECTORY BUILD_DIRECTORY"
}
lassign $quartus(args) repo measurement build
set repo [file normalize $repo]
set measurement [file normalize $measurement]
set build [file normalize $build]
foreach required [list [file join $repo filelists rtl_core_plus_fft.f] \
    [file join $measurement trecap_measurement_engine.sv] \
    [file join $measurement trecap_measurement_top.sv] \
    [file join $measurement measurement.sdc]] {
    if {![file isfile $required]} { error "Missing required input: $required" }
}
file mkdir $build
cd $build
project_new trecap_measurement -revision trecap_measurement
set_global_assignment -name FAMILY "Cyclone V"
set_global_assignment -name DEVICE 5CSEMA5F31C6
set_global_assignment -name TOP_LEVEL_ENTITY trecap_measurement_top
set_global_assignment -name PROJECT_OUTPUT_DIRECTORY output_files
set_global_assignment -name VERILOG_MACRO SYNTHESIS=1
set_global_assignment -name MIN_CORE_JUNCTION_TEMP 0
set_global_assignment -name MAX_CORE_JUNCTION_TEMP 85
set_global_assignment -name NUM_PARALLEL_PROCESSORS 4
set_global_assignment -name RESERVE_ALL_UNUSED_PINS "AS INPUT TRI-STATED"
set_global_assignment -name SEARCH_PATH $repo
set_global_assignment -name SEARCH_PATH $measurement
set_global_assignment -name SDC_FILE [file join $measurement measurement.sdc]

set fd [open [file join $repo filelists rtl_core_plus_fft.f] r]
set filelist [read $fd]
close $fd
foreach raw [split $filelist \n] {
    set line [string trim $raw]
    if {$line eq "" || [string match {#*} $line]} { continue }
    if {[string match {+incdir+*} $line]} {
        set_global_assignment -name SEARCH_PATH [file join $repo [string range $line 8 end]]
    } elseif {[string match {*.sv} $line] || [string match {*.v} $line]} {
        set source [file join $repo $line]
        if {![file isfile $source]} { error "Missing RTL source: $source" }
        set_global_assignment -name SYSTEMVERILOG_FILE $source
    } else { error "Unsupported filelist entry: $line" }
}
set_global_assignment -name SYSTEMVERILOG_FILE [file join $measurement trecap_measurement_engine.sv]
set_global_assignment -name SYSTEMVERILOG_FILE [file join $measurement trecap_measurement_top.sv]
set_location_assignment PIN_AF14 -to CLOCK_50
set_location_assignment PIN_AA14 -to {KEY[0]}
foreach {index pin} {0 V16 1 W16 2 V17 3 V18 4 W17 5 W19 6 Y19 7 W20 8 W21 9 Y21} {
    set_location_assignment PIN_$pin -to [format {LEDR[%d]} $index]
}
foreach port {CLOCK_50 {KEY[0]} {LEDR[*]}} {
    set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to $port
}
export_assignments
project_close
puts "Created standalone measurement project: [file join $build trecap_measurement.qpf]"

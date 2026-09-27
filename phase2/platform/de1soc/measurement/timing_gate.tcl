# quartus_sta -t timing_gate.tcl BUILD_DIRECTORY
# Gate the actual fitted CLOCK_50 fabric at every available operating corner.
package require ::quartus::project
package require ::quartus::sta
if {[llength $quartus(args)] != 1} { error "Usage: timing_gate.tcl BUILD_DIRECTORY" }
set build [file normalize [lindex $quartus(args) 0]]
cd $build
project_open trecap_measurement -revision trecap_measurement
create_timing_netlist
read_sdc
update_timing_netlist
set clocks [get_clocks CLOCK_50]
if {[get_collection_size $clocks] != 1} { error "Missing unique CLOCK_50 timing clock" }
foreach_in_collection clk $clocks {
    if {abs([get_clock_info -period $clk] - 20.0) > 0.00001} {
        error "CLOCK_50 is not constrained to 20 ns"
    }
}
set reportdir [file join $build timing_gate]
file mkdir $reportdir
set fd [open [file join $reportdir corners.csv] w]
puts $fd "corner,check,slack_ns"
set failed 0
set corner_count 0
foreach_in_collection op [get_available_operating_conditions] {
    incr corner_count
    set_operating_conditions $op
    update_timing_netlist
    set corner [get_operating_conditions_info -name $op]
    set safe [string map {" " _ / _ \\ _ : _} $corner]
    foreach check {setup hold recovery removal} {
        set paths [get_timing_paths -$check -from_clock CLOCK_50 -to_clock CLOCK_50 -npaths 1]
        if {[get_collection_size $paths] == 0} {
            if {$check eq "setup" || $check eq "hold"} {
                error "No CLOCK_50 $check paths at $corner"
            }
            puts $fd "$corner,$check,not_applicable"
            continue
        }
        foreach_in_collection path $paths {
            set slack [get_path_info -slack $path]
            puts $fd "$corner,$check,$slack"
            if {![string is double -strict $slack] || $slack < 0.0} { set failed 1 }
        }
        report_timing -$check -from_clock CLOCK_50 -to_clock CLOCK_50 -npaths 5 \
            -detail full_path -file [file join $reportdir ${safe}_${check}.rpt]
    }
    check_timing -include {no_clock multiple_clock loops latches generated_clock} \
        -file [file join $reportdir ${safe}_constraint_checks.rpt]
    report_ucp -file [file join $reportdir ${safe}_unconstrained.rpt]
}
close $fd
delete_timing_netlist
project_close
if {$corner_count == 0 || $failed} { error "Fitted CLOCK_50 timing gate FAILED; see $reportdir" }
set fd [open [file join $reportdir PASS.txt] w]
puts $fd "PASS: fitted CLOCK_50 setup/hold and applicable recovery/removal, $corner_count corners, period 20 ns."
puts $fd "JTAG clock domain and asynchronous external reset are outside this fabric gate; review constraint reports separately."
close $fd
puts "PASS: fitted CLOCK_50 timing gate ($corner_count corners)"

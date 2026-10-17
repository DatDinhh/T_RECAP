# Independent fitted-netlist reports. Never exports project assignments.
package require ::quartus::project
package require ::quartus::sta
if {[llength $quartus(args)] != 2} {error "Usage: timing_review.tcl BUILD OUTPUT"}
set build [file normalize [lindex $quartus(args) 0]]
set dest [file normalize [lindex $quartus(args) 1]]
file mkdir $dest
cd $build
project_open audio_hps -revision audio_hps
create_timing_netlist
read_sdc
update_timing_netlist
set clockfile [open [file join $dest clocks.tsv] w]
puts $clockfile "clock\tperiod_ns"
foreach_in_collection clock [get_clocks *] {
    puts $clockfile "[get_clock_info -name $clock]\t[get_clock_info -period $clock]"
}
close $clockfile
set cf [open [file join $dest corners.tsv] w]
puts $cf "corner\tclock\tcheck\tslack_ns\tfrom\tto"
set index 0
foreach_in_collection condition [get_available_operating_conditions] {
    set_operating_conditions $condition
    update_timing_netlist
    set corner [get_operating_conditions_info -name $condition]
    set safe [string map {" " _ / _ \\ _ : _} $corner]
    set ci 0
    foreach_in_collection clock [get_clocks *] {
        set name [get_clock_info -name $clock]
        foreach check {setup hold recovery removal} {
            set paths [get_timing_paths -$check -to_clock $clock -npaths 1]
            if {[get_collection_size $paths]==0} {
                puts $cf "$corner\t$name\t$check\tN/A\t\t"
            } else {
                foreach_in_collection path $paths {
                    puts $cf "$corner\t$name\t$check\t[get_path_info -slack $path]\t[get_node_info -name [get_path_info -from $path]]\t[get_node_info -name [get_path_info -to $path]]"
                }
            }
        }
        incr ci
    }
    foreach check {setup hold recovery removal} {
        report_timing -$check -to_clock [get_clocks CLOCK_50] -npaths 10 -detail full_path -file [file join $dest ${safe}_fabric_${check}.rpt]
    }
    check_timing -include {no_clock multiple_clock loops latches generated_clock} -file [file join $dest ${safe}_constraint_checks.rpt]
    report_ucp -file [file join $dest ${safe}_unconstrained.rpt]
    report_clocks -file [file join $dest ${safe}_clocks.rpt]
    report_min_pulse_width -nworst 10 -file [file join $dest ${safe}_min_pulse_width.rpt]
    incr index
}
close $cf
delete_timing_netlist
project_close -dont_export_assignments
puts "INDEPENDENT_HPS_TIMING_REPORTS_COMPLETE corners=$index"

# SPDX-License-Identifier: MIT
# Run with quartus_sta after Analysis & Synthesis. Keep the vendor pin script
# unmodified and retain only its assignment commands in a generated QSF include.
package require ::quartus::project

namespace eval ::trecap_ddr_capture {
    variable commands {}
    variable wrapped {}
}

proc ::trecap_ddr_capture::record {command arguments} {
    variable commands
    set result [uplevel 1 [linsert $arguments 0 ::trecap_ddr_capture::native_$command]]
    lappend commands [linsert $arguments 0 $command]
    return $result
}

proc ::trecap_ddr_capture::install {} {
    variable wrapped
    foreach command {set_global_assignment set_instance_assignment remove_all_instance_assignments} {
        rename ::$command ::trecap_ddr_capture::native_$command
        lappend wrapped $command
        proc ::$command {args} [format {
            return [::trecap_ddr_capture::record %s $args]
        } $command]
    }
}

proc ::trecap_ddr_capture::restore {} {
    variable wrapped
    foreach command $wrapped {
        rename ::$command {}
        rename ::trecap_ddr_capture::native_$command ::$command
    }
    set wrapped {}
}

proc ::trecap_ddr_capture::option {command key} {
    set index [lsearch -exact $command $key]
    if {$index < 0 || $index + 1 >= [llength $command]} {
        error "Vendor assignment is missing $key: $command"
    }
    return [lindex $command [expr {$index + 1}]]
}

proc ::trecap_ddr_capture::vector_pins {base width} {
    set pins {}
    for {set index 0} {$index < $width} {incr index} {
        lappend pins [format {%s[%d]} $base $index]
    }
    return $pins
}

proc ::trecap_ddr_capture::validate {} {
    variable commands
    if {![array exists ::ddr_db] || [array size ::ddr_db] != 1} {
        error "Expected one detected HPS DDR interface in the post-map netlist"
    }
    set data [vector_pins HPS_DDR3_DQ 32]
    set strobes [concat [vector_pins HPS_DDR3_DQS_P 4] [vector_pins HPS_DDR3_DQS_N 4]]
    set masks [vector_pins HPS_DDR3_DM 4]
    set clocks {HPS_DDR3_CK_P HPS_DDR3_CK_N}
    set expected_io [concat $data $strobes $masks $clocks \
        [vector_pins HPS_DDR3_ADDR 15] [vector_pins HPS_DDR3_BA 3] \
        {HPS_DDR3_CAS_N HPS_DDR3_CKE HPS_DDR3_CS_N HPS_DDR3_ODT HPS_DDR3_RAS_N HPS_DDR3_RESET_N HPS_DDR3_RZQ HPS_DDR3_WE_N}]
    set observed_io {}
    set observed_input {}
    set observed_output {}
    foreach command $commands {
        if {[lindex $command 0] ne "set_instance_assignment"} { continue }
        set name [option $command -name]
        set target [option $command -to]
        if {[option $command -tag] ne "__hps_sdram_p0"} {
            error "Unexpected vendor assignment tag: $command"
        }
        if {$name eq "IO_STANDARD"} {
            if {[lsearch -exact [concat $strobes $clocks] $target] >= 0} {
                set expected_value "DIFFERENTIAL 1.5-V SSTL CLASS I"
            } else {
                set expected_value "SSTL-15 CLASS I"
            }
            if {[lindex $command [expr {[lsearch -exact $command -name] + 2}]] ne $expected_value} {
                error "Unexpected HPS DDR I/O standard: $command"
            }
            lappend observed_io $target
        } elseif {$name eq "INPUT_TERMINATION"} {
            if {[lindex $command [expr {[lsearch -exact $command -name] + 2}]] ne "PARALLEL 50 OHM WITH CALIBRATION"} {
                error "Unexpected HPS DDR input termination: $command"
            }
            lappend observed_input $target
        } elseif {$name eq "OUTPUT_TERMINATION"} {
            set value [lindex $command [expr {[lsearch -exact $command -name] + 2}]]
            if {[lsearch -exact $clocks $target] >= 0} {
                if {$value ne "SERIES 50 OHM WITHOUT CALIBRATION"} {
                    error "Unexpected HPS DDR clock termination: $command"
                }
            } else {
                if {$value ne "SERIES 50 OHM WITH CALIBRATION"} {
                    error "Unexpected HPS DDR output termination: $command"
                }
                lappend observed_output $target
            }
        }
    }
    foreach {label actual expected} [list \
        IO_STANDARD $observed_io $expected_io \
        INPUT_TERMINATION $observed_input [concat $data $strobes] \
        OUTPUT_TERMINATION $observed_output [concat $data $strobes $masks]] {
        if {[lsort -unique $actual] ne [lsort -unique $expected]} {
            error "Detected HPS DDR $label targets do not match the DE1-SoC interface: $actual"
        }
    }
    post_message -type info "T-RECAP: captured 72 DDR I/O standards, 40 calibrated input and 44 calibrated output terminations"
}

proc ::trecap_ddr_capture::run {} {
    variable commands
    if {[llength $::quartus(args)] != 5} {
        error "Usage: quartus_sta -t capture_hps_ddr_assignments.tcl <project> <revision> <vendor-script> <output-qsf> <python>"
    }
    lassign $::quartus(args) project revision vendor_script output_qsf python
    set vendor_script [file normalize $vendor_script]
    set output_qsf [file normalize $output_qsf]
    if {![file isfile $vendor_script]} { error "Missing generated DDR pin script: $vendor_script" }
    if {[is_project_open]} { error "DDR capture must start without an open project" }
    set pin_dump [file normalize [file join [pwd] hps_sdram_p0_all_pins.txt]]
    set original_args $::quartus(args)
    set result [catch {
        # Open before interception: source-owned/profile assignments must not
        # become part of this generated vendor-only snapshot.
        project_open $project -revision $revision
        install
        set ::quartus(args) [list -c $revision $project]
        uplevel #0 [list source $vendor_script]
        restore
        validate
        # No normal or exceptional exit may auto-export a flattened project QSF.
        project_close -dont_export_assignments
        file mkdir [file dirname $output_qsf]
        if {![file isfile $pin_dump]} { error "Vendor DDR pin dump is missing: $pin_dump" }
        set retained_dump [file join [file dirname $output_qsf] hps_sdram_p0_all_pins.txt]
        exec $python -c {import os,sys;os.replace(sys.argv[1],sys.argv[2])} $pin_dump $retained_dump
        set staging "${output_qsf}.tmp.[pid]"
        set channel [open $staging w]
        fconfigure $channel -translation lf -encoding utf-8
        puts $channel "# Generated HPS DDR assignments; regenerate after map. Do not edit."
        puts $channel "# Source: Platform Designer hps_sdram_p0_pin_assignments.tcl"
        foreach command $commands {
            # Each captured command is a Tcl list, preserving literal brackets,
            # spaces and hierarchy separators without re-evaluating pin names.
            puts $channel $command
        }
        close $channel
        # Python also handles replacement of an existing target on Windows;
        # the temporary file is beside its destination for atomic publication.
        exec $python -c {import os,sys;os.replace(sys.argv[1],sys.argv[2])} $staging $output_qsf
        post_message -type info "T-RECAP: wrote [llength $commands] DDR assignment commands to $output_qsf"
    } message options]
    set ::quartus(args) $original_args
    restore
    if {[is_project_open]} { project_close -dont_export_assignments }
    if {$result} { return -options $options $message }
}

if {[catch {::trecap_ddr_capture::run} message]} {
    # run closes the project before returning errors; qexit cannot auto-export it.
    post_message -type error "T-RECAP DDR assignment capture failed: $message"
    qexit -error
}

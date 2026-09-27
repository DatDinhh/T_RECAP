# Quartus 20.1 In-System Sources/Probes helper. Sourcing this file only defines
# functions unless quartus(args) starts with "campaign". No discovery defaults:
# the caller supplies the exact hardware and device names.
#
# quartus_stp -t jtag_zero_control.tcl campaign HARDWARE DEVICE OUT_JSONL EPOCHS BLOCKS IDLE_MS TIMEOUT_MS
# Protocol2: one block is masked_baseline, masked_isolated, masked_isolated, masked_baseline. One-epoch admission in each mode,
# 20 s idle, 4096-epoch warmup in each mode, and idle_ms idle precede the blocks.
# A final 20 s idle closes the campaign. All writes, snapshots and trials log
# UTC Unix milliseconds. No per-poll subprocess is used.

namespace eval trecap {
    variable connected 0
    variable logfd ""
    variable instance -1
    variable command 0
}

proc trecap::json_quote {text} {
    return "\"[string map [list \\ \\\\ \" \\\" \n \\n \r \\r \t \\t] $text]\""
}

proc trecap::emit {record} {
    variable logfd
    set fields {}
    dict for {key value} $record {
        if {![string match *_hex $key] && [string is wideinteger -strict $value]} {
            set encoded [expr {wide($value)}]
        } elseif {$value eq "true" || $value eq "false"} {
            set encoded $value
        } else { set encoded [json_quote $value] }
        lappend fields "[json_quote $key]:$encoded"
    }
    set line "\{[join $fields ,]\}"
    if {$logfd ne ""} { puts $logfd $line; flush $logfd }
    puts $line
    flush stdout
}

proc trecap::connect {hardware device output_jsonl} {
    variable connected
    variable instance
    variable command
    variable logfd
    if {$connected} { error "A measurement JTAG connection is already open" }
    package require ::quartus::insystem_source_probe
    set matches {}
    foreach info [get_insystem_source_probe_instance_info -hardware_name $hardware -device_name $device] {
        lassign $info index source_width probe_width name
        if {$name eq "TREC" && $source_width == 32 && $probe_width == 480} {
            lappend matches $index
        }
    }
    if {[llength $matches] != 1} { error "Expected exactly one TREC instance with source32/probe480" }
    set instance [lindex $matches 0]
    set logfd [open $output_jsonl {WRONLY CREAT EXCL}]
    fconfigure $logfd -translation lf -encoding utf-8
    if {[catch {
        start_insystem_source_probe -hardware_name $hardware -device_name $device
        set connected 1
        set raw [string trim [read_source_data -instance_index $instance -value_in_hex]]
        if {![regexp {^[0-9a-fA-F]{1,8}$} $raw]} { error "Invalid source readback: $raw" }
        scan $raw %x command
        if {$command & 0x0000fff0} { error "Reserved source command bits are nonzero" }
        emit [dict create event connected utc_ms [clock milliseconds] hardware $hardware device $device \
            instance $instance command_hex [format %08X $command]]
    } message options]} {
        disconnect
        return -options $options $message
    }
}

proc trecap::disconnect {} {
    variable connected
    variable logfd
    if {$connected} {
        catch {end_insystem_source_probe}
        set connected 0
    }
    if {$logfd ne ""} { catch {close $logfd}; set logfd "" }
}

proc trecap::write {value event} {
    variable connected
    variable instance
    variable command
    if {!$connected} { error "Measurement JTAG is not connected" }
    if {![string is wideinteger -strict $value] || $value < 0 || $value > 0xffffffff} {
        error "Source value is not an unsigned 32-bit integer"
    }
    set hex [format %08X $value]
    set before [clock milliseconds]
    write_source_data -instance_index $instance -value $hex -value_in_hex
    set after [clock milliseconds]
    set command $value
    emit [dict create event $event before_utc_ms $before after_utc_ms $after command_hex $hex]
    return [list $before $after]
}

proc trecap::decode {raw} {
    set hex [string toupper [string trim $raw]]
    if {![regexp {^[0-9A-F]{1,120}$} $hex]} { error "Invalid 480-bit probe readback: $raw" }
    set hex "[string repeat 0 [expr {120 - [string length $hex]}]]$hex"
    set words {}
    for {set i 0} {$i < 15} {incr i} {
        set right [expr {119 - 8 * $i}]
        scan [string range $hex [expr {$right - 7}] $right] %x word
        lappend words $word
    }
    if {[lindex $words 0] != 0x54524350} { error "Probe magic does not match T-RECAP measurement protocol" }
    set status [lindex $words 1]
    if {(($status >> 24) & 0xff) != 2} { error "Expected zero-isolation measurement protocol2" }
    return [dict create probe_hex $hex words $words status $status \
        busy [expr {$status & 1}] done [expr {($status >> 1) & 1}] \
        snapshot_ack [expr {($status >> 9) & 1}] \
        consumed_start [expr {($status >> 8) & 1}]]
}

proc trecap::snapshot {{timeout_ms 1000}} {
    variable instance
    variable command
    set request [expr {$command ^ 8}]
    set wanted [expr {($request >> 3) & 1}]
    lassign [write $request snapshot_request] transaction_before request_after
    # Source crosses into CLOCK_50 through the IP's two registers. The explicit
    # delay also avoids treating a pre-existing snapshot as a new acknowledgement.
    after 2
    set deadline [expr {[clock milliseconds] + $timeout_ms}]
    while {[clock milliseconds] <= $deadline} {
        set read_before [clock milliseconds]
        set raw [read_probe_data -instance_index $instance -value_in_hex]
        set read_after [clock milliseconds]
        set sample [decode $raw]
        if {[dict get $sample snapshot_ack] == $wanted} {
            dict set sample transaction_before_ms $transaction_before
            dict set sample request_after_ms $request_after
            dict set sample read_before_ms $read_before
            dict set sample read_after_ms $read_after
            emit [dict create event snapshot before_utc_ms $transaction_before \
                request_after_utc_ms $request_after read_before_utc_ms $read_before \
                after_utc_ms $read_after command_hex [format %08X $command] \
                probe_hex [dict get $sample probe_hex]]
            return $sample
        }
        after 5
    }
    error "Snapshot acknowledgement timed out after $timeout_ms ms"
}

proc trecap::require_clean {sample} {
    set words [dict get $sample words]
    if {([dict get $sample status] & 0x0c) != 0 || [lindex $words 5] != 0 || [lindex $words 11] != 0} {
        error "Measurement engine reported numerical fault, command rejection or fault flags: [dict get $sample probe_hex]"
    }
}

proc trecap::launch {mode epochs} {
    variable command
    if {$mode < 0 || $mode > 3 || $epochs < 0 || $epochs > 65535 || ($mode != 0 && $epochs == 0)} {
        error "Invalid finite batch mode or epoch count"
    }
    set before [snapshot]
    require_clean $before
    if {[dict get $before busy]} { error "Cannot start a new command while the engine is busy" }
    # Synchronizing each source bit does not make a bus atomic. Prepare all mode
    # and count bits with the old start toggle, allow settling, then change ONLY
    # bit2. All later snapshot requests change ONLY bit3.
    set prepared [expr {($epochs << 16) | $mode | ($command & 0x0c)}]
    write $prepared payload_prepare
    after 2
    set launched [expr {$prepared ^ 4}]
    set bounds [write $launched batch_launch]
    return [dict create before_ms [lindex $bounds 0] after_ms [lindex $bounds 1] \
        start_toggle [expr {($launched >> 2) & 1}] command $launched]
}

proc trecap::idle {{pause_ms 0}} {
    set launched [launch 0 0]
    set sample [snapshot]
    require_clean $sample
    if {[dict get $sample busy] || [dict get $sample consumed_start] != [dict get $launched start_toggle]} {
        error "Idle command was not acknowledged"
    }
    emit [dict create event idle_begin utc_ms [clock milliseconds] duration_ms $pause_ms]
    if {$pause_ms > 0} { after $pause_ms }
    emit [dict create event idle_end utc_ms [clock milliseconds]]
    return $sample
}

proc trecap::run_batch {mode epochs trial_id pair_id timeout_ms} {
    set launched [launch $mode $epochs]
    set launch_before [dict get $launched before_ms]
    set launch_after [dict get $launched after_ms]
    set deadline [expr {$launch_after + $timeout_ms}]
    set last_busy_before $launch_before
    set lower_source launch
    set condition [lindex {idle dense masked_baseline masked_isolated} $mode]
    set threshold [expr {$mode == 1 ? 0 : 100000000000}]
    while {[clock milliseconds] <= $deadline} {
        set sample [snapshot]
        require_clean $sample
        if {[dict get $sample consumed_start] != [dict get $launched start_toggle]} {
            after 5
            continue
        }
        if {[dict get $sample busy]} {
            # Use the beginning of the BUSY snapshot request, not the beginning
            # of its read: the stable snapshot may already be old by read time.
            set last_busy_before [dict get $sample transaction_before_ms]
            set lower_source last_busy_snapshot_request
        } elseif {[dict get $sample done]} {
            set words [dict get $sample words]
            set status [dict get $sample status]
            if {($status & 0x30) != ($mode == 1 ? 0x10 : 0x20) ||
                (($status >> 11) & 1) != ($mode == 3)} {
                error "Mode/isolation status disagrees with requested batch"
            }
            set cycles [expr {([lindex $words 9] << 32) | [lindex $words 8]}]
            if {[lindex $words 3] != $epochs || [lindex $words 4] != $epochs * 1536 ||
                [lindex $words 6] != $epochs * 1024 || [lindex $words 7] != $epochs * 9 ||
                [lindex $words 12] != 1536 || $cycles <= 0 ||
                ([lindex $words 2] & 0xffff0003) != (($epochs << 16) | $mode)} {
                error "Completed batch has unexpected counts, mode or elapsed cycles: [dict get $sample probe_hex]"
            }
            set result [dict create event trial_complete trial_id $trial_id pair_id $pair_id \
                condition $condition threshold2 $threshold \
                launch_before_ms $launch_before launch_after_ms $launch_after \
                completion_before_ms $last_busy_before \
                completion_after_ms [dict get $sample read_after_ms] \
                completion_lower_bound_source $lower_source \
                cycles $cycles epochs [lindex $words 3] outputs [lindex $words 4] \
                useful_inputs [lindex $words 6] frames [lindex $words 7] \
                mismatch_count [lindex $words 5] fault_flags [lindex $words 11] \
                last_epoch_outputs [lindex $words 12] last_epoch_cycles [lindex $words 13] \
                rolling_checksum [lindex $words 14] completed true \
                probe_hex [dict get $sample probe_hex]]
            emit $result
            return $result
        }
        after 100
    }
    error "Finite batch $trial_id timed out after $timeout_ms ms; hardware may still finish its programmed finite batch"
}

proc trecap::campaign {hardware device output_jsonl epochs blocks idle_ms timeout_ms} {
    if {![string is integer -strict $epochs] || $epochs < 1 || $epochs > 65535 ||
        ![string is integer -strict $blocks] || $blocks < 1 || $blocks > 16 ||
        ![string is integer -strict $idle_ms] || $idle_ms < 0 || $idle_ms > 60000 ||
        ![string is integer -strict $timeout_ms] || $timeout_ms < 1000 || $timeout_ms > 600000} {
        error "Campaign arguments exceed finite bounds"
    }
    connect $hardware $device $output_jsonl
    set failed [catch {
        run_batch 1 1 admission_dense 0 $timeout_ms
        run_batch 2 1 admission_masked_baseline 0 $timeout_ms
        run_batch 3 1 admission_masked_isolated 0 $timeout_ms
        idle 20000
        run_batch 2 4096 warmup_masked_baseline 0 $timeout_ms
        run_batch 3 4096 warmup_masked_isolated 0 $timeout_ms
        idle $idle_ms
        set trial 0
        for {set block 1} {$block <= $blocks} {incr block} {
            foreach mode {2 3 3 2} {
                incr trial
                set pair [expr {($trial + 1) / 2}]
                run_batch $mode $epochs [format trial_%03d $trial] $pair $timeout_ms
                if {$trial < $blocks * 4} { idle $idle_ms }
            }
        }
        idle 20000
        set final_snapshot [snapshot]
        require_clean $final_snapshot
        if {[dict get $final_snapshot busy]} { error "Engine unexpectedly busy after final idle" }
        emit [dict create event campaign_complete utc_ms [clock milliseconds] \
            measured_trials $trial epochs_per_trial $epochs completed true]
    } message options]
    if {$failed} { catch {emit [dict create event campaign_error utc_ms [clock milliseconds] error $message completed false]} }
    disconnect
    if {$failed} { return -options $options $message }
}

if {[info exists quartus(args)] && [llength $quartus(args)] > 0 && [lindex $quartus(args) 0] eq "campaign"} {
    if {[llength $quartus(args)] != 8} {
        error "Usage: campaign HARDWARE DEVICE OUT_JSONL EPOCHS BLOCKS IDLE_MS TIMEOUT_MS"
    }
    trecap::campaign {*}[lrange $quartus(args) 1 end]
}

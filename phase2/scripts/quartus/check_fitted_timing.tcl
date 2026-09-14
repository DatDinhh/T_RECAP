# SPDX-License-Identifier: MIT
# Post-fit timing and absolute data-route bounds. Run with quartus_sta, with the
# same TRECAP_PROFILE_QSF and TRECAP_HPS_DDR_QSF as the fitted build.
package require ::quartus::project
package require ::quartus::sta
package require ::quartus::report

namespace eval ::trecap_fitted_timing {
    variable report ""
    variable report_dir ""
    variable failures 0
    variable corner "initialization"
    variable source_root [file normalize [file join [file dirname [info script]] ../..]]
}

proc ::trecap_fitted_timing::row {category check status value bound from to} {
    variable report
    variable corner
    set fields {}
    foreach value [list $corner $category $check $status $value $bound $from $to] {
        lappend fields [string map [list "\t" " " "\r" " " "\n" " "] $value]
    }
    puts $report [join $fields "\t"]
    flush $report
}

proc ::trecap_fitted_timing::fail {category check message} {
    variable failures
    incr failures
    row $category $check FAIL "" "" $message ""
    post_message -type warning "T-RECAP timing gate: $check: $message"
}

proc ::trecap_fitted_timing::node_name {path option} {
    set node [get_path_info $path $option]
    if {$node eq ""} { return "" }
    return [get_node_info $node -name]
}

proc ::trecap_fitted_timing::numeric {value description} {
    if {![string is double -strict $value] || [regexp -nocase {nan|inf} $value]} {
        error "$description is not a finite numeric delay: $value"
    }
    return $value
}

proc ::trecap_fitted_timing::check_slack {type index {clock ""}} {
    variable report_dir
    variable failures
    set options [list -$type -npaths 1]
    set label $type
    if {$clock ne ""} {
        lappend options -from_clock $clock -to_clock $clock
        set label CLOCK_50_$type
    }
    set paths [get_timing_paths {*}$options]
    if {![get_collection_size $paths]} {
        if {$clock ne ""} {
            fail slack $label "Required fabric-clock paths are missing"
        } else {
            row slack $label ABSENT "" 0 "No paths of this type" ""
        }
        return
    }
    foreach_in_collection path $paths {
        set slack [numeric [get_path_info $path -slack] "$label slack"]
        set status [expr {$slack >= 0.0 ? "PASS" : "FAIL"}]
        if {$status eq "FAIL"} { incr failures }
        row slack $label $status $slack 0 [node_name $path -from] [node_name $path -to]
    }
    # Retain the full worst path as well as the compact machine-readable row.
    report_timing {*}$options -detail full_path \
        -file [file join $report_dir [format {corner_%03d_%s.rpt} $index $label]]
}

proc ::trecap_fitted_timing::check_route {label from to bound required {any_source 0}} {
    variable failures
    set source_count [expr {$any_source ? -1 : [get_collection_size $from]}]
    set destination_count [get_collection_size $to]
    if {(!$any_source && !$source_count) || !$destination_count} {
        if {!$required && !$source_count && !$destination_count} {
            row route $label ABSENT_OPTIONAL "" $bound "source_count=$source_count" "destination_count=$destination_count"
        } else {
            fail route $label "Missing endpoints: source_count=$source_count destination_count=$destination_count"
        }
        return
    }
    set options [list -npaths 1 -to $to]
    if {!$any_source} { lappend options -from $from }
    # get_path returns longest data paths without clock information. Its
    # arrival_time is therefore the absolute data delay, with no clock credit.
    set paths [get_path {*}$options]
    if {![get_collection_size $paths]} {
        fail route $label "No connecting fitted path between matched endpoints"
        return
    }
    foreach_in_collection path $paths {
        set delay [numeric [get_path_info $path -arrival_time] "$label data delay"]
        set status [expr {$delay <= $bound ? "PASS" : "FAIL"}]
        if {$status eq "FAIL"} { incr failures }
        row route $label $status $delay $bound [node_name $path -from] [node_name $path -to]
    }
}

proc ::trecap_fitted_timing::regs {pattern} {
    return [get_registers -nowarn $pattern]
}

proc ::trecap_fitted_timing::check_ddr_microtiming {index} {
    variable corner
    variable report_dir
    variable failures
    variable source_root
    set vendor [file join $source_root platform de1soc qsys system synthesis submodules hps_sdram_p0_report_timing.tcl]
    if {![file isfile $vendor]} { error "Missing generated DDR microtiming script: $vendor" }
    # The vendor script expects global scope and uses the currently selected
    # fitted corner. It neither creates source clocks nor edits source SDCs.
    foreach name {instances summary assumptions_valid} { unset -nocomplain ::$name }
    uplevel #0 [list source $vendor]
    if {![info exists ::instances] || [llength $::instances] != 1 ||
        ![info exists ::summary] || ![llength $::summary] ||
        ![info exists ::pins(dqs_pins)] || [llength $::pins(dqs_pins)] != 4} {
        error "Expected one fitted DDR interface with four DQS groups and a nonempty vendor timing summary"
    }
    set valid 1
    if {![info exists ::assumptions_valid] || !$::assumptions_valid} {
        fail ddr_microtiming assumptions "Vendor DDR timing model assumptions did not pass"
        set valid 0
    }
    set required [dict create Write 0 {Read Capture} 0 {Address Command} 0 {DQS vs CK} 0 {Bus Turnaround Time} 0 Postamble 0 Core 0 {Core Recovery/Removal} 0]
    foreach item $::summary {
        if {[llength $item] ni {5 7}} { error "Unexpected vendor DDR summary row: $item" }
        lassign $item condition order label setup hold setup_count hold_count
        set category [string trim [lindex [split $label (] 0]]
        if {![dict exists $required $category]} { error "Unrecognized vendor DDR summary category: $category" }
        set fields [expr {$category in {Core {Core Recovery/Removal}} ? 7 : 5}]
        if {[llength $item] != $fields} { error "DDR $category requires $fields summary fields: $item" }
        if {[string trim $condition] ne [string trim $corner]} {
            error "DDR summary corner '$condition' differs from current fitted corner '$corner'"
        }
        dict incr required $category
        foreach {type margin count} [list setup $setup $setup_count hold $hold $hold_count] {
            if {[llength $item] == 7} {
                if {![string is integer -strict $count] || $count <= 0} {
                    fail ddr_microtiming "${category}_${type}" "Missing positive vendor timing-path count: '$count'"
                    set valid 0
                    continue
                }
            }
            # This hard-PHY configuration has no hold side of the turnaround
            # calculation. The generated summary explicitly represents it as --.
            if {$category eq "Bus Turnaround Time" && $type eq "hold" && $margin eq "--"} {
                row ddr_microtiming "${category}_${type}" ABSENT "" 0 "vendor analytic side not applicable" $vendor
                continue
            }
            set margin [numeric $margin "DDR $label $type margin"]
            set status [expr {$margin >= 0.0 ? "PASS" : "FAIL"}]
            if {$status eq "FAIL"} { incr failures; set valid 0 }
            row ddr_microtiming "${category}_${type}" $status $margin 0 "four fitted DQS groups; current corner" $vendor
        }
    }
    dict for {category count} $required {
        if {$count != 1} {
            fail ddr_microtiming $category "Expected one vendor analytic summary row, found $count"
            set valid 0
        }
    }
    # The vendor CSV is a generated report, not a source-tree deliverable.
    set csv [file join [pwd] hps_sdram_p0_summary.csv]
    if {[file isfile $csv]} {
        file copy -force $csv [file join $report_dir [format {corner_%03d_ddr_summary.csv} $index]]
        file delete $csv
    }
    return $valid
}

proc ::trecap_fitted_timing::classify_no_clock {nodes ddr_valid} {
    variable failures
    # Exact hierarchy and counts are the reviewed Quartus 20.1 Cyclone V HPS
    # model boundary. A changed model or any unrecognized fabric node fails.
    set hps {platform_designer_wrapper:u_platform_designer_wrapper|system:u_platform_designer_system|system_hps_0:hps_0|}
    set fpga ${hps}system_hps_0_fpga_interfaces:fpga_interfaces|
    set border ${hps}system_hps_0_hps_io:hps_io|system_hps_0_hps_io_border:border|
    set expected [dict create f2sdram 623 clocks_resets 618 hps2fpga_light_weight 617 \
        sdio_inst 743 usb1_inst 645 qspi_inst 635 spim1_inst 621 uart0_inst 617 \
        i2c0_inst 617 i2c1_inst 617 gpio_inst 617 emac_border 16 dedicated_hps_ports 3 \
        ddr_pll_anchors 2 ddr_postamble 4]
    set exact [dict create]
    foreach port {HPS_USB_CLKOUT HPS_I2C1_SCLK HPS_I2C2_SCLK} { dict set exact $port dedicated_hps_ports }
    foreach leaf {
        emac1_inst~O_EMAC_CLK_TX emac1_inst~O_EMAC_PHY_TX_OE intermediate[0] intermediate[1]
        emac1_inst~O_EMAC_GMII_MDC emac1_inst emac1_inst~O_EMAC_PHY_TXD1
        emac1_inst~O_EMAC_PHY_TXD2 emac1_inst~O_EMAC_PHY_TXD3 emac1_inst~EMAC_CLK_RX[0]
        emac1_inst~EMAC_PHY_RXDV[0] emac1_inst~EMAC_GMII_MDO_I[0]
        emac1_inst~EMAC_PHY_RXD[0] emac1_inst~EMAC_PHY_RXD[1]
        emac1_inst~EMAC_PHY_RXD[2] emac1_inst~EMAC_PHY_RXD[3]
    } { dict set exact ${border}${leaf} emac_border }
    set pll ${border}hps_sdram:hps_sdram_inst|hps_sdram_pll:pll|
    foreach leaf {afi_clk pll_write_clk} { dict set exact ${pll}${leaf} ddr_pll_anchors }
    foreach group {0 1 2 3} {
        set leaf [format {hps_sdram:hps_sdram_inst|hps_sdram_p0:p0|hps_sdram_p0_acv_hard_memphy:umemphy|hps_sdram_p0_acv_hard_io_pads:uio_pads|hps_sdram_p0_altdqdqs:dq_ddio[%d].ubidir_dq_dqs|altdq_dqs2_acv_connect_to_hard_phy_cyclonev:altdq_dqs2_inst|dqs_delay_chain~POS_POSTAMBLE_DFF} $group]
        dict set exact ${border}${leaf} ddr_postamble
    }
    set seen [dict create]
    set unclassified 0
    foreach node $nodes {
        set group ""
        if {[dict exists $exact $node]} {
            set group [dict get $exact $node]
        } elseif {[string first $fpga $node] == 0 &&
                  [regexp {^(f2sdram|clocks_resets|hps2fpga_light_weight)~FF_[0-9]+$} [string range $node [string length $fpga] end] ignored group]} {
            # Dedicated HPS interface primitives expose model pseudo-registers.
        } elseif {[string first $border $node] == 0 &&
                  [regexp {^(sdio_inst|usb1_inst|qspi_inst|spim1_inst|uart0_inst|i2c0_inst|i2c1_inst|gpio_inst)~FF_[0-9]+$} [string range $node [string length $border] end] ignored group]} {
            # Dedicated HPS hard IO primitives; no FPGA peripheral is included.
        } else {
            incr unclassified
            row clock_coverage unclassified_no_clock FAIL "" "" $node ""
            continue
        }
        dict incr seen $group
    }
    set pll_valid 1
    foreach leaf {afi_clk_write_clk pll_write_clk_dq_write_clk} {
        set clock_name ${pll}${leaf}
        set clocks [get_clocks -nowarn $clock_name]
        if {[get_collection_size $clocks] != 1} {
            fail clock_coverage ddr_pll_clock "Missing unique vendor DDR clock: $clock_name"
            set pll_valid 0
            continue
        }
        foreach_in_collection clock $clocks {
            set period [numeric [get_clock_info $clock -period] "Vendor DDR clock period"]
            if {abs($period - 2.5) > 0.001} {
                fail clock_coverage ddr_pll_clock "Vendor DDR clock is not 2.5 ns: $clock_name = $period"
                set pll_valid 0
            }
        }
    }
    dict for {group count} $expected {
        set actual 0
        if {[dict exists $seen $group]} { set actual [dict get $seen $group] }
        set valid [expr {$actual == $count}]
        if {$group eq "ddr_postamble" && !$ddr_valid} { set valid 0 }
        if {$group eq "ddr_pll_anchors" && !$pll_valid} { set valid 0 }
        set status [expr {$valid ? "HARD_IP_MODEL_EXCLUDED" : "FAIL"}]
        if {!$valid} { incr failures }
        row clock_coverage $group $status "" "" "actual=$actual; expected=$count" \
            "postamble requires current-corner vendor margins; PLL anchors require actual vendor clocks"
    }
    if {$unclassified} { incr failures }
    row clock_coverage unclassified_no_clock [expr {$unclassified ? "FAIL" : "PASS"}] "" "" \
        "fabric_or_unrecognized_count=$unclassified" "No blanket HPS or register wildcard waiver"
}

proc ::trecap_fitted_timing::check_clock_coverage {index ddr_valid} {
    variable report_dir
    variable failures
    set panel_name "T-RECAP Clock Coverage $index"
    # TCL_OK only means the command ran. Preserve the raw problem count and
    # every detail row before applying the reviewed hard-IP model boundary.
    check_timing -include {no_clock generated_clock} -panel_name $panel_name \
        -file [file join $report_dir [format {corner_%03d_clock_coverage.rpt} $index]]
    set counts [dict create]
    set nodes [dict create]
    foreach panel [get_report_panel_names] {
        if {[string first $panel_name $panel] < 0} { continue }
        set id [get_report_panel_id $panel]
        if {[catch {set rows [get_number_of_rows -id $id]}]} { continue }
        for {set row_index 0} {$row_index < $rows} {incr row_index} {
            set cells [get_report_panel_row -id $id -row $row_index]
            set key [string trim [lindex $cells 0]]
            set detail [string trim [lindex $cells 1]]
            if {[string match {*||No Clock} $panel] && $key ne "Port or Register"} {
                if {$detail ni {{No clock feeds this register's clock port.} {Node was determined to feed a clock port but was found without an associated clock assignment.}}} {
                    error "Unrecognized no_clock detail: $cells"
                }
                if {[dict exists $nodes $key]} { error "Duplicate no_clock detail: $key" }
                dict set nodes $key 1
            }
            if {$key ni {no_clock generated_clock}} { continue }
            if {![string is integer -strict $detail] || $detail < 0} { error "Invalid clock-coverage count: $cells" }
            if {[dict exists $counts $key] && [dict get $counts $key] != $detail} { error "Conflicting clock-coverage counts: $key" }
            dict set counts $key $detail
        }
    }
    foreach key {no_clock generated_clock} {
        if {![dict exists $counts $key]} { error "Missing explicit $key problem count" }
    }
    set count [dict get $counts no_clock]
    row clock_coverage no_clock_raw RAW "" "" "problem_count=$count" $panel_name
    if {$count != [dict size $nodes]} { error "Raw no_clock count $count differs from [dict size $nodes] parsed unique detail nodes" }
    classify_no_clock [dict keys $nodes] $ddr_valid
    set generated [dict get $counts generated_clock]
    if {$generated} { incr failures }
    row clock_coverage generated_clock [expr {$generated ? "FAIL" : "PASS"}] "" "" "problem_count=$generated" $panel_name
}

proc ::trecap_fitted_timing::check_board_clocks {} {
    # TimeQuest reports periods to picosecond precision. This is query precision,
    # distinct from the allowed PLL synthesis quantization and board oscillator error.
    set query_precision_ns 0.001
    foreach {name expected} {CLOCK_50 20.0 codec_bclk 325.5208333333333} {
        set clocks [get_clocks -nowarn $name]
        if {[get_collection_size $clocks] != 1} { error "Expected exactly one $name clock" }
        foreach_in_collection clock $clocks {
            set period [numeric [get_clock_info $clock -period] "$name period"]
            set tolerance [expr {$name eq "CLOCK_50" ? 0.000001 : $query_precision_ns}]
            if {abs($period - $expected) > $tolerance} {
                error "$name period must be $expected ns within $tolerance ns, found $period"
            }
            row clock $name PASS $period $expected "query_precision_ns=$tolerance" ""
        }
    }
    # This output-counter hierarchy is observed in the native 20.1 generated
    # clocks; the VCO clock is deliberately excluded from the MCLK requirement.
    set outputs [get_clocks -nowarn {*u_audio_pll_wrapper*|*PLL_OUTPUT_COUNTER|divclk}]
    if {[get_collection_size $outputs] != 1} {
        error "Expected exactly one derived audio PLL output-counter clock"
    }
    # Engineering allocation in config/boards/physical_timing.json. It accepts
    # PLL synthesis quantization only; oscillator and board errors are separate.
    set nominal_hz 12288000.0
    set mclk_compile_tolerance_ppm 100.0
    foreach_in_collection clock $outputs {
        set name [get_clock_info $clock -name]
        set master [get_clock_info $clock -master_clock]
        if {$master eq "" || ![get_collection_size [get_clocks -nowarn $master]]} {
            error "Audio PLL output clock has no valid derived master: $name"
        }
        set period [numeric [get_clock_info $clock -period] "Audio MCLK period"]
        if {$period <= 0.0} { error "Audio MCLK period is not positive" }
        set nominal_period [expr {1.0e9 / $nominal_hz}]
        set fraction [expr {$mclk_compile_tolerance_ppm / 1.0e6}]
        set minimum [expr {$nominal_period / (1.0 + $fraction) - $query_precision_ns}]
        set maximum [expr {$nominal_period / (1.0 - $fraction) + $query_precision_ns}]
        if {$period < $minimum || $period > $maximum} {
            error "Audio MCLK period $period ns exceeds 100 ppm PLL allocation plus 1 ps query precision"
        }
        set frequency [expr {1.0e9 / $period}]
        set ppm [expr {($frequency / $nominal_hz - 1.0) * 1.0e6}]
        row clock audio_mclk PASS $period $nominal_period \
            "frequency_hz=$frequency; deviation_ppm=$ppm; compile_tolerance_ppm=100; query_precision_ns=0.001" $name
    }
}

proc ::trecap_fitted_timing::check_skew_reports {index lineout_allowed} {
    variable report_dir
    variable failures
    set skew_file [file join $report_dir [format {corner_%03d_max_skew.rpt} $index]]
    # 20.1 returns {number_of_paths worst_slack}; there is no -from/-to filter.
    # The full report covers every set_max_skew constraint, including the
    # required RX crossings and any retained TX/payload constraints.
    set result [report_max_skew -npaths 1 -detail full_path -file $skew_file]
    if {[llength $result] != 2} { error "Unexpected report_max_skew result: $result" }
    lassign $result count slack
    if {![string is integer -strict $count] || $count <= 0} {
        fail skew aggregate "No max-skew paths were analyzed"
        return
    }
    set slack [numeric $slack "Worst max-skew slack"]
    set status [expr {$slack >= 0.0 ? "PASS" : "FAIL"}]
    if {$status eq "FAIL"} { incr failures }
    row skew aggregate $status $slack 0 "analyzed_paths=$count" $skew_file
    set channel [open $skew_file r]
    set text [read $channel]
    close $channel
    foreach fifo {u_audio_rx_fifo u_audio_tx_fifo} {
        set retained [get_collection_size [regs "*${fifo}*"]]
        set required [expr {$fifo eq "u_audio_rx_fifo" || $lineout_allowed || $retained > 0}]
        if {!$required} { continue }
        foreach {direction source destination} {
            write wr_gray_q wr_gray_sync_rd_q
            read rd_gray_q rd_gray_sync_wr_q
        } {
            set from [regs "*${fifo}*|${source}*"]
            set to [regs "*${fifo}*|${destination}*"]
            if {![get_collection_size $from] || ![get_collection_size $to]} {
                fail skew ${fifo}_${direction} "Required Gray-pointer endpoints are absent"
                continue
            }
            # Detailed report coverage and the separately required connecting
            # get_path results prevent an unrelated skew group from satisfying RX.
            set source_pattern [format {%s[^\r\n]*\|%s} $fifo $source]
            set destination_pattern [format {%s[^\r\n]*\|%s} $fifo $destination]
            if {![regexp $source_pattern $text] || ![regexp $destination_pattern $text]} {
                fail skew ${fifo}_${direction} "Required Gray-pointer group absent from detailed skew report"
            } else {
                row skew ${fifo}_${direction} COVERED "" 10 "source_count=[get_collection_size $from]" "destination_count=[get_collection_size $to]"
            }
        }
    }
    # This API documents a report, not an aggregate pass/fail count. Retain it;
    # independent get_path limits enforce the clock-free 20 ns route maximum.
    report_net_delay -nworst 1 \
        -file [file join $report_dir [format {corner_%03d_net_delay.rpt} $index]]
}

proc ::trecap_fitted_timing::check_adc_return_route {index} {
    variable failures
    variable report_dir
    set from [get_ports -nowarn ADC_DOUT]
    set to [regs {*adc_dout_sync_q[0]}]
    if {[get_collection_size $from] != 1 || [get_collection_size $to] != 1} {
        fail route ADC_DOUT_input "Expected one ADC port and exactly one first-stage synchronizer"
        return
    }
    # Unlike a clock-relative set_min_delay, these queries contain no launch or
    # latch clock contribution. The hold-only first-stage exception in SDC has
    # no effect on get_path/report_path, so both physical bounds remain checked.
    foreach kind {maximum minimum} {
        set options [list -npaths 1 -from $from -to $to]
        set label ADC_DOUT_input
        set bound 10.0
        if {$kind eq "minimum"} {
            lappend options -min_path
            set label ADC_DOUT_input_min
            set bound 0.0
        }
        set paths [get_path {*}$options]
        if {[get_collection_size $paths] != 1} {
            fail route $label "Missing unique fitted $kind data path"
            continue
        }
        foreach_in_collection path $paths {
            set delay [numeric [get_path_info $path -arrival_time] "ADC $kind data delay"]
            set valid [expr {$kind eq "minimum" ? $delay >= $bound : $delay <= $bound}]
            if {!$valid} { incr failures }
            row route $label [expr {$valid ? "PASS" : "FAIL"}] $delay $bound \
                [node_name $path -from] [node_name $path -to]
        }
        report_path {*}$options -show_routing \
            -file [file join $report_dir [format {corner_%03d_ADC_DOUT_input_%s.rpt} $index $kind]]
    }
}

proc ::trecap_fitted_timing::check_output_data_routes {index} {
    variable failures
    variable report_dir
    foreach {port bound} {ADC_SCLK 5.0 ADC_CS_N 5.0 ADC_DIN 5.0 FPGA_I2C_SCLK 20.0 FPGA_I2C_SDAT 20.0} {
        set target [get_ports -nowarn $port]
        if {[get_collection_size $target] != 1} {
            fail route ${port}_output "Missing exact port or its source-owned SDC data-route registration"
            continue
        }
        if {![info exists ::trecap_output_data_max_ns($port)] || $::trecap_output_data_max_ns($port) != $bound} {
            fail route ${port}_output "SDC and fitted-gate data bounds disagree"
            continue
        }
        set from [get_fanins $target]
        if {![get_collection_size $from]} {fail route ${port}_output "No register fan-in"; continue}
        set sources_valid 1
        foreach_in_collection source $from {
            if {[get_node_info $source -type] ne "reg"} {
                fail route ${port}_output "Non-register source: [get_node_info $source -name]"
                set sources_valid 0
            }
        }
        if {!$sources_valid} {continue}
        row output_data_contract $port REQUIRED "" $bound \
            "register_sources=[get_collection_size $from]" "Physical propagation; no external synchronous capture clock"
        foreach kind {maximum minimum} {
            set options [list -npaths 1 -to $target]
            set label ${port}_output
            set limit $bound
            if {$kind eq "minimum"} {
                lappend options -min_path
                set label ${port}_output_min
                set limit 0.0
            }
            # Query every data source of this exact port, not only one nominal
            # driver. This includes ownership gating and open-drain control.
            set paths [get_path {*}$options]
            if {[get_collection_size $paths] != 1} {fail route $label "Missing unique $kind data path"; continue}
            foreach_in_collection path $paths {
                set delay [numeric [get_path_info $path -arrival_time] "$port $kind data delay"]
                set valid [expr {$kind eq "minimum" ? $delay >= 0.0 : $delay <= $limit}]
                if {!$valid} {incr failures}
                row route $label [expr {$valid ? "PASS" : "FAIL"}] $delay $limit \
                    [node_name $path -from] [node_name $path -to]
            }
            report_path {*}$options -show_routing \
                -file [file join $report_dir [format {corner_%03d_%s_%s.rpt} $index $port $kind]]
        }
    }
}

proc ::trecap_fitted_timing::check_physical_routes {lineout_allowed index} {
    # RX survives the board composition even when replay is selected. TX may
    # disappear when LINE-OUT is disallowed by the selected synthesis profile.
    foreach fifo {u_audio_rx_fifo u_audio_tx_fifo} {
        set source_present [get_collection_size [regs "*${fifo}*"]]
        set required [expr {$fifo eq "u_audio_rx_fifo" || $lineout_allowed || $source_present > 0}]
        foreach {direction source destination} {
            write wr_gray_q wr_gray_sync_rd_q
            read rd_gray_q rd_gray_sync_wr_q
        } {
            check_route ${fifo}_${direction}_gray \
                [regs "*${fifo}*|${source}*"] [regs "*${fifo}*|${destination}*"] 20.0 $required
        }
    }
    check_route rx_payload [regs {*u_audio_rx_fifo*|mem*}] \
        [regs {*u_audio_codec_wrapper*|audio_*_o*}] 20.0 1
    set tx_present [get_collection_size [regs {*u_audio_tx_fifo*}]]
    foreach side {left right} {
        set source [regs {*u_audio_tx_fifo*|mem*}]
        set destination [regs "*u_audio_codec_wrapper*|bclk_lineout_${side}_q*"]
        if {!$lineout_allowed && !$tx_present} {
            # Constant destination registers can survive pruning of the FIFO;
            # absence is permitted only when the included profile disables
            # LINE-OUT and the entire source FIFO is absent.
            row route tx_${side}_payload ABSENT_OPTIONAL "" 20 "TX FIFO removed by profile" ""
        } else {
            check_route tx_${side}_payload $source $destination 20.0 1
        }
    }
    check_output_data_routes $index
    check_adc_return_route $index

    check_route FPGA_I2C_SDAT_input [get_ports -nowarn FPGA_I2C_SDAT] \
        [regs {*sda_sync_q[0]}] 20.0 1
}

proc ::trecap_fitted_timing::run {} {
    variable report
    variable report_dir
    variable failures
    variable corner
    if {[llength $::quartus(args)] != 3} {
        error "Usage: quartus_sta -t check_fitted_timing.tcl <project> <revision> <report-directory>"
    }
    lassign $::quartus(args) project revision report_dir
    set report_dir [file normalize $report_dir]
    file mkdir $report_dir
    set report [open [file join $report_dir fitted_timing.tsv] w]
    fconfigure $report -translation lf -encoding utf-8
    puts $report "corner\tcategory\tcheck\tstatus\tvalue_ns\tbound_ns\tfrom\tto"
    set result [catch {
        foreach variable {TRECAP_PROFILE_QSF TRECAP_HPS_DDR_QSF} {
            if {![info exists ::env($variable)] || ![file isfile $::env($variable)]} {
                error "Missing fitted-build include selected by $variable"
            }
        }
        if {[is_project_open]} { error "Timing gate must start without an open project" }
        project_open $project -revision $revision
        set lineout_allowed [get_parameter -name AUDIO_LINEOUT_ALLOWED]
        if {$lineout_allowed ni {0 1}} {
            error "Included profile must set AUDIO_LINEOUT_ALLOWED to 0 or 1, found '$lineout_allowed'"
        }
        load_report
        # Default is the fitted netlist; never fall back to -post_map or zero IC delay.
        create_timing_netlist
        read_sdc
        update_timing_netlist
        check_board_clocks
        set fabric [get_clocks -nowarn CLOCK_50]
        set corners [get_available_operating_conditions -all]
        if {![get_collection_size $corners]} { error "No available fitted operating conditions" }
        set index 0
        foreach_in_collection operating_condition $corners {
            incr index
            set corner [get_operating_conditions_info $operating_condition -display_name]
            post_message -type info "T-RECAP fitted timing corner: $corner"
            set_operating_conditions $operating_condition
            update_timing_netlist
            foreach type {setup hold recovery removal} { check_slack $type $index }
            foreach type {setup hold} { check_slack $type $index $fabric }
            set ddr_valid [check_ddr_microtiming $index]
            check_clock_coverage $index $ddr_valid
            check_physical_routes $lineout_allowed $index
            check_skew_reports $index $lineout_allowed
        }
        set corner all
        if {$failures} { error "$failures fitted timing or physical-route checks failed" }
        row gate completed PASS "" "" "$index operating conditions" ""
    } message options]
    if {$result} { row gate completed FAIL "" "" $message "" }
    # Closing the project must still happen if timing-netlist cleanup fails.
    catch {if {[timing_netlist_exist]} { delete_timing_netlist }}
    if {[is_project_open]} { project_close -dont_export_assignments }
    close $report
    set report ""
    if {$result} { return -options $options $message }
}

if {[catch {::trecap_fitted_timing::run} message]} {
    post_message -type error "T-RECAP fitted timing gate failed: $message"
    qexit -error
}

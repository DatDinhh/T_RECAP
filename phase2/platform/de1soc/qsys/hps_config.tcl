# SPDX-License-Identifier: MIT
# T-RECAP Phase 2 DE1-SoC HPS and Platform Designer configuration.
# File class: [1] hand-written platform source.
# Layer: platform/de1soc/qsys/
# Owner: T-RECAP Phase 2 implementation.
#
# This file centralizes the HPS bridge, CSR-window, DDR-ring, and direct-link
# Ethernet defaults used by platform_designer.tcl and later HPS runtime config
# generation.  It is not generated output and it does not define CSR offsets,
# packet layouts, FFT/WOLA arithmetic, or signal-processing behavior.
#
# Address-space warning:
#   csr_base_hps_phys   = HPS/Linux physical address for the CSR window.
#   ring_base_hps_phys  = HPS/Linux physical DDR address for the telemetry ring.
#   ring_base_fpga      = FPGA-visible bus address written to CSR RING_BASE_*.
#   mmap() virtual pointers are process-local and shall never be written to FPGA CSRs.

namespace eval ::trecap_hps_config {
    variable cfg
    variable hps_parameter_overrides
    variable hps_parameter_snapshot
    variable hps_parameter_map
    variable hps_parameter_mode
    variable preset_metadata
    variable source_file [info script]

    # Keep this braced list strictly key/value-only: words beginning with '#'
    # are list data here, not Tcl comments. Bridge rationale belongs outside it.
    # The raw Cyclone-V F2SDRAM Avalon agent has no write-response channel.
    # Keep the exported single-beat bridge response-free; Platform Designer
    # adapts its one-bit burstcount to the raw agent's 11-bit burstcount.
    array set cfg {
        project_name                       T_RECAP_Phase2
        board_name                         de1soc
        device_family                      {Cyclone V}
        device_part                        5CSEMA5F31C6

        platform_contract_revision         step6_typed_bridges_source_v1
        platform_contract_status           source_implemented_pending_quartus_normalization_generation_compile
        address_map_contract_revision      step4_frozen_v1
        address_map_contract_stage         step4_address_map_source_frozen
        address_map_contract_status        source_frozen_pending_sopcinfo_linux_reservation_and_board_revision_signoff
        board_revision_profile             rev_h
        physical_board_revision_status     unverified_requires_board_label_confirmation
        quartus_release                    20.1

        qsys_system_name                   system
        qsys_api_version                   16.0
        qsys_blueprint_rel                 platform/de1soc/qsys/system_blueprint.xml
        qsys_file_rel                      platform/de1soc/qsys/system.qsys
        qsys_generated_dir_rel             platform/de1soc/qsys/system
        sopcinfo_file_rel                  platform/de1soc/qsys/system.sopcinfo
        qip_file_rel                       platform/de1soc/qsys/system/synthesis/system.qip
        generated_notes_rel                platform/de1soc/generated_notes/generated_files_readme.md
        address_map_md_rel                 platform/de1soc/address_map/address_map.md
        hps_bridge_regions_rel             platform/de1soc/address_map/hps_bridge_regions.json
        sopcinfo_location_md_rel            platform/de1soc/address_map/sopcinfo_location.md
        hps_runtime_config_rel             sw/hps/config/trecap_hps_config.json
        hps_preset_tsv_rel                 platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps.tsv
        hps_preset_manifest_rel            platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps_manifest.json
        hps_preset_profile_id              terasic_de1soc_revh_qp20_1_trecap_f2sdram64
        hps_preset_parameter_count         520
        hps_preset_applied_parameter_count 476
        hps_preset_readback_parameter_count 44
        hps_preset_base_sha256             57a6d9d4ab09a0b6f88d26908d2f2def38e46a37e2b0f94466411fcabc73be26
        hps_preset_effective_sha256        bf0dc533f1a141c2a3d91058501b19b0a6ef5b479619bb4829fe94bea60e0888
        hps_preset_application_sha256      02c6f1fc1bec86f960d3a7740f38f65ec3931c74458bf338f20c9b9f22f45076

        clk_50_hz                          50000000
        fabric_clock_frequency_known       true
        fabric_reset_synchronous_edges     NONE
        fabric_clk_export                  clk_50
        fabric_clk_export_role             sink
        fabric_clk_internal                clk_0.clk
        hps_bridge_clock_sinks             {f2h_sdram0_clock h2f_axi_clock f2h_axi_clock h2f_lw_axi_clock}
        fabric_reset_export                reset_n
        fabric_reset_internal              clk_0.clk_in_reset
        fabric_reset_bridge_internal       clk_0.clk_reset
        fabric_reset_export_role           sink

        hps_instance                       hps_0
        hps_component_type                 altera_hps
        hps_component_version              20.1

        h2f_lw_master_export               trecap_csr_lw_master
        h2f_lw_master_export_role          master
        h2f_lw_master_internal             hps_0.h2f_lw_axi_master
        h2f_lw_master_export_internal      trecap_csr_bridge.m0
        f2h_sdram0_export                  trecap_f2h_sdram0
        f2h_sdram0_export_role             slave
        f2h_sdram0_internal                hps_0.f2h_sdram0_data
        f2h_sdram0_export_internal         trecap_f2h_sdram_bridge.s0
        hps_io_export                      hps_io
        hps_io_export_role                 end
        hps_memory_export                  memory
        hps_memory_export_role             end
        h2f_reset_export                   h2f_reset
        h2f_reset_export_direction         source
        export_hps_io                      1

        h2f_lw_base_hps_phys               0xff200000
        h2f_lw_span_bytes                  0x00200000
        csr_offset_in_lw                   0x00000000
        csr_base_hps_phys                  0xff200000
        csr_span_bytes                     0x00001000
        csr_data_width                     32
        h2f_lw_master_byte_addr_width       21
        csr_leaf_byte_addr_width            12

        csr_bridge_instance                trecap_csr_bridge
        csr_bridge_component_type          altera_avalon_mm_bridge
        csr_bridge_component_version       20.1
        csr_bridge_clock_interface         trecap_csr_bridge.clk
        csr_bridge_reset_interface         trecap_csr_bridge.reset
        csr_bridge_slave_interface         trecap_csr_bridge.s0
        csr_bridge_master_interface        trecap_csr_bridge.m0
        csr_bridge_upstream_interface      hps_0.h2f_lw_axi_master
        csr_bridge_connection_base_address 0x00000000
        csr_bridge_address_units           SYMBOLS
        csr_bridge_address_width           21
        csr_bridge_data_width              32
        csr_bridge_symbol_width            8
        csr_bridge_linewrap_bursts         0
        csr_bridge_max_burst_size          1
        csr_bridge_max_pending_responses   1
        csr_bridge_pipeline_command        0
        csr_bridge_pipeline_response       0
        csr_bridge_use_auto_address_width  0
        csr_bridge_use_response            1

        f2h_sdram_bridge_instance                trecap_f2h_sdram_bridge
        f2h_sdram_bridge_component_type          altera_avalon_mm_bridge
        f2h_sdram_bridge_component_version       20.1
        f2h_sdram_bridge_clock_interface         trecap_f2h_sdram_bridge.clk
        f2h_sdram_bridge_reset_interface         trecap_f2h_sdram_bridge.reset
        f2h_sdram_bridge_slave_interface         trecap_f2h_sdram_bridge.s0
        f2h_sdram_bridge_master_interface        trecap_f2h_sdram_bridge.m0
        f2h_sdram_bridge_downstream_interface    hps_0.f2h_sdram0_data
        f2h_sdram_bridge_connection_base_address 0x00000000
        f2h_sdram_bridge_address_units           SYMBOLS
        f2h_sdram_bridge_address_width           32
        f2h_sdram_bridge_data_width              64
        f2h_sdram_bridge_symbol_width            8
        f2h_sdram_bridge_linewrap_bursts         0
        f2h_sdram_bridge_max_burst_size          1
        f2h_sdram_bridge_max_pending_responses   1
        f2h_sdram_bridge_pipeline_command        1
        f2h_sdram_bridge_pipeline_response       1
        f2h_sdram_bridge_use_auto_address_width  0
        f2h_sdram_bridge_use_response            0

        ring_base_hps_phys                 0x3e000000
        ring_base_fpga                     0x3e000000
        ring_size_bytes                    0x02000000
        ring_guard_bytes                   64
        ddr_writer_data_width              64
        ddr_writer_byteenable_width        8
        ddr_writer_burstcount_width        1

        pc_direct_ip                       192.168.10.1
        hps_direct_ip                      192.168.10.2
        direct_link_netmask                255.255.255.0
        telemetry_dst_port                 5005
        command_listen_port                5006
        trusted_command_peer               192.168.10.1
        transport_version_major            1
        transport_version_minor            8

        memory_mapping_policy              reserved_ddr_or_dma_coherent
        hps_ring_cache_policy              non_cacheable_or_explicit_invalidate
        malformed_record_policy            disable_and_reset
    }

    # Populated from the provenance-locked TSV at the end of this file. Every
    # one of the 520 Quartus 20.1 altera_hps parameters is frozen; the Platform
    # Designer generator is not allowed to guess parameter names or silently
    # skip missing parameters.
    set hps_parameter_overrides {}
    set hps_parameter_snapshot {}
}


# qsys-script in some Intel FPGA/Quartus releases uses a restricted Tcl
# interpreter where "file normalize" is not implemented.  Keep path handling
# deterministic without depending on that subcommand.  The returned path may
# retain ".." components; Tcl file commands still resolve those correctly.
proc ::trecap_hps_config::normpath {path} {
    if {[string equal $path ""]} {
        return ""
    }
    if {[regexp {^[A-Za-z]:[\\/]} $path] || [regexp {^[/\\][/\\]} $path] || [string equal [string index $path 0] "/"]} {
        return [file join $path]
    }
    return [file join [pwd] $path]
}

proc ::trecap_hps_config::repo_root {{start_file ""}} {
    if {[string equal $start_file ""]} {
        set start_file [info script]
    }
    if {[string equal $start_file ""]} {
        set start_file [file join [pwd] platform de1soc qsys hps_config.tcl]
    }
    set qsys_dir [file dirname [normpath $start_file]]
    return [normpath [file join $qsys_dir .. .. ..]]
}

proc ::trecap_hps_config::get {key} {
    variable cfg
    if {![info exists cfg($key)]} {
        return -code error "unknown T-RECAP HPS config key: $key"
    }
    return $cfg($key)
}

proc ::trecap_hps_config::set_value {key value} {
    variable cfg
    set cfg($key) $value
}

proc ::trecap_hps_config::all_pairs {} {
    variable cfg
    set out {}
    foreach key [lsort [array names cfg]] {
        lappend out $key $cfg($key)
    }
    return $out
}

proc ::trecap_hps_config::hex_literal_to_small_int {hex_digits original_value} {
    # Compatibility note: qsys-script on some Intel FPGA/Quartus installs does
    # not implement the Tcl expr wide() math function and may use a restricted
    # 32-bit expression engine.  Only call expr on hex literals that are known
    # to fit in signed 31-bit positive range.  Larger addresses are formatted
    # by hex64 without converting through expr.
    set h [string trimleft $hex_digits 0]
    if {[string equal $h ""]} {
        return 0
    }
    set h [string tolower $h]
    set n [string length $h]
    if {$n > 8} {
        return -code error "integer literal is too large for portable Tcl arithmetic: $original_value"
    }
    if {$n == 8} {
        set first [string index $h 0]
        if {[lsearch -exact {8 9 a b c d e f} $first] >= 0} {
            return -code error "integer literal is too large for portable signed arithmetic: $original_value"
        }
    }
    if {[scan $h %x out] != 1} {
        return -code error "could not parse hex integer: $original_value"
    }
    return $out
}

proc ::trecap_hps_config::as_int {value} {
    set value [string trim $value]
    if {[regexp {^[0-9]+$} $value]} {
        return [expr {$value + 0}]
    }
    if {[regexp {^0[xX]([0-9a-fA-F]+)$} $value -> hex_digits]} {
        return [hex_literal_to_small_int $hex_digits $value]
    }
    return -code error "not an integer literal: $value"
}

proc ::trecap_hps_config::is_power_of_two {value} {
    set v [as_int $value]
    return [expr {$v > 0 && (($v & ($v - 1)) == 0)}]
}

proc ::trecap_hps_config::hex64 {value} {
    set value [string trim $value]
    if {[regexp {^0[xX]([0-9a-fA-F]+)$} $value -> hex_digits]} {
        set h [string trimleft [string tolower $hex_digits] 0]
        if {[string equal $h ""]} {
            set h 0
        }
        if {[string length $h] > 16} {
            return -code error "integer literal is wider than 64 bits: $value"
        }
        set padded $h
        while {[string length $padded] < 16} {
            set padded "0$padded"
        }
        return "0x$padded"
    }

    set v [as_int $value]
    return [format 0x%016x $v]
}

proc ::trecap_hps_config::json_escape {text} {
    return [string map [list "\\" "\\\\" "\"" "\\\"" "\n" "\\n" "\r" "\\r" "\t" "\\t"] $text]
}

proc ::trecap_hps_config::json_string {text} {
    return "\"[json_escape $text]\""
}

proc ::trecap_hps_config::abs_path {repo_root rel_or_abs} {
    if {[string equal [file pathtype $rel_or_abs] "absolute"]} {
        return [normpath $rel_or_abs]
    }
    return [normpath [file join $repo_root $rel_or_abs]]
}

proc ::trecap_hps_config::ensure_parent {path} {
    set dir [file dirname $path]
    if {![string equal $dir "."] && ![file isdirectory $dir]} {
        file mkdir $dir
    }
}

proc ::trecap_hps_config::load_hps_parameter_snapshot {} {
    variable source_file
    variable hps_parameter_overrides
    variable hps_parameter_snapshot
    variable hps_parameter_map
    variable hps_parameter_mode
    variable preset_metadata

    set root [repo_root $source_file]
    set path [abs_path $root [get hps_preset_tsv_rel]]
    if {![file exists $path]} {
        return -code error "frozen HPS preset is missing: [get hps_preset_tsv_rel]"
    }

    set fp [open $path r]
    set content [read $fp]
    close $fp

    set hps_parameter_overrides {}
    set hps_parameter_snapshot {}
    catch {unset hps_parameter_map}
    catch {unset hps_parameter_mode}
    catch {unset preset_metadata}

    set previous_name ""
    foreach raw_line [split $content "\n"] {
        set line [string trimright $raw_line "\r"]
        if {[string equal $line ""]} { continue }
        if {[string equal [string index $line 0] "#"]} {
            if {[regexp {^# ([A-Za-z0-9_]+)=(.*)$} $line -> key value]} {
                set preset_metadata($key) $value
            }
            continue
        }

        set tab_index [string first "\t" $line]
        set last_tab_index [string last "\t" $line]
        if {$tab_index < 1 || $last_tab_index <= $tab_index} {
            return -code error "invalid three-column frozen HPS preset row: $line"
        }
        set name [string range $line 0 [expr {$tab_index - 1}]]
        set value [string range $line [expr {$tab_index + 1}] [expr {$last_tab_index - 1}]]
        set application_mode [string range $line [expr {$last_tab_index + 1}] end]
        if {[lsearch -exact {set readback_only} $application_mode] < 0} {
            return -code error "invalid HPS parameter application mode for $name: $application_mode"
        }
        if {[info exists hps_parameter_map($name)]} {
            return -code error "duplicate parameter in frozen HPS preset: $name"
        }
        if {![string equal $previous_name ""] && [string compare $previous_name $name] >= 0} {
            return -code error "frozen HPS preset rows are not strictly sorted: $previous_name then $name"
        }
        set hps_parameter_map($name) $value
        set hps_parameter_mode($name) $application_mode
        lappend hps_parameter_snapshot $name $value
        if {[string equal $application_mode "set"]} {
            lappend hps_parameter_overrides [list $name $value]
        }
        set previous_name $name
    }

    set actual_count [array size hps_parameter_map]
    set expected_count [as_int [get hps_preset_parameter_count]]
    if {$actual_count != $expected_count} {
        return -code error "frozen HPS preset count mismatch: got $actual_count, expected $expected_count"
    }
    if {[llength $hps_parameter_overrides] != [as_int [get hps_preset_applied_parameter_count]]} {
        return -code error "frozen HPS preset applied-parameter count mismatch"
    }
    set readback_count 0
    foreach name [array names hps_parameter_mode] {
        if {[string equal $hps_parameter_mode($name) "readback_only"]} { incr readback_count }
    }
    if {$readback_count != [as_int [get hps_preset_readback_parameter_count]]} {
        return -code error "frozen HPS preset readback-only count mismatch"
    }
    foreach metadata_key {base_parameter_sha256 effective_parameter_sha256 parameter_count applied_parameter_count readback_only_parameter_count application_mode_sha256 upstream_qsys_sha256} {
        if {![info exists preset_metadata($metadata_key)]} {
            return -code error "frozen HPS preset metadata missing: $metadata_key"
        }
    }
    if {![string equal $preset_metadata(base_parameter_sha256) [get hps_preset_base_sha256]]} {
        return -code error "frozen HPS preset base hash metadata mismatch"
    }
    if {![string equal $preset_metadata(effective_parameter_sha256) [get hps_preset_effective_sha256]]} {
        return -code error "frozen HPS preset effective hash metadata mismatch"
    }
    if {![string equal $preset_metadata(parameter_count) [get hps_preset_parameter_count]]} {
        return -code error "frozen HPS preset parameter-count metadata mismatch"
    }
    if {![string equal $preset_metadata(applied_parameter_count) [get hps_preset_applied_parameter_count]]} {
        return -code error "frozen HPS preset applied-count metadata mismatch"
    }
    if {![string equal $preset_metadata(readback_only_parameter_count) [get hps_preset_readback_parameter_count]]} {
        return -code error "frozen HPS preset readback-count metadata mismatch"
    }
    if {![string equal $preset_metadata(application_mode_sha256) [get hps_preset_application_sha256]]} {
        return -code error "frozen HPS preset application-partition hash metadata mismatch"
    }
    return $actual_count
}

proc ::trecap_hps_config::hps_parameter_get {name} {
    variable hps_parameter_map
    if {![info exists hps_parameter_map($name)]} {
        return -code error "unknown frozen HPS parameter: $name"
    }
    return $hps_parameter_map($name)
}

proc ::trecap_hps_config::hps_parameter_pairs {} {
    variable hps_parameter_overrides
    return $hps_parameter_overrides
}

proc ::trecap_hps_config::hps_snapshot_pairs {} {
    variable hps_parameter_snapshot
    set pairs {}
    foreach {name value} $hps_parameter_snapshot {
        lappend pairs [list $name $value]
    }
    return $pairs
}

proc ::trecap_hps_config::hps_readback_pairs {} {
    variable hps_parameter_snapshot
    variable hps_parameter_mode
    set pairs {}
    foreach {name value} $hps_parameter_snapshot {
        if {[string equal $hps_parameter_mode($name) "readback_only"]} {
            lappend pairs [list $name $value]
        }
    }
    return $pairs
}

proc ::trecap_hps_config::validate {} {
    set errors {}

    if {![string equal [get platform_contract_status] "source_implemented_pending_quartus_normalization_generation_compile"]} {
        lappend errors "platform_contract_status must report the truthful Step 6 source-only state"
    }
    if {![string equal [get address_map_contract_stage] "step4_address_map_source_frozen"]} {
        lappend errors "address_map_contract_stage is not the Step 4 frozen-source state"
    }
    if {![string equal [get address_map_contract_status] "source_frozen_pending_sopcinfo_linux_reservation_and_board_revision_signoff"]} {
        lappend errors "address_map_contract_status must keep hardware evidence explicitly pending"
    }
    if {![string equal [get board_revision_profile] "rev_h"]} {
        lappend errors "only the provenance-locked Rev-H board profile is supported by this snapshot"
    }
    if {![string equal [get physical_board_revision_status] "unverified_requires_board_label_confirmation"]} {
        lappend errors "physical board revision must remain explicitly unverified until its label is checked"
    }
    if {![string equal [get hps_component_version] "20.1"]} {
        lappend errors "altera_hps component version must be frozen to 20.1"
    }
    if {[as_int [get export_hps_io]] != 1} {
        lappend errors "HPS IO export must be enabled for the board pin-mux contract"
    }
    if {![string equal [get h2f_reset_export_direction] "source"]} {
        lappend errors "h2f_reset must use the Qsys Tcl reset-source role (serialized direction start)"
    }

    variable hps_parameter_map
    if {[array size hps_parameter_map] != [as_int [get hps_preset_parameter_count]]} {
        lappend errors "frozen HPS parameter snapshot is not loaded or has the wrong size"
    }
    variable hps_parameter_overrides
    if {[llength $hps_parameter_overrides] != [as_int [get hps_preset_applied_parameter_count]]} {
        lappend errors "frozen HPS applied-parameter inventory has the wrong size"
    }
    foreach {name expected} {
        EMAC1_Mode RGMII
        EMAC1_PinMuxing {HPS I/O Set 0}
        F2SDRAM_Type {Avalon-MM Bidirectional}
        F2SDRAM_Width 64
        HARD_EMIF true
        HHP_HPS true
        LWH2F_Enable true
        MPU_EVENTS_Enable false
        SDIO_Mode {4-bit Data}
        SDIO_PinMuxing {HPS I/O Set 0}
        UART0_Mode {No Flow Control}
        UART0_PinMuxing {HPS I/O Set 0}
        USB1_Mode SDR
        USB1_PinMuxing {HPS I/O Set 0}
    } {
        if {![info exists hps_parameter_map($name)] || ![string equal $hps_parameter_map($name) $expected]} {
            set actual "<missing>"
            if {[info exists hps_parameter_map($name)]} { set actual $hps_parameter_map($name) }
            lappend errors "frozen HPS parameter $name must be '$expected'; got '$actual'"
        }
    }
    if {[info exists hps_parameter_map(F2SDRAM_Width)] &&
        [as_int $hps_parameter_map(F2SDRAM_Width)] != [as_int [get ddr_writer_data_width]]} {
        lappend errors "F2SDRAM_Width must match ddr_writer_data_width"
    }

    set csr_span [as_int [get csr_span_bytes]]
    if {$csr_span < 0x100} {
        lappend errors "csr_span_bytes must cover the Revision G CSR map; got $csr_span"
    }
    if {($csr_span % 4) != 0} {
        lappend errors "csr_span_bytes must be 32-bit aligned; got $csr_span"
    }
    # Step 6 freezes the CSR bridge at offset zero. Compare the high physical
    # addresses textually in normalized 64-bit form so this validation remains
    # valid in restricted qsys-script Tcl builds with 32-bit expression math.
    if {[as_int [get csr_offset_in_lw]] != 0} {
        lappend errors "csr_offset_in_lw must remain zero for the frozen bridge connection"
    }
    if {![string equal [hex64 [get csr_base_hps_phys]] [hex64 [get h2f_lw_base_hps_phys]]]} {
        lappend errors "csr_base_hps_phys must equal h2f_lw_base_hps_phys for the zero-offset CSR bridge"
    }
    if {[as_int [get h2f_lw_span_bytes]] != 0x00200000} {
        lappend errors "Cyclone V lightweight HPS-to-FPGA aperture must be 2 MiB"
    }
    if {[as_int [get h2f_lw_master_byte_addr_width]] != 21} {
        lappend errors "the 2 MiB lightweight master must preserve all 21 byte-address bits"
    }
    if {[as_int [get csr_leaf_byte_addr_width]] != 12} {
        lappend errors "the 4 KiB CSR leaf must use 12 byte-offset bits"
    }
    if {([as_int [get csr_offset_in_lw]] + $csr_span) > [as_int [get h2f_lw_span_bytes]]} {
        lappend errors "the CSR subwindow does not fit inside the lightweight bridge aperture"
    }

    foreach {key expected} {
        csr_bridge_instance                trecap_csr_bridge
        csr_bridge_component_type          altera_avalon_mm_bridge
        csr_bridge_component_version       20.1
        csr_bridge_clock_interface         trecap_csr_bridge.clk
        csr_bridge_reset_interface         trecap_csr_bridge.reset
        csr_bridge_slave_interface         trecap_csr_bridge.s0
        csr_bridge_master_interface        trecap_csr_bridge.m0
        csr_bridge_upstream_interface      hps_0.h2f_lw_axi_master
        h2f_lw_master_internal             hps_0.h2f_lw_axi_master
        h2f_lw_master_export_internal      trecap_csr_bridge.m0
        csr_bridge_address_units           SYMBOLS
        f2h_sdram_bridge_instance          trecap_f2h_sdram_bridge
        f2h_sdram_bridge_component_type    altera_avalon_mm_bridge
        f2h_sdram_bridge_component_version 20.1
        f2h_sdram_bridge_clock_interface   trecap_f2h_sdram_bridge.clk
        f2h_sdram_bridge_reset_interface   trecap_f2h_sdram_bridge.reset
        f2h_sdram_bridge_slave_interface   trecap_f2h_sdram_bridge.s0
        f2h_sdram_bridge_master_interface  trecap_f2h_sdram_bridge.m0
        f2h_sdram_bridge_downstream_interface hps_0.f2h_sdram0_data
        f2h_sdram0_internal                hps_0.f2h_sdram0_data
        f2h_sdram0_export_internal         trecap_f2h_sdram_bridge.s0
        fabric_reset_bridge_internal       clk_0.clk_reset
        f2h_sdram_bridge_address_units     SYMBOLS
    } {
        if {![string equal [get $key] $expected]} {
            lappend errors "$key must be '$expected'; got '[get $key]'"
        }
    }
    if {[as_int [get csr_bridge_connection_base_address]] != [as_int [get csr_offset_in_lw]]} {
        lappend errors "the HPS-to-CSR-bridge connection must start at the frozen CSR offset"
    }
    if {[as_int [get csr_bridge_address_width]] != [as_int [get h2f_lw_master_byte_addr_width]]} {
        lappend errors "the CSR bridge must preserve all lightweight byte-address bits"
    }
    if {[as_int [get csr_bridge_data_width]] != [as_int [get csr_data_width]]} {
        lappend errors "the CSR bridge data width must match the 32-bit CSR contract"
    }
    if {[as_int [get csr_bridge_symbol_width]] != 8} {
        lappend errors "the CSR bridge symbol width must be 8 bits for byte addressing"
    }
    foreach key {
        csr_bridge_linewrap_bursts
        csr_bridge_pipeline_command
        csr_bridge_pipeline_response
        csr_bridge_use_auto_address_width
    } {
        if {[as_int [get $key]] != 0} {
            lappend errors "$key must be disabled for the frozen single-beat CSR path"
        }
    }
    foreach key {csr_bridge_max_burst_size csr_bridge_max_pending_responses csr_bridge_use_response} {
        if {[as_int [get $key]] != 1} {
            lappend errors "$key must be 1 for the frozen response-capable single-transaction CSR path"
        }
    }
    if {[as_int [get f2h_sdram_bridge_connection_base_address]] != 0} {
        lappend errors "the FPGA-to-HPS SDRAM bridge must connect to the HPS agent at base address zero"
    }
    if {[as_int [get f2h_sdram_bridge_address_width]] != 32} {
        lappend errors "the wrapper-facing FPGA-to-HPS SDRAM bridge must preserve a 32-bit byte address"
    }
    if {[as_int [get f2h_sdram_bridge_data_width]] != [as_int [get ddr_writer_data_width]]} {
        lappend errors "the FPGA-to-HPS SDRAM bridge width must match the 64-bit DDR writer"
    }
    if {[as_int [get f2h_sdram_bridge_symbol_width]] != 8} {
        lappend errors "the FPGA-to-HPS SDRAM bridge symbol width must be 8 bits for byte addressing"
    }
    foreach key {f2h_sdram_bridge_linewrap_bursts f2h_sdram_bridge_use_auto_address_width} {
        if {[as_int [get $key]] != 0} {
            lappend errors "$key must be disabled for the frozen byte-addressed DDR path"
        }
    }
    foreach key {
        f2h_sdram_bridge_max_burst_size
        f2h_sdram_bridge_max_pending_responses
        f2h_sdram_bridge_pipeline_command
        f2h_sdram_bridge_pipeline_response
    } {
        if {[as_int [get $key]] != 1} {
            lappend errors "$key must be 1 for the frozen pipelined single-transaction DDR path"
        }
    }
    if {[as_int [get f2h_sdram_bridge_use_response]] != 0} {
        lappend errors "f2h_sdram_bridge_use_response must be 0 because the raw HPS F2SDRAM agent has no write-response channel"
    }

    set ring_size [as_int [get ring_size_bytes]]
    if {$ring_size < 0x00100000} {
        lappend errors "ring_size_bytes must be at least 1 MiB; got $ring_size"
    }
    if {![is_power_of_two $ring_size]} {
        lappend errors "ring_size_bytes must be a power of two; got $ring_size"
    }
    if {($ring_size % 64) != 0} {
        lappend errors "ring_size_bytes must be a multiple of 64; got $ring_size"
    }

    foreach key {ring_base_hps_phys ring_base_fpga} {
        set v [as_int [get $key]]
        if {($v % 64) != 0} {
            lappend errors "$key must be 64-byte aligned; got [get $key]"
        }
    }
    if {[as_int [get ring_base_fpga]] != [as_int [get ring_base_hps_phys]]} {
        lappend errors "Step 4 freezes an identity HPS-physical to FPGA-visible ring mapping"
    }
    if {([as_int [get ring_base_hps_phys]] % $ring_size) != 0} {
        lappend errors "the Step 4 ring base must be naturally aligned to ring_size_bytes"
    }

    set major [as_int [get transport_version_major]]
    set minor [as_int [get transport_version_minor]]
    if {$major != 1 || $minor != 8} {
        lappend errors "transport version must be 1.8; got $major.$minor"
    }

    foreach key {telemetry_dst_port command_listen_port} {
        set port [as_int [get $key]]
        if {$port < 1 || $port > 65535} {
            lappend errors "$key must be in 1..65535; got $port"
        }
    }

    if {[llength $errors] != 0} {
        return -code error "T-RECAP HPS config validation failed:\n  - [join $errors {\n  - }]"
    }
    return 1
}

proc ::trecap_hps_config::emit_summary {{channel stdout}} {
    validate
    puts $channel "T-RECAP DE1-SoC HPS/Platform Designer config:"
    puts $channel "  contract               : [get platform_contract_revision] / [get platform_contract_status]"
    puts $channel "  address map            : [get address_map_contract_revision] / [get address_map_contract_status]"
    puts $channel "  board profile          : [get board_revision_profile] ([get physical_board_revision_status])"
    puts $channel "  Quartus / HPS component: [get quartus_release] / [get hps_component_version]"
    puts $channel "  HPS preset             : [get hps_preset_profile_id]"
    puts $channel "  HPS preset parameters  : [get hps_preset_parameter_count] total / [get hps_preset_applied_parameter_count] applied"
    puts $channel "  HPS preset hash        : [get hps_preset_effective_sha256]"
    puts $channel "  qsys_system_name        : [get qsys_system_name]"
    puts $channel "  device                  : [get device_family] / [get device_part]"
    puts $channel "  fabric clock            : [get clk_50_hz] Hz"
    puts $channel "  H2F lightweight aperture: [hex64 [get h2f_lw_base_hps_phys]] / [as_int [get h2f_lw_span_bytes]] bytes"
    puts $channel "  H2F/CSR address widths   : [get h2f_lw_master_byte_addr_width] master / [get csr_leaf_byte_addr_width] leaf bits"
    puts $channel "  CSR bridge              : [get csr_bridge_instance] ([get csr_bridge_component_type] [get csr_bridge_component_version])"
    puts $channel "  CSR bridge path         : [get csr_bridge_upstream_interface] -> [get csr_bridge_slave_interface] -> [get csr_bridge_master_interface]"
    puts $channel "  SDRAM bridge path       : [get f2h_sdram_bridge_slave_interface] -> [get f2h_sdram_bridge_master_interface] -> [get f2h_sdram_bridge_downstream_interface]"
    puts $channel "  CSR HPS phys base       : [hex64 [get csr_base_hps_phys]]"
    puts $channel "  CSR span                : [as_int [get csr_span_bytes]] bytes"
    puts $channel "  ring HPS phys base      : [hex64 [get ring_base_hps_phys]]"
    puts $channel "  ring FPGA visible base  : [hex64 [get ring_base_fpga]]"
    puts $channel "  ring size               : [as_int [get ring_size_bytes]] bytes"
    puts $channel "  direct PC/HPS IP        : [get pc_direct_ip] / [get hps_direct_ip]"
    puts $channel "  UDP telemetry/command   : [get telemetry_dst_port] / [get command_listen_port]"
    puts $channel "  transport version       : [get transport_version_major].[get transport_version_minor]"
}

proc ::trecap_hps_config::write_hps_runtime_config {repo_root {path ""}} {
    validate
    if {[string equal $path ""]} {
        set path [get hps_runtime_config_rel]
    }
    set out [abs_path $repo_root $path]
    if {![file exists $out]} {
        return -code error "reviewed HPS runtime config is missing: $path"
    }
    # This is a reviewed [1] source file. Parity is enforced by the mandatory
    # Python checker; emit-configs validates and preserves it, never rewrites it.
    return $out
}

proc ::trecap_hps_config::write_bridge_regions {repo_root {path ""}} {
    validate
    if {[string equal $path ""]} {
        set path [get hps_bridge_regions_rel]
    }
    set out [abs_path $repo_root $path]
    if {![file exists $out]} {
        return -code error "reviewed HPS bridge-region source is missing: $path"
    }
    # This is a reviewed [1] source file. Parity is enforced by the mandatory
    # Python checker; emit-configs validates and preserves it, never rewrites it.
    return $out
}

::trecap_hps_config::load_hps_parameter_snapshot

if {[info exists argv0] && ![string equal [info script] ""] && [string equal [::trecap_hps_config::normpath $argv0] [::trecap_hps_config::normpath [info script]]]} {
    ::trecap_hps_config::emit_summary
}

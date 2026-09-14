# SPDX-License-Identifier: MIT
# T-RECAP Phase 2 DE1-SoC baseline TimeQuest constraints.
# File class: [1] hand-written timing constraint source.
# Layer: constraints/de1soc/
# Owner: T-RECAP Phase 2 implementation.
#
# Purpose:
#   Provide the fabric-clock timing baseline for the pin-agnostic logical top
#   and the implemented board-facing DE1-SoC source/core/Platform Designer hierarchy.
#
# Scope:
#   - Creates a 50 MHz baseline fabric clock for the logical clk port and/or the
#     CLOCK_50 board-wrapper port when present.
#   - Cuts asynchronous reset assertion paths and documented single-bit synchronizer first-stage
#     CDC endpoints.
#   - Gives zero-delay internal-interface constraints to current abstract virtual pins so
#     early smoke builds expose unconstrained-interface mistakes without inventing board timing.
#
# Non-scope:
#   - This is not a final Platform Designer timing closure file.
#   - The Step-16 audio PLL clock is derived from the instantiated PLL; codec-master BCLK/LRCK
#     external I/O timing is owned by clocks.sdc; generated HPS clocks come from its QIP.
#   - Board package pin assignments are not timing constraints; they belong in
#     constraints/de1soc/pin_assignments.tcl.

# -----------------------------------------------------------------------------
# Helper procs
# -----------------------------------------------------------------------------

proc trecap_ports {pattern} {
    return [get_ports -nowarn $pattern]
}

proc trecap_regs {pattern} {
    return [get_registers -nowarn $pattern]
}

proc trecap_create_clock_if_port {clock_name period_ns port_pattern} {
    set ports [trecap_ports $port_pattern]
    if {[get_collection_size $ports] > 0} {
        create_clock -name $clock_name -period $period_ns $ports
    }
}

proc trecap_set_input_delay_if_ports {clock_name delay_ns port_patterns} {
    if {[get_collection_size [get_clocks -nowarn $clock_name]] == 0} {
        return
    }
    foreach pattern $port_patterns {
        set ports [trecap_ports $pattern]
        if {[get_collection_size $ports] > 0} {
            set_input_delay -clock $clock_name $delay_ns $ports
        }
    }
}

proc trecap_set_output_delay_if_ports {clock_name delay_ns port_patterns} {
    if {[get_collection_size [get_clocks -nowarn $clock_name]] == 0} {
        return
    }
    foreach pattern $port_patterns {
        set ports [trecap_ports $pattern]
        if {[get_collection_size $ports] > 0} {
            set_output_delay -clock $clock_name $delay_ns $ports
        }
    }
}

proc trecap_false_path_from_ports {port_patterns} {
    foreach pattern $port_patterns {
        set ports [trecap_ports $pattern]
        if {[get_collection_size $ports] > 0} {
            set_false_path -from $ports
        }
    }
}

proc trecap_false_path_to_regs {reg_patterns} {
    foreach pattern $reg_patterns {
        set regs [trecap_regs $pattern]
        if {[get_collection_size $regs] > 0} {
            set_false_path -to $regs
        }
    }
}

# -----------------------------------------------------------------------------
# Baseline clocks
# -----------------------------------------------------------------------------

# The logical top uses input port clk and the implemented DE1-SoC board wrapper exposes CLOCK_50.
# Both are constrained only if the corresponding selected top-level port exists.
trecap_create_clock_if_port clk      20.000 clk
trecap_create_clock_if_port CLOCK_50 20.000 CLOCK_50

# The instantiated Step-16 audio PLL is handled by derive_pll_clocks below. Optional aliases and
# external codec-master BCLK/LRCK timing is defined in clocks.sdc.

# -----------------------------------------------------------------------------
# Reset constraints
# -----------------------------------------------------------------------------

# Reset assertion is asynchronous; reset release is synchronized in RTL.  In the physical top,
# KEY[0] asynchronously clears the 20 ms board-release qualifier and clock_reset_ctrl combines
# that qualified release with H2F reset before the sole platform reset synchronizer.
trecap_false_path_from_ports {
    rst_n
    reset_n
    KEY[0]
}

# -----------------------------------------------------------------------------
# CDC synchronizer first-stage cuts
# -----------------------------------------------------------------------------

# The RTL marks synchronizer chains with async_reg/preserve attributes.  These false paths
# cut asynchronous launch-to-first-stage analysis.  Do not use this section as a substitute
# for real CDC design.  Multi-bit crossings still require async FIFO, snapshot/commit, or
# another documented CDC mechanism.
# Use instance suffixes, which match both instance-only TimeQuest names and
# report names containing entity prefixes. Reset chains are explicitly scoped.
trecap_false_path_to_regs {
    *u_platform_reset_sync|sync_q[0]
    *u_bclk_rx_reset_sync|sync_q[0]
    *u_bclk_tx_reset_sync|sync_q[0]
    *g_sync_top_reset|u_reset_sync|sync_q[0]
    *|key_sync_q[*][0]
    *|sw_sync_q[*][0]
    *|src_ack_sync_q[0]
    *|dst_event_sync_q[0]
    *|src_req_sync_q[0]
    *|dst_done_sync_q[0]
    *|pll_locked_sync_q[0]
    *|bclk_codec_ready_sync_q[0]
    *|bclk_capture_enable_sync_q[0]
    *|bclk_tx_codec_ready_sync_q[0]
    *|bclk_lineout_enable_sync_q[0]
    *|bclk_tx_epoch_sync_q[0]
    *|clk_bclk_seen_sync_q[0]
    *|clk_lrck_seen_sync_q[0]
}

# Only synchronizer first stages are cut. Multi-bit audio payloads cross only through Gray-pointer
# async FIFOs; clocks.sdc constrains their pointer delay/skew and external codec I/O.
# ADC_SCLK remains a protocol output and is not an internal RTL clock.

# -----------------------------------------------------------------------------
# Current logical-top virtual-interface delays
# -----------------------------------------------------------------------------

# These ports are synchronous to clk in the pin-agnostic logical integration top and are marked
# virtual in de1soc.qsf.  They model internal Platform Designer/core-tap boundaries for smoke
# builds, not real board I/O timing.  When de1_soc_trecap_top.sv connects these buses inside
# the FPGA fabric, these external-port delays should disappear from the physical top.
set trecap_logical_inputs {
    csr_valid_i
    csr_write_i
    csr_addr_i[*]
    csr_wdata_i[*]
    avm_waitrequest_i
    avm_writeresponsevalid_i
    avm_response_i[*]
    tap_sample_i[*]
    tap_frame_i[*]
    tap_bin_valid_i
    tap_bin_frame_idx_i[*]
    tap_bin_idx_i[*]
    tap_bin_mag2_i[*]
    tap_bin_mask_i
    tap_bin_eligible_i
    tap_bin_last_i
    frame_boundary_i
    source_safe_boundary_i
    core_alive_i
    core_frame_count_i[*]
    core_sample_count_i[*]
    status_tick_i
    metrics_tick_i
    sample_rate_hz_i[*]
    external_overflow_flags_set_i[*]
    external_csr_reject_pulse_i
}

set trecap_logical_outputs {
    rst_n_sync_o
    csr_ready_o
    csr_rvalid_o
    csr_rdata_o[*]
    csr_error_o
    avm_address_o[*]
    avm_write_o
    avm_writedata_o[*]
    avm_byteenable_o[*]
    avm_burstcount_o[*]
    ctrl_o[*]
    ring_config_o[*]
    telemetry_soft_reset_pulse_o
    clear_metrics_pulse_o
    thr2_apply_pulse_o
    source_mode_apply_pulse_o
    clear_sticky_flags_w1c_o[*]
    ring_config_commit_pulse_o
    ring_wr_snapshot_req_pulse_o
    ring_rd_commit_req_pulse_o
    core_count_snapshot_pulse_o
    packet_fifo_drop_count_o[*]
    packet_fifo_drop_pulse_o
    packet_fifo_full_o
    packet_fifo_overflow_o
    scheduler_backpressure_o
    scheduler_disabled_drop_o
    scheduler_illegal_drop_o
    status_o[*]
    dma_status_o[*]
    overflow_flags_o[*]
    csr_command_reject_count_o[*]
    dma_drop_count_o[*]
    dma_packet_count_o[*]
    producer_ptr_o[*]
    consumer_ptr_o[*]
    sequence_o[*]
    used_bytes_o[*]
    free_bytes_o[*]
    current_offset_o[*]
    current_tail_bytes_o[*]
    writer_idle_o
    writer_busy_o
    writer_no_space_o
    malformed_config_o
    ring_full_o
    ddr_wait_o
    drop_active_o
    ring_configured_o
    pointers_valid_o
    writer_fault_sticky_o
    normal_commit_pulse_o
    wrap_commit_pulse_o
    writer_drop_pulse_o
    writer_malformed_pulse_o
    writer_oversized_pulse_o
    ring_rd_accept_pulse_o
    ring_rd_reject_pulse_o
    writer_ring_wr_snapshot_valid_o
    writer_ring_wr_snapshot_pulse_o
    packet_fifo_full_status_o
    packet_fifo_overflow_status_o
    packet_enable_illegal_o
    spec_mode_illegal_o
    spec_shift_illegal_o
    wave_decim_illegal_o
    telemetry_config_illegal_o
    telemetry_active_o
    core_tap_seen_o
    full_path_alive_o
}

trecap_set_input_delay_if_ports  clk 0.000 $trecap_logical_inputs
trecap_set_output_delay_if_ports clk 0.000 $trecap_logical_outputs

# -----------------------------------------------------------------------------
# Derived timing data
# -----------------------------------------------------------------------------

# Derive the Step-16 peripheral audio PLL clock without introducing a fabric/core clock domain.
# Platform Designer QIP owns its timing; clocks.sdc supplies physical audio/ADC constraints.
derive_pll_clocks

# Let TimeQuest derive baseline clock uncertainty from the device timing models.
derive_clock_uncertainty

# End of constraints/de1soc/de1soc.sdc

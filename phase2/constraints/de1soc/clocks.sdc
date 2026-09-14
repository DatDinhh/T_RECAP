# SPDX-License-Identifier: MIT
# Physical board timing contract. Numeric margins are design allocations, not measurements.
# Reference: docs/architecture/physical_timing.md and config/boards/physical_timing.json.

proc trecap_physical_regs {pattern} { return [get_registers -nowarn $pattern] }
proc trecap_bound_cdc {source_pattern destination_pattern max_ns {required 0} {direct_net 0}} {
    set source [trecap_physical_regs $source_pattern]
    set destination [trecap_physical_regs $destination_pattern]
    if {[get_collection_size $source] && [get_collection_size $destination]} {
        # No false path/clock-group exception may override these physical bounds.
        set_max_delay -from $source -to $destination $max_ns
        set_min_delay -from $source -to $destination 0.000
        set_max_skew -from $source -to $destination 10.000
        if {$direct_net} {
            # Quartus 20.1 has no -ignore_clock_latency option. Net constraints
            # additionally bound direct Gray Q-to-first-stage D wiring without
            # clock-network credit; the post-fit gate checks full data paths.
            set_net_delay -max -from $source -to $destination $max_ns
            set_net_delay -min -from $source -to $destination 0.000
        }
    } elseif {$required} {
        error "T-RECAP: missing required CDC endpoint: $source_pattern -> $destination_pattern"
    }
}

# The platform reset is asynchronous to codec BCLK. Only the asynchronous
# clear pins of the two reset synchronizers are exempt; their inter-stage data
# paths and the synchronized reset distribution remain timed. Later stages
# hold zero while reset release propagates through the chain.
foreach {reset_chain required} {u_bclk_rx_reset_sync 1 u_bclk_tx_reset_sync 0} {
    # Pin wildcards otherwise stop at hierarchy boundaries in Quartus 20.1.
    set clear_pins [get_pins -nowarn -compatibility_mode [format {*%s|sync_q*|clrn} $reset_chain]]
    if {[get_collection_size $clear_pins]} {
        set_false_path -to $clear_pins
    } elseif {$required && [get_collection_size [get_ports -nowarn AUD_BCLK]]} {
        error "T-RECAP: missing codec reset-synchronizer clear pins: $reset_chain"
    }
}

if {[get_collection_size [get_ports -nowarn AUD_BCLK]]} {
    # Codec-master clock, independent external phase; not a fabricated PLL alias.
    create_clock -name codec_bclk -period 325.520833 [get_ports AUD_BCLK]
    set_clock_uncertainty -setup -from [get_clocks codec_bclk] -to [get_clocks codec_bclk] 0.500
    set_clock_uncertainty -hold -from [get_clocks codec_bclk] -to [get_clocks codec_bclk] 0.500
    # WM8731 Rev4.9 p16: falling-edge launch, ADCDAT max35ns, LRCK max10ns.
    # +/-2ns allocation for clock/data board skew.
    set_input_delay -clock codec_bclk -clock_fall -max 37.000 [get_ports AUD_ADCDAT]
    set_input_delay -clock codec_bclk -clock_fall -min -2.000 [get_ports AUD_ADCDAT]
    set_input_delay -clock codec_bclk -clock_fall -max 12.000 [get_ports {AUD_ADCLRCK AUD_DACLRCK}]
    set_input_delay -clock codec_bclk -clock_fall -min -2.000 [get_ports {AUD_ADCLRCK AUD_DACLRCK}]
    # FPGA changes DACDAT on falling BCLK; codec captures rising BCLK, setup/hold10ns.
    set_output_delay -clock codec_bclk -max 12.000 [get_ports AUD_DACDAT]
    set_output_delay -clock codec_bclk -min -12.000 [get_ports AUD_DACDAT]

    foreach fifo {u_audio_rx_fifo u_audio_tx_fifo} {
        set required [expr {$fifo eq "u_audio_rx_fifo"}]
        trecap_bound_cdc "*${fifo}*|wr_gray_q*" "*${fifo}*|wr_gray_sync_rd_q*" 20.000 $required 1
        trecap_bound_cdc "*${fifo}*|rd_gray_q*" "*${fifo}*|rd_gray_sync_wr_q*" 20.000 $required 1
    }
    # FIFO payload storage is deliberately logic with a held, already-published word.
    # The minimum publication path crosses two pointer synchronizer stages first.
    # Bound the direct payload read path; do not false-path the complete clocks.
    trecap_bound_cdc {*u_audio_rx_fifo*|mem*} {*u_audio_codec_wrapper*|audio_*_o*} 20.000 1
    trecap_bound_cdc {*u_audio_tx_fifo*|mem*} {*u_audio_codec_wrapper*|bclk_lineout_left_q*} 20.000
    trecap_bound_cdc {*u_audio_tx_fifo*|mem*} {*u_audio_codec_wrapper*|bclk_lineout_right_q*} 20.000

    # Control acknowledgement uses the existing two-stage synchronizer.
    set ack [get_registers -nowarn {*capture_enable_ack_q[0]}]
    if {[get_collection_size $ack]} { set_false_path -to $ack }
}

# These five slow-control outputs have a physical propagation allocation, not
# a capture edge at an external CLOCK_50 receiver. In Quartus 20.1 ordinary
# max/min exceptions add launch-clock latency, so they are the wrong model.
# The mandatory fitted gate bounds complete register-to-port data paths,
# including all logic and I/O cell delays. Quartus 20.1 reports no nets for
# register-to-unclocked-port net-delay assignments; do not emit ineffective
# fitter guidance or invent a capture clock for these physical data budgets.
proc trecap_bound_output_data {port_name max_ns} {
    set target [get_ports -nowarn $port_name]
    if {[get_collection_size $target] != 1} { error "T-RECAP: missing unique output data port $port_name" }
    # Store only the scalar contract here. The fitted gate traverses and
    # validates actual fan-in after placement, without retaining timing-netlist
    # objects across the Fitter's netlist preparation/rebuild lifecycle.
    set ::trecap_output_data_max_ns($port_name) $max_ns
}

if {[get_collection_size [get_ports -nowarn ADC_DOUT]]} {
    # ADC_SCLK is an output waveform driven by the 50MHz FSM, not an internal RTL clock.
    # Budget the registered output and return routing directly. The serial FSM provides
    # the 200ns low/high timing; the external 100ns return allocation is accounted in docs.
    foreach port_name {ADC_SCLK ADC_CS_N ADC_DIN} { trecap_bound_output_data $port_name 5.000 }
    set adc_first [get_registers -nowarn {*adc_dout_sync_q[0]}]
    if {[get_collection_size $adc_first] != 1} { error "T-RECAP: expected exactly one ADC first-stage synchronizer" }
    # DOUT enters the continuously sampled first synchronizer stage without a
    # deterministic phase relative to CLOCK_50. A 0ns clock-relative minimum
    # invents a first-stage hold relationship. Cut only that hold check; keep
    # setup-directed placement and all interstage/consumer checks enabled.
    # The fitted gate separately requires the shortest/longest data-only paths
    # to lie within 0..10ns. The complete serial return budget is 177ns/200ns.
    set_max_delay -from [get_ports ADC_DOUT] -to $adc_first 10.000
    set_false_path -hold -from [get_ports ADC_DOUT] -to $adc_first
}

# Generated PLL and HPS clocks stay owned by derive_pll_clocks and the generated QIP.
# Timing analysis must use that QIP; a hand-written guessed system-clock alias is not used.

# Codec control is a 100kHz open-drain protocol. Hold the route allocation
# separately from the 5us FSM half-period and board RC settling allocation.
if {[get_collection_size [get_ports -nowarn FPGA_I2C_SDAT]]} {
    foreach port_name {FPGA_I2C_SCLK FPGA_I2C_SDAT} { trecap_bound_output_data $port_name 20.000 }
    set sda_first [get_registers -nowarn {*sda_sync_q[0]}]
    if {![get_collection_size $sda_first]} { error "T-RECAP: missing SDA first-stage synchronizer" }
    set_max_delay -from [get_ports FPGA_I2C_SDAT] -to $sda_first 20.000
    set_min_delay -from [get_ports FPGA_I2C_SDAT] -to $sda_first 0.000
}

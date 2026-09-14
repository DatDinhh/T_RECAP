# SPDX-License-Identifier: MIT
# T-RECAP Phase 2 DE1-SoC board pin assignment scaffold.
# File class: [1] hand-written Quartus assignment source.
# Layer: constraints/de1soc/
# Owner: T-RECAP Phase 2 implementation.
#
# Purpose:
#   Own physical FPGA-side package pin assignments for the board-facing wrapper
#   rtl/platform/de1soc/de1_soc_trecap_top.sv.  This file intentionally does not assign
#   abstract logical integration ports from rtl/top/trecap_de1soc_full_top.sv.
#
# Important policy:
#   - HPS DDR, HPS Ethernet, and HPS pin-mux details belong to Platform Designer/HPS
#     configuration, not to hand-written random FPGA pin assignments in this file.
#   - This file assigns only standard FPGA-side board ports used by the T-RECAP bring-up:
#     clocks, KEY, SW, LEDR, HEX, audio codec pins, and external ADC serial pins.
#   - If the board wrapper uses different port names, add explicit aliases here instead of
#     renaming assignments silently.
#   - Verify against the actual DE1-SoC board revision before programming hardware.

# -----------------------------------------------------------------------------
# Helper procs
# -----------------------------------------------------------------------------

# Assignments are loaded before a timing netlist exists. Emit the fixed board
# ports unconditionally; Quartus binds and checks them during compilation.
proc trecap_pin {pin_name port_name {io_standard "3.3-V LVTTL"}} {
    set_location_assignment $pin_name -to $port_name
    if {![string equal $io_standard ""]} {
        set_instance_assignment -name IO_STANDARD $io_standard -to $port_name
    }
}

proc trecap_pullup {port_name} {
    set_instance_assignment -name WEAK_PULL_UP_RESISTOR ON -to $port_name
}

# -----------------------------------------------------------------------------
# FPGA-side 50 MHz clocks
# -----------------------------------------------------------------------------

trecap_pin PIN_AF14 CLOCK_50
trecap_pin PIN_AA16 CLOCK2_50
trecap_pin PIN_Y26  CLOCK3_50
trecap_pin PIN_K14  CLOCK4_50

# -----------------------------------------------------------------------------
# Push buttons, active low
# -----------------------------------------------------------------------------

trecap_pin PIN_AA14 {KEY[0]}
trecap_pin PIN_AA15 {KEY[1]}
trecap_pin PIN_W15  {KEY[2]}
trecap_pin PIN_Y16  {KEY[3]}

foreach trecap_key_port {KEY[0] KEY[1] KEY[2] KEY[3]} {
    trecap_pullup $trecap_key_port
}

# -----------------------------------------------------------------------------
# Slide switches
# -----------------------------------------------------------------------------

trecap_pin PIN_AB12 {SW[0]}
trecap_pin PIN_AC12 {SW[1]}
trecap_pin PIN_AF9  {SW[2]}
trecap_pin PIN_AF10 {SW[3]}
trecap_pin PIN_AD11 {SW[4]}
trecap_pin PIN_AD12 {SW[5]}
trecap_pin PIN_AE11 {SW[6]}
trecap_pin PIN_AC9  {SW[7]}
trecap_pin PIN_AD10 {SW[8]}
trecap_pin PIN_AE12 {SW[9]}

# -----------------------------------------------------------------------------
# Red LEDs
# -----------------------------------------------------------------------------

trecap_pin PIN_V16 {LEDR[0]}
trecap_pin PIN_W16 {LEDR[1]}
trecap_pin PIN_V17 {LEDR[2]}
trecap_pin PIN_V18 {LEDR[3]}
trecap_pin PIN_W17 {LEDR[4]}
trecap_pin PIN_W19 {LEDR[5]}
trecap_pin PIN_Y19 {LEDR[6]}
trecap_pin PIN_W20 {LEDR[7]}
trecap_pin PIN_W21 {LEDR[8]}
trecap_pin PIN_Y21 {LEDR[9]}

# -----------------------------------------------------------------------------
# Seven-segment displays, active-low segment drive by board convention
# -----------------------------------------------------------------------------

trecap_pin PIN_AE26 {HEX0[0]}
trecap_pin PIN_AE27 {HEX0[1]}
trecap_pin PIN_AE28 {HEX0[2]}
trecap_pin PIN_AG27 {HEX0[3]}
trecap_pin PIN_AF28 {HEX0[4]}
trecap_pin PIN_AG28 {HEX0[5]}
trecap_pin PIN_AH28 {HEX0[6]}

trecap_pin PIN_AJ29 {HEX1[0]}
trecap_pin PIN_AH29 {HEX1[1]}
trecap_pin PIN_AH30 {HEX1[2]}
trecap_pin PIN_AG30 {HEX1[3]}
trecap_pin PIN_AF29 {HEX1[4]}
trecap_pin PIN_AF30 {HEX1[5]}
trecap_pin PIN_AD27 {HEX1[6]}

trecap_pin PIN_AB23 {HEX2[0]}
trecap_pin PIN_AE29 {HEX2[1]}
trecap_pin PIN_AD29 {HEX2[2]}
trecap_pin PIN_AC28 {HEX2[3]}
trecap_pin PIN_AD30 {HEX2[4]}
trecap_pin PIN_AC29 {HEX2[5]}
trecap_pin PIN_AC30 {HEX2[6]}

trecap_pin PIN_AD26 {HEX3[0]}
trecap_pin PIN_AC27 {HEX3[1]}
trecap_pin PIN_AD25 {HEX3[2]}
trecap_pin PIN_AC25 {HEX3[3]}
trecap_pin PIN_AB28 {HEX3[4]}
trecap_pin PIN_AB25 {HEX3[5]}
trecap_pin PIN_AB22 {HEX3[6]}

trecap_pin PIN_AA24 {HEX4[0]}
trecap_pin PIN_Y23  {HEX4[1]}
trecap_pin PIN_Y24  {HEX4[2]}
trecap_pin PIN_W22  {HEX4[3]}
trecap_pin PIN_W24  {HEX4[4]}
trecap_pin PIN_V23  {HEX4[5]}
trecap_pin PIN_W25  {HEX4[6]}

trecap_pin PIN_V25  {HEX5[0]}
trecap_pin PIN_AA28 {HEX5[1]}
trecap_pin PIN_Y27  {HEX5[2]}
trecap_pin PIN_AB27 {HEX5[3]}
trecap_pin PIN_AB26 {HEX5[4]}
trecap_pin PIN_AA26 {HEX5[5]}
trecap_pin PIN_AA25 {HEX5[6]}

# -----------------------------------------------------------------------------
# Audio codec, FPGA-side pins
# -----------------------------------------------------------------------------

# The Step-16 LINE-IN path drives AUD_XCK from the reviewed 50 MHz -> 12.288 MHz audio PLL.
# In WM8731 codec-master mode, BCLK and LRCK return from the codec and remain asynchronous to
# the fabric clock.  FPGA_I2C_SCLK/SDAT are the FPGA side of the board's codec-control mux;
# software must leave HPS_I2C_CONTROL low while FPGA codec initialization owns this bus.
trecap_pin PIN_K7 AUD_ADCDAT
trecap_pin PIN_K8 AUD_ADCLRCK
trecap_pin PIN_H7 AUD_BCLK
trecap_pin PIN_J7 AUD_DACDAT
trecap_pin PIN_H8 AUD_DACLRCK
trecap_pin PIN_G7 AUD_XCK

# WM8731 control bus.  FPGA_I2C_SDAT is open-drain in RTL and relies on the board-level external
# pull-up; do not enable a Cyclone-V weak pull-up or ever drive the signal high from fabric.
trecap_pin PIN_J12 FPGA_I2C_SCLK
trecap_pin PIN_K12 FPGA_I2C_SDAT

# -----------------------------------------------------------------------------
# External ADC serial interface, FPGA-side pins
# -----------------------------------------------------------------------------

trecap_pin PIN_AJ4 ADC_CS_N
trecap_pin PIN_AK4 ADC_DIN
trecap_pin PIN_AK3 ADC_DOUT
trecap_pin PIN_AK2 ADC_SCLK

# -----------------------------------------------------------------------------
# Explicit non-assignments
# -----------------------------------------------------------------------------

# HPS DDR3, HPS Ethernet, HPS USB, HPS SD card, HPS UART, and HPS GPIO pin ownership
# is handled by Platform Designer / HPS configuration and generated assignment files.
# Do not add hand-written assignments for those interfaces here unless the Platform
# Designer/HPS integration document explicitly requires it.

# End of constraints/de1soc/pin_assignments.tcl

# Keep the asynchronous ADC input's first sampling register at its I/O cell.
# The post-fit data-path gate retains the 10 ns input budget; this is a packing
# request, not a timing exception or a guarantee of placement.
set_instance_assignment -name FAST_INPUT_REGISTER ON -to {u_adc_wrapper|adc_dout_sync_q[0]}

# Keep the three existing ADC output registers in their I/O cells. This requests
# placement only; it adds no protocol stage and retains the full 0..5 ns
# register-to-pad check, including the 3.3-V I/O buffer delay. Internal SCLK
# feedback remains timed even if the Fitter uses a separate register copy.
foreach adc_output_port {ADC_SCLK ADC_CS_N ADC_DIN} {
    set_instance_assignment -name FAST_OUTPUT_REGISTER ON -to $adc_output_port
}
unset adc_output_port

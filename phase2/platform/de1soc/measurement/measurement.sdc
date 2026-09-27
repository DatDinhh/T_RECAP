# All useful work runs directly from the board's 50 MHz oscillator.
create_clock -name CLOCK_50 -period 20.000 [get_ports CLOCK_50]
derive_clock_uncertainty
# Only the external asynchronous reset is excepted. Its synchronous distribution
# and every CLOCK_50 datapath remain timed. The fixed LED outputs carry no data.
set_false_path -from [get_ports {KEY[0]}]
set_false_path -to [get_ports {LEDR[*]}]
# The JTAG IP is asynchronous to CLOCK_50. Its built-in two-stage source
# synchronizer and the held snapshot protocol handle the crossing. No broad
# exception is applied to CLOCK_50-to-CLOCK_50 paths.

create_clock -name CLOCK_50 -period 20.000 [get_ports CLOCK_50]
derive_pll_clocks
derive_clock_uncertainty
# The HPS reset output asserts a shared reset asynchronously. Only the
# synchronizer clear pins are cut; its stage-to-stage release remains timed.
set reset_clears [get_pins -nowarn -compatibility_mode {*reset_release*|clrn}]
if {[get_collection_size $reset_clears] == 0} {error "Missing reset-release synchronizer clear pins"}
set_false_path -to $reset_clears
set_false_path -to [get_ports {LEDR[*]}]

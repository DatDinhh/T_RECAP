# SPDX-License-Identifier: MIT
# T-RECAP Phase 2 DE1-SoC supplemental clock policy.
# File class: [1] hand-written timing constraint source.
# Layer: constraints/de1soc/
# Owner: T-RECAP Phase 2 implementation.
#
# Step-10 baseline plus Step-16 audio-clock and Step-17 ADC-clock policy:
#   - constraints/de1soc/de1soc.sdc is the sole source-owned creator of the active fabric clock.
#   - CLOCK_50 is constrained there at 20.000 ns and feeds the clk_fabric alias directly.
#   - CLOCK2_50, CLOCK3_50, and CLOCK4_50 are reserved physical pins, not active clock domains.
#   - Step 16 implements AUD_XCK with the reviewed 50 MHz-to-12.288 MHz peripheral audio PLL;
#     derive_pll_clocks in de1soc.sdc owns its generated-clock derivation.
#   - Codec-master AUD_BCLK/LRCK external I/O delays, clock groups, and board timing closure remain
#     explicitly deferred to Step 18; no guessed live-audio timing exception is added here.
#   - ADC_SCLK is a registered protocol output, not an internal/generated RTL clock.
#   - Platform Designer generated clocks/constraints remain deferred until real generation output
#     is available and reviewed.
#
# Consequently this supplemental file intentionally creates no additional clock, clock group,
# uncertainty, or I/O-delay exception. The Step-16/17 CDC/reset architecture is source-implemented;
# Step 18 must add reviewed external audio and ADC timing constraints backed by TimeQuest evidence.

# End of constraints/de1soc/clocks.sdc

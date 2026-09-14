# Board timing and clock ownership

We implement the physical source interface for the DE1-SoC Rev-H board profile,
50 MHz fabric, 48 ksample/s WM8731 codec-master audio, and 100 ksample/s LTC2308
acquisition. These are source design choices. The actual board revision and boot
image must match before deployment. The numeric ledger is
[`physical_timing.json`](../../config/boards/physical_timing.json); the executable
constraints are [`clocks.sdc`](../../constraints/de1soc/clocks.sdc) and
[`de1soc.sdc`](../../constraints/de1soc/de1soc.sdc).

## Fabric, PLL, and HPS clocks

`CLOCK_50` has a 20 ns period. The audio wrapper instantiates `altera_pll` for
12.288 MHz MCLK. Quartus must resolve the Cyclone V primitive, compensation, and
legal divider/VCO configuration. `derive_pll_clocks` owns that clock tree; the
portable phase-accumulator model is excluded from synthesis. It cannot establish
physical MCLK duty cycle, jitter, or analog operation.

The generated Platform Designer `system.qip` supplies the HPS/DDR IP and its
constraints. We do not reproduce hard-IP clock names in a guessed SDC alias.
The exported CSR and DDR fabric interfaces share CLOCK_50. A source elaboration
that treats `system` and `altera_pll` as external modules is useful for our RTL,
but does not elaborate their vendor implementations or establish timing closure.

AUD_XCK is a forwarded PLL clock. Confirm its derived clock reaches the output
pin, with the requested frequency and duty cycle, in the generated design.
The WM8731 requires a period of at least 54 ns, high/low times of at least 18 ns,
and a 40:60 to 60:40 duty cycle. The requested 12.288 MHz period is 81.3802 ns and
nominal high/low time 40.6901 ns; actual pad timing remains a fitted result.
[WM8731 Rev4.9, p 15](https://www.mouser.com/datasheet/2/76/WM8731_v4_9-1141834.pdf)

## Codec serial data

The codec is BCLK/LRCK master. We constrain the external BCLK independently at
3.072 MHz, period 325.520833 ns. Receive words are sampled on rising BCLK;
DAC output changes on falling BCLK and the codec captures it on the next rising
edge. LRCK transition handling follows the one-bit I2S delay in the wrapper.

WM8731 Rev4.9 specifies falling-edge ADCDAT delay 0..35 ns, LRCK delay 0..10 ns,
and DAC input setup/hold 10 ns. We allocate +/-2 ns for board clock/data skew and
0.5 ns clock uncertainty. This gives the following TimeQuest I/O values:

| Pin | Clock edge | Min delay | Max delay |
| --- | --- | ---: | ---: |
| AUD_ADCDAT input | Falling launch | -2 ns | 37 ns |
| AUD_ADCLRCK / AUD_DACLRCK input | Falling launch | -2 ns | 12 ns |
| AUD_DACDAT output | Rising capture | -12 ns | 12 ns |

The input delay is referenced to the codec launch edge, not the FPGA sampling
edge. The negative output minimum expresses the codec hold requirement.
The 2 ns board skew and 0.5 ns uncertainty are design allocations, not measurements.
[WM8731 Rev4.9, p 16](https://www.mouser.com/datasheet/2/76/WM8731_v4_9-1141834.pdf)

## Audio clock crossings

The RX/TX FIFO pointers are Gray coded with two synchronization stages. Their
payloads use explicitly selected logic storage with asynchronous reads. A word
is held until the synchronized read pointer returns ownership; the receiving
side cannot see the write pointer until its two-stage publication completes.

We constrain Gray launch-to-synchronizer delay to 20 ns and bus skew to 10 ns,
at the faster 20 ns fabric period. The direct FIFO payload-to-receiving-register
path is also bounded to 20 ns. RX constraints must resolve in the board top;
TX may disappear when LINE-OUT is disabled. Only single-bit control/status first
stages use false-path exceptions. Capture-stop acknowledgement has its own
fabric synchronizer, so rearm cannot mistake a stopped BCLK for a completed stop.

No broad asynchronous clock group or pointer false path overrides the delay/skew
bounds. This matters for the pinned Quartus 20.1 flow, where exception precedence
can mask a skew constraint. Post-fit endpoint collections, synchronizer placement,
route delay, and exceptions still need inspection in the generated design.
[Intel CDC constraints](https://www.intel.com/content/www/us/en/docs/programmable/683243/25-1/constraining-cdc-paths.html)

## ADC serial schedule

The ADC FSM runs entirely on CLOCK_50. ADC_SCLK is a registered output waveform,
not an internal RTL clock. At the baseline divider, each high/low phase lasts
10 fabric clocks (200 ns), for 2.5 MHz SCLK. CONVST is high for 2 clocks (40 ns), the
first SCLK rising edge occurs at cycle 92 (1840 ns), and a conversion transaction
occupies 334 clocks (6680 ns). Periodic requests are 500 clocks apart.

LTC2308 RevC requires CONVST high at least 20 ns, conversion time at most 1.6 us,
SCLK high/low at least 10 ns, SDI setup 0 ns/hold 2.5 ns, and at least 20 ns from the
last SCLK falling edge to the next CONVST rise. Acquisition from the seventh
SCLK rising edge to the next conversion must be at least 240 ns. The scheduled
transaction and 100 ksample/s request spacing allocate substantial margin to those
requirements. A nominal 40 ns CONVST pulse is not a measured 40 ns pulse at the ADC.
[LTC2308 RevC, p 5](https://www.analog.com/media/en/technical-documentation/data-sheets/2308fc.pdf)

The return path uses a two-stage synchronizer followed by the controller's
sampling edge. In `adc_wrapper.sv`, a falling SCLK launch at fabric edge E0 is
followed by the next rising-SCLK event at E10, 200 ns later. That E10 event reads
the previous value of the second synchronizer stage. We reserve 60 ns: up to one
20 ns cycle to reach a capture edge, one cycle to transfer into the second stage,
and one cycle before the controller can read that stage. Interstage and
controller setup/hold timing remain ordinary fabric timing requirements.

The subsequent-bit return budget is:

| Contribution | Allocation |
| --- | ---: |
| Registered FPGA output to pin | 5 ns |
| Combined board flight/skew | 2 ns |
| ADC output response | 100 ns |
| Input pin to first synchronizer | 10 ns |
| Synchronizer and controller sampling | 60 ns |
| Total / remaining margin | 177 ns / 23 ns |

We require at least one additional 20 ns fabric cycle of guard within that
remaining margin. For an input-path allocation `B_in`, the complete inequality is:

```text
5 + 2 + 100 + B_in + 60 + 20 <= 200 ns
B_in <= 13 ns
```

We choose 10 ns, one half of a fabric-clock period, leaving the required 20 ns
guard and another 3 ns unallocated. This is a schedule-based engineering
reallocation from the original 5 ns input allowance, not an LTC2308 timing
requirement or a threshold chosen to equal an observed fitted delay. The
native-10 input-register packing was applied and its largest reported input data
path was 5.886 ns. That observation alone does not establish that 5 ns is
physically impossible; detailed path components are needed for that conclusion.

The first bit has a separate deadline. CONVST rises at E0, remains high for two
fabric cycles, and is already low when conversion finishes. After the 80-cycle
conversion wait and the initial 10-cycle SCLK half-period, the controller consumes
B11 at E92, or 1840 ns. Conservatively applying the same 100 ns publication
allocation after the maximum conversion time gives:

```text
5 + 2 + 1600 + 100 + 10 + 60 = 1777 ns < 1840 ns
first-bit margin = 63 ns = 20 ns required guard + 43 ns
```

The 100 ns ADC response/publication value and 2 ns combined board flight/skew are
engineering allocations. The data-sheet 12.5 ns maximum clock-to-SDO value is
specified at OVDD=5 V and is not promoted to a guaranteed 3.3 V board value.
Physical qualification must establish the 100 ns allocation for both subsequent
bits and first-bit publication under the actual supply, load, temperature, and
board conditions. The published protocol places subsequent transitions after
falling SCK and makes the MSB available after conversion when CONVST is already
low. [LTC2308 RevC, pp 5 and 15](https://www.analog.com/media/en/technical-documentation/data-sheets/2308fc.pdf)

The input path is checked as an absolute pin-to-first-stage data path, with a
10 ns upper bound and nonnegative propagation, separately from ordinary fabric
hold analysis. The subsequent synchronizer and controller paths keep their
normal timing requirements. Output routes retain their 5 ns allocation. These
inequalities apply to the frozen 50 MHz fabric, divider 10, two-stage receiver
configuration; changing those parameters requires a new complete return budget.

With 0..5 ns output routing, SCLK high/low and CONVST pulse widths can differ by
up to 5 ns from their RTL intervals before board skew. DIN changes on falling SCLK
and is held across the following rising edge, leaving the half-cycle budget for
SDI setup/hold. No transport delay participates in this acquisition schedule.

## Slow-control output data paths

`ADC_SCLK`, `ADC_CS_N`, and `ADC_DIN` have a 0..5 ns registered-data propagation
allocation; `FPGA_I2C_SCLK` and `FPGA_I2C_SDAT` have a 0..20 ns allocation including
open-drain and ownership-control logic. These five outputs are physical data
paths in timed serial FSMs, not outputs captured by an external CLOCK_50 receiver.
Their protocol budgets remain as specified above and below.

The native-12 fit before explicit ADC output packing placed the three existing
output registers in fabric logic. Their slow-corner data paths had no
combinational logic levels but included substantial register-to-pin routing;
the largest complete delay was 5.608 ns, exceeding the unchanged 5 ns budget.
We therefore set `FAST_OUTPUT_REGISTER ON` on the exact `ADC_SCLK`, `ADC_CS_N`,
and `ADC_DIN` ports in
[`pin_assignments.tcl`](../../constraints/de1soc/pin_assignments.tcl). This requests
I/O-cell placement of existing registers. It adds no pipeline stage or protocol
latency and preserves their reset behavior. Internal SCLK phase feedback remains
active and normally timed, including when the fitter uses a separate register
copy. [Intel Fast Output Register option](https://www.intel.com/content/www/us/en/programmable/quartushelp/17.0/mapIdTopics/mwh1465427394966.htm)

The completed native-12 IO02 refit placed all three ADC output registers in
I/O cells. Its final four-corner gate passed: the largest complete ADC output
delay was 2.968 ns, below the unchanged 5 ns limit, and all shortest output paths
were nonnegative. This includes the 3.3 V I/O-buffer delay. The
[public implementation result](../results/de1soc_bram_native12.json) records the
per-port, per-corner measurements and report identities. The 2 ns board
allocation, 100 ns device-response allocation and 177 ns complete return budget
remain unchanged. Every new build must still satisfy the complete 0..5 ns bound;
this fitted result does not establish the external board/device allocations.

Quartus 20.1 `set_max_delay -to <port>` adds the launching register's clock-network
latency. In fitted native11, ADC_SCLK's 2.968 ns data path plus 4.997 ns clock
latency produced a spurious -2.965 ns result against a 5 ns absolute data budget.
The raw data path meets that budget. The installed API also requires a `-from`
pin of `set_max_delay` to be a clock pin and supports only port references for
`set_output_delay -reference_pin`; a fabricated internal reference is not used.

`clocks.sdc` resolves each exact output port and registers its scalar bound.
The mandatory fitted gate checks the actual register fan-in and complete paths. Quartus 20.1 reports no nets
for the attempted register-to-port `set_net_delay` assignments on these outputs;
we omit those ineffective assignments. The fitter receives no external
capture-edge timing requirement for these five ports. ADC outputs retain their
I/O-register placement request; acceptance still requires the complete data
route to meet its physical budget. The mandatory fitted gate uses both
longest `get_path` and shortest `get_path -min_path`, retains detailed
`report_path` output, and requires every corner to satisfy 0..5 ns or 0..20 ns.
All combinational, I/O-cell and routing delays are included. Missing ports,
register sources or connecting paths fail the gate. No false path or clock-group
cutoff is introduced for these outputs, and no budget is increased.

Conventional synchronous output-delay reports can list exactly these five ports
without an external capture-clock requirement. Their explicit disposition is
the compulsory physical data-path report; this is not a waiver for any other
unconstrained port or for internal setup/hold timing.

## Codec control bus

The supported I2C initialization rate is 100 kHz: 250 fabric clocks per 5 us half-cycle.
Both signals are open drain. SDA enters a preserved two-stage synchronizer and
ACK is sampled at the end of ACK_HIGH. We allocate 20 ns FPGA routing, 300 ns board
settling, and 60 ns synchronization/sampling, well within the 5 us phase. This path
uses a route bound rather than an unconstrained asynchronous input.

The codec's control interface permits at least 1.3 us low, 600 ns high, 100 ns data
setup, and 300 ns rise/fall limits. Board pull-ups must meet the settling allocation.
Clock stretching and multi-master arbitration are outside this dedicated control
bus. GPIO 48 ownership is held by our Linux platform driver throughout operation;
loss of grant aborts initialization and stops an active live-source epoch.
[WM8731 Rev4.9, p 19](https://www.mouser.com/datasheet/2/76/WM8731_v4_9-1141834.pdf)

## What remains after source implementation

Generate the selected vendor IP, resolve all required endpoint collections, fit
the target device, and examine setup/hold, recovery/removal, pulse width, skew,
and unconstrained-path reports. Board measurements must establish the stated
external allocations. These are implementation results and later hardware
qualification; the numeric budgets above do not substitute for them.


## HPS peripheral electrical standards

Our board constraints assign `3.3-V LVTTL` to all 55 exposed, non-DDR HPS
peripheral signals in `constraints/de1soc/hps_peripheral_io.tcl`: Ethernet,
QSPI flash, SD, UART, USB, SPI master, both I2C buses, and the named HPS GPIO
signals. These are electrical-standard assignments; generated `HPS_LOCATION`
assignments retain ownership of the hard-pin placement. The generated DDR pin
script separately supplies `HPS_DDR3_*` SSTL-15 standards and calibrated OCT.

The authority is the official
[Terasic DE1-SoC Rev-H System CD](https://download.terasic.com/downloads/cd-rom/de1-soc/DE1-SoC_v.6.0.0_HWrevH_SystemCD.zip),
member `Demonstrations/SOC_FPGA/de1_soc_GHRD/soc_system.qsf`, lines 252 and
325–378. That member contains exactly the same 55 non-DDR HPS signal names as
our top-level interface, all assigned `3.3-V LVTTL`.

| Source metadata | Value |
| --- | --- |
| Vendor package | DE1-SoC_v.6.0.0_HWrevH_SystemCD.zip |
| Source member | Demonstrations/SOC_FPGA/de1_soc_GHRD/soc_system.qsf |
| Member size | 70,899 bytes |
| Member SHA-256 | `4e38b4957b044cfd2ef4d8f8776cf590b02fe3bf388c57b9e51445b25ac8b3bd` |
| Member ZIP CRC32 | `aca297b8` |
| Retrieval | HTTPS byte-range reads of the vendor ZIP directory and this member |

This audit checked the extracted member's CRC and computed its SHA-256; it did
not recompute the full ZIP hash. The frozen Qsys preset contains the DDR voltage
and peripheral pinmux selections but no equivalent HPS peripheral I/O-standard
assignments. Registering generated HPS placement therefore does not replace these
board electrical assignments. Their source provenance does not establish physical
board revision, fitted timing, or live peripheral operation.

## HPS DDR3 physical-pin review

The board manual connects DDR3 to the dedicated HPS Hard Memory Controller I/O
banks. Our source-owned comparison ledger,
`config/boards/de1soc_hps_ddr_pins.json`, records all 72 package pins from Table
3-29 in the official Rev-H System CD manual, printed pages 50-52 (PDF pages
51-53), dated January 9, 2022. The ledger translates only the manual's `A` bus
name to our `ADDR` bus name and lowercase polarity suffixes to uppercase.
For example, `HPS_DDR3_RZQ` is `PIN_D27`, `HPS_DDR3_CK_N` is `PIN_L23`, and
`HPS_DDR3_CK_P` is `PIN_M23`.

The reviewed official GHRD QSF contains DDR electrical assignments but no
explicit DDR `set_location_assignment` records. We therefore keep this ledger
as comparison data and do not invent a second placement owner. The generated
DDR pin pass remains responsible for SSTL/OCT settings; a fitted `.pin` report
must establish the actual package locations.

Quartus warnings 169085 (72 pins without exact user locations) and 174073 (RZQ
without an exact user location) were observed during fitting. They concern
missing explicit location assignments and are not, by themselves, evidence of
correct or incorrect physical routing. They can be classified as expected for
this dedicated-HPS placement flow only after all 72 fitted DDR signal locations
match the ledger, including RZQ, and their generated electrical assignments are
present. A missing or differing location remains unresolved and blocks hardware
use; the warning count alone does not close this review.

The authority is the official
[Terasic DE1-SoC Rev-H System CD](https://download.terasic.com/downloads/cd-rom/de1-soc/DE1-SoC_v.6.0.0_HWrevH_SystemCD.zip),
member `UserManual/DE1-SoC_User_manual.pdf` (9,936,624 bytes, ZIP CRC32
`24dc16d3`, SHA-256
`f9d743dec68e9d5cc3d9a64c44231fde1d4ac0fed3f4961088fcacca2624e5b1`).
The member was extracted by HTTPS byte range, its CRC was checked, and its
SHA-256 was computed. The full ZIP hash was not computed. This source identifies
the reference board wiring; it does not identify the connected board revision
or establish completed fitted timing or live DDR operation.

We compare a completed artifact with the ledger and the source FPGA/HPS I/O
assignments using:

```bash
python scripts/check_fitted_pins.py \
  --pin-file platform/de1soc/quartus/output_files/trecap_de1soc.pin \
  --report runs/quartus/windows/<run-id>/fitted_pins.json
```

The checker requires both paths, reads the fitted artifact without changing it,
and records the artifact and source hashes in its JSON result. It requires all
209 board-top signal bits: 72 DDR locations and SSTL standards, 55 HPS peripheral
standards, and 82 FPGA locations and standards. The 10 dedicated HPS package
clock/reset/JTAG functions reported by Quartus are retained separately and are
not counted as compared top-level signals.

The native-09 fitted artifact passed this comparison with 209 matching signals,
including `HPS_DDR3_RZQ` at `PIN_D27`. The run-local record is
`runs/quartus/windows/20260913-bram-09/fitted_pins.json`. This resolves the physical
location question behind warnings 169085 and 174073 for that artifact. It does
not establish timing, calibrated OCT operation, or programming availability.

## Native reset and ADC timing constraints

The platform reset crosses into the independent codec BCLK domain through the
existing RX/TX reset synchronizers. Their asynchronous clear pins are exempt from
recovery/removal analysis of the unrelated platform-reset launch clock. The
inter-stage data paths and the locally synchronized reset fanout remain timed.
This follows the reset-synchronizer boundary described in
[Intel's reset timing guidance](https://www.intel.com/content/www/us/en/docs/programmable/683243/25-1/resolve-violation-asynchronous-reset.html).

The initial native-09 ADC input path measured 6.348 ns against the original
5 ns input allowance. We request I/O-cell packing for
`u_adc_wrapper|adc_dout_sync_q[0]` with `FAST_INPUT_REGISTER`. The independently
derived return budget above now allocates 10 ns to this input route, with 23 ns
remaining in the 200 ns sampling interval. The native-10 boundary audit measured
a largest data-only input delay of 5.886 ns across four corners, with positive
shortest propagation and passing interstage/consumer setup and hold. These
results preserve the two-stage sampling schedule and do not substitute for
board qualification of the external response allocation.
[Intel Fast Input Register option](https://www.intel.com/content/www/us/en/programmable/quartushelp/17.0/mapIdTopics/mwh1465427392898.htm)

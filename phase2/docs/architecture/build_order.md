# Build order and development tools

The root build files orchestrate the reference library, HPS application, generated contracts, and FPGA source lists. They do not replace each component's toolchain. Use this guide together with the [implementation plan](architecture_implementation.md) and the [platform setup guide](../bringup/quartus_programming.md).

## Tool environments

| Work | Environment |
| --- | --- |
| Repository maintenance and CI | Python 3.12 baseline; root hygiene uses the standard-library TOML parser |
| Reference-model/dashboard Python packages | Python 3.10+ according to their package metadata |
| Reference library | C++20 compiler and CMake 3.24+ |
| Root Makefile | GNU Make with Bash |
| HPS application | Linux/POSIX build for the DE1-SoC HPS target or supported cross-compiler |
| PC dashboard | Python and dependencies in `sw/pc_dashboard/pyproject.toml` |
| FPGA project | Supported Intel Quartus/Platform Designer installation and DE1-SoC board sources |

Windows entry points use CMake for the host library and the provided PowerShell scripts for platform setup. The Bash Makefile is not a native PowerShell script. A host compile of the HPS application is not an HPS deployment.

## First build

From the repository root:

```bash
cmake --preset host
cmake --build --preset host
```

The host preset builds the reference model and disables test targets. On Linux, the `hps` preset adds a native build of the HPS application:

```bash
cmake --preset hps
cmake --build --preset hps
```

A direct reference-only component build remains available:

```bash
cmake -S sw/reference_model -B build/reference_model -DCMAKE_BUILD_TYPE=Release -DTRECAP_BUILD_TESTS=OFF
cmake --build build/reference_model --config Release
```

With the root `host` preset, the reference runner's typical location is:

| CMake generator | Executable |
| --- | --- |
| Unix Makefiles or Ninja on Linux | `build/host/reference_model/phase2_golden_model` |
| Visual Studio on Windows, Release configuration | `build/host/reference_model/Release/phase2_golden_model.exe` |

For the direct component build above, remove `host/` from those paths. Other
generators or configurations may use a different layout. The executable keeps
its historical name; the reference tools accept an explicit `--reference-exe`
path when automatic discovery does not match the selected build directory.

The Linux `hps` preset uses the selected native compiler. Building on an x86 Linux
host does not produce an ARM HPS deployment binary. Build on the HPS itself or
select a suitable cross-toolchain for target deployment; the preset does not
supply an ARM toolchain or configure the board's Linux runtime.

For the normal on-board build, `make hps-build` writes
`build/hps/bin/trecap_udp_streamer`, which is the HPS launcher's default.
The CMake `hps` preset instead writes `build/hps-host/trecap_udp_streamer` with
single-configuration Linux generators. If that CMake binary was built for the
HPS target, select it explicitly when launching on the configured board:

```bash
sw/hps/scripts/run_udp_streamer.sh --no-build --binary build/hps-host/trecap_udp_streamer --profile config/profiles/de1soc_bram_replay.json
```

The launcher also needs the board's Linux memory reservation, platform driver, CSR mappings,
network configuration, and matching FPGA bitstream. The command above is not a
host-only substitute for that platform setup.

Refer to [sw/reference_model/README.md](../../sw/reference_model/README.md) for its artifact and analysis commands. `make help` lists the wider root command surface, including existing diagnostic targets; no diagnostic result is implied by this guide.

## Shared files before RTL builds

```bash
make gen-headers
make rtl-filelist
```

Header generation consumes the root machine-readable contracts. Source-list generation owns RTL dependency order. Change the input contracts or generator when necessary; do not maintain local edits to generated SV/C/Python headers or filelists.

The reference model and root implementation have a deliberate boundary: reference code owns the arithmetic source snapshot, while the root also owns CSR, telemetry, and board contracts. A runtime profile selects a composition and source but does not change synthesized arithmetic constants by itself.

## Production RTL source elaboration

Use a dedicated Python environment and the pinned frontend/schema dependencies:

```bash
python -m pip install -r scripts/requirements-source.txt
python scripts/elaborate_rtl_sources.py
```

This elaborates `de1_soc_trecap_top` with SYNTHESIS defined and writes diagnostics
under `build/`. Only the vendor modules `system` and `altera_pll` may remain
external. Other unknown modules are errors. It does not use testbench stubs, run
a simulator, or execute the reference model. Non-error diagnostics are retained
in the report; a successful source compile is not a timing or functional result.

The Quartus build wrapper runs contract-generation and platform-address checks
by default. Historical source/model checks are available explicitly through
`--with-legacy-checks`; they are maintained separately from this source build.
The [Linux source recipe](../../platform/de1soc/linux/README.md) defines the
kernel/DTB/module and offline runtime installation commands.

## Component order

| Stage | Source dependency |
| --- | --- |
| Reference and coefficients | Arithmetic configuration, coefficient tables, finite-stream conventions |
| RTL foundation | Generated packages, typed interfaces, reset/FIFO/RAM helpers |
| Core | FFT/IFFT, windows, frame scheduler, mask, WOLA, metrics, core-only top |
| Telemetry | Core tap interface, packet layout, packetizers and FIFO |
| HPS bridge | CSR adapter/bank, ring lifecycle, record builder and writer |
| Source/core integration | Core plus replay/audio/ADC/diagnostic adapters |
| Physical board | Logical owners, clock/reset, peripheral wrappers, generated platform boundary |
| HPS and dashboard | Generated CSR/packet contracts and supported runtime configuration |

The core-first build excludes HPS, DDR, Ethernet and board pins. Telemetry/HPS development can proceed against their interfaces while physical integration is being completed, but cannot redefine the mathematical contract.

## FPGA source lists and commands

| Target | Scope |
| --- | --- |
| `make compile-core` | Core dependency closure in `filelists/rtl_core_plus_fft.f` |
| `make compile-telemetry` | Packet formatters and telemetry FIFO |
| `make compile-core-telemetry` | Standalone core-plus-telemetry composition |
| `make compile-hps-bridge` | CSR, record and DDR ownership |
| `make quartus-de1soc` | Full physical board project with an explicit profile |
| `make hps-build` | HPS transport application |

The compile targets require their configured external tools. Full-board generation depends on the pinned Platform Designer source, address-map reconciliation, generated vendor products, and timing/pin constraints. See [platform_designer_wrapper.md](platform_designer_wrapper.md), [memory_map.md](memory_map.md), and [quartus_programming.md](../bringup/quartus_programming.md).

## Native Windows Quartus build

Use Windows PowerShell 5.1 or PowerShell 7 with Quartus Prime Standard 20.1
(including the 20.1.1 update) and Python 3.12. Set `QUARTUS_ROOTDIR` to the installed
Quartus component directory, or replace that argument below with its actual path.
The script also accepts an installation directory containing `quartus` or
`quartusfpga/quartus`.
It resolves native tools under that installation and does not require Bash or WSL.

```powershell
.\scripts\quartus\build_de1soc.ps1 `
    -QuartusRoot $env:QUARTUS_ROOTDIR `
    -Python python `
    -Profile config/profiles/de1soc_bram_replay.json
```

`-Python` accepts a Python executable path when `python` on PATH is not the desired
interpreter. `-RunDirectory` selects an empty log directory; relative paths are
resolved from the repository root. Without it, the script creates a timestamped
directory under `runs/quartus/windows/`.

The wrapper checks generated headers/filelists, the source HPS/address contracts,
and the selected profile before resolving `effective_runtime.json` and the
run-specific `profile_parameters.qsf`. Platform Designer uses Tcl API package
16.0: it constructs the checked-in bootstrap once, or captures parameter readbacks
from an existing normalized `system.qsys`. Tcl arguments, including the Python
path, are passed as UTF-8 hex values to preserve Windows path characters.
Both Qsys commands add the source-owned CSR bridge component at
`platform/de1soc/qsys/ip/trecap_csr_bridge/*` to their IP search path and retain the
standard Quartus catalog through the literal `$` search entry (`<component-dir>/*,$`). The effective
search path is recorded in the build manifest. `qsys-generate` then produces
Verilog. Generated address/interface checks precede the staged Quartus flow in
`platform/de1soc/quartus/`: Analysis & Synthesis (`quartus_map`), generated HPS
DDR pin assignments, Fitter (`quartus_fit`), Assembler (`quartus_asm`), then
TimeQuest (`quartus_sta`), and the fitted timing gate. The resolved profile include
remains active throughout.

Use `-GenerateOnly` to stop after Platform Designer generation and its source
interface checks. Use `-SkipPlatformGenerate` for an already generated normalized
system: the script recaptures HPS parameter readbacks and checks existing products
before compiling. These switches cannot be combined. Existing generated files are
kept; the wrapper does not recursively clean build directories or patch vendor HDL.

Every external stage has its own `.log` and a recorded exit code in
`build_manifest.json`; the first failure stops the flow. The run also records
Platform Designer provenance and the selected profile. A completed FPGA compile
records `platform/de1soc/quartus/output_files/trecap_de1soc.sof` and its hash.
An assembler exit code of zero is not proof that an image was produced. The
wrappers record SOF presence immediately after assembly, continue timing reports
if it is missing, and fail the overall build before completion. Evaluation or
license restrictions must be resolved before a programmable image can be claimed.
The script creates build products only; board programming is a separate operation.
It does not invoke models, simulation, negative tests, or the historical verification
checklist. Tool compilation results must still be distinguished from functional
or hardware signoff.

### Native synthesis warning review

The native-12 synthesis completed with 1,741 warnings and no errors. Its complete
map report contains no divider or remainder megafunctions. WAVE uses 4,965
combinational ALUTs instead of 9,659, with the same 7,219 dedicated registers and
four additional DSP blocks. Total DSP use is 36; these synthesis ALUT counts are
not fitted ALM counts. The [storage schedule](storage_schedule.md) proves the
bounded reciprocal and radix-4 arithmetic and documents source-health and ring
admission factoring. The [magnitude timing note](magnitude_mask_timing.md) and
[SPEC timing note](spectrum_packetizer_timing.md) explain the unchanged arithmetic,
overflow and capture behavior behind the other shortened paths.

Relative to native-11, three warnings were added: a generated HPS dangling-pin
summary; a ring-query signal used only by the non-synthesis diagnostic; and a
narrow stored record offset. The offset is written only after a full-width
terminal comparison establishes that the next offset is below the admitted
record length. No new latch, multiple-driver or RAM-inference warning appeared.
The initial fitter process stopped with an internal access violation; its failure
record is preserved. After completing placement, the first native-12 timing gate
passed fabric timing but exposed three ADC output routes outside their 5 ns
allocation. The final I/O placement requests the existing three output registers
in I/O buffers. It uses 20,280 ALMs (63%), 29,115 registers, 55 M10K blocks and
36 DSP blocks. The fitted RAM summary identifies FFT/IFFT work memories as M10K
true-dual-port storage. All 209 pin comparisons and the required timing gate pass
at all four available operating corners. Worst fabric setup slack is +1.999 ns;
maximum ADC output data-path delay is 2.968 ns. Evaluation Mode still suppresses
the SOF, so the continuation remains incomplete for programming. The
[implementation results](../results/fpga_implementation.md) retain each checkpoint
and the sanitized evidence record.

The preceding native-11 synthesis completed with 1,738 warnings and no errors.
The mapped report contains no SPEC divider. All eight WAVE divide/modulo
instances and all five payload-validation modulo instances use 11-bit unsigned
numerators and 3-bit denominators. The only removed diagnostic is a generated
HPS dangling-pin summary; no new warning message appeared after source-line
renumbering. These mapped widths establish the intended hardware reduction;
post-fit reports must still establish timing.


The native09 and native10 Analysis & Synthesis logs each contain 1,739 warnings;
comparison of the complete warning messages found no additions or removals.
The records are `runs/quartus/windows/20260913-bram-{09,10}/quartus-map.log`.
These are diagnostic-message counts, including summary and child messages, rather
than counts of distinct design defects.

| Warning class | Messages | Source explanation |
| --- | ---: | --- |
| Twiddle initialization narrowing | 1,536 | Five hexadecimal digits occupy 20 bits; the coefficient ROM stores signed 17-bit words. The load retains the defined 17-bit coefficient representation. |
| Other assignment narrowing | 39 | Derived-width constants, bounded indexes and rate-accumulator remainders in project RTL, plus generated HPS controller/PHY widths. |
| Undriven nets or outputs | 28 | Twenty-one name synthesized write inputs (`data_a`, `waddr_a`, `we_a`) of initialized read-only ROMs; seven belong to generated HPS PLL/PHY code. |
| Unrecognized `async_reg` attribute | 21 | Quartus does not recognize this portable annotation. Source preservation and Intel-specific synchronizer attributes must be considered separately. |
| Assigned objects never read | 28 | Includes unused status expressions and array accesses made through packetizer functions; this diagnostic alone does not establish that payload storage was removed. |
| Permanently enabled I/O child nodes | 69 | All identify generated HPS `~synth` pin nodes, not the fabric codec I2C open-drain outputs. |
| Case completeness not checked | 5 | The CSR decoder's wide case expressions exceed the compiler's completeness-check limit. |
| Inputs without dependent outputs | 4 | Three spare board clocks and `SW[3]`, whose LINE-OUT monitor is disabled in this profile. |
| Other tool and summary messages | 9 | Include HPS implicit/unused model signals, connectivity summaries, inferred RAM read/write forwarding, and the constant `AUD_DACDAT` output with `AUDIO_LINEOUT_ALLOWED=0`. |

The source review followed the ROM declarations in
[twiddle_rom.sv](../../rtl/fft/twiddle_rom.sv), the bounded rate arithmetic in
[clock_reset_ctrl.sv](../../rtl/platform/de1soc/clock_reset_ctrl.sv) and
[adc_wrapper.sv](../../rtl/platform/de1soc/adc_wrapper.sv), and the selected
[board composition](../../rtl/platform/de1soc/de1_soc_trecap_top.sv).
No latch or multiple-driver diagnostic appeared, and this bounded review found no
additional source-owned board defect requiring a change. It does not suppress
these messages or establish numerical correctness, functional behavior,
metastability performance, or fitted timing closure. New or changed diagnostics
require a fresh review; the generated HPS clock-model boundary is documented below.

### HPS DDR assignments between synthesis and fitting

The generated HPS DDR pin script discovers the actual top-level pins from the
post-map netlist. Registering it as a QIP `TCL_FILE` does not execute it. We run
`scripts/quartus/capture_hps_ddr_assignments.tcl` through `quartus_sta` after map
and before fit in both build wrappers. The adapter sources the unchanged vendor
script, checks one interface with the expected 72 DDR I/O pins, 40 calibrated
input terminations and 44 calibrated output terminations, then writes a safely
quoted `hps_ddr_assignments.qsf` into that run's directory. A failed discovery
stops the build before fitting.

`TRECAP_HPS_DDR_QSF` selects this generated include for subsequent stages. The
adapter closes the Quartus project with `-dont_export_assignments` on success
and failure; the vendor script otherwise allows automatic export to rewrite the
maintained project QSF. The include is published atomically and retained with its
hash, stage logs, and the vendor `hps_sdram_p0_all_pins.txt` discovery dump.
Native runs record each exit in `build_manifest.json`; Bash
runs retain `quartus_stages.json` even when a stage fails and embed it in the
completed build manifest.

The scripted sequence is the authoritative board build. Opening the project or
reports in the GUI is supported, but a direct GUI full compile also requires the
matching generated DDR include and profile to be active. Analysis & Synthesis
alone does not establish DDR fitting, timing closure, or a programmable image.

### Fitted timing gate

Both build wrappers finish with `scripts/quartus/check_fitted_timing.tcl` through
`quartus_sta`. It loads the fitted netlist and the same profile/DDR includes,
then checks every operating condition returned by
`get_available_operating_conditions -all`. Setup, hold, recovery and removal
slack must be nonnegative wherever those paths exist. Absent path types are
reported explicitly; `CLOCK_50` and its setup/hold paths are required. Clock
coverage checks retain the explicit `no_clock` and `generated_clock` problem
counts and every detail row from `check_timing`. Only the reviewed hard-IP model
boundary below is excluded; a successful report command is not itself a pass.
The external `codec_bclk` and the observed audio PLL output clock are required.

The gate also measures the longest data paths using `get_path`, which excludes
clock-path credit. It applies the physical allocations from the board design:
20 ns for audio Gray pointers and payload crossings, 5 ns for ADC output routes,
10 ns for the ADC return input, and 20 ns for codec I2C input/output routes. RX endpoints are required;
TX checks are optional only when the included profile sets
`AUDIO_LINEOUT_ALLOWED=0` and the complete TX FIFO is absent. Every corner also
requires nonnegative `report_max_skew` slack and explicit Gray-pointer coverage
in its detailed report. Net-delay reports are retained separately.
A retained interface with missing endpoints or no connecting path fails the gate.
The five ADC/I2C output ports additionally require nonnegative shortest data
paths and retain both minimum and maximum detailed route reports. Their
full-path gate expresses a physical propagation budget;
there is no external CLOCK_50 capture edge assigned to these slow-control
outputs. See [the output data-path contract](physical_timing.md#slow-control-output-data-paths)
for the exact five-port disposition and Quartus 20.1 clock-latency rationale.

The ADC return's first synchronizer register samples continuously at 50 MHz;
the FSM consumes its final stage after the serial half-period. We therefore
exclude only the `ADC_DOUT` to `adc_dout_sync_q[0]` hold check: that input has no
deterministic phase relative to each fabric-clock edge. The setup placement
constraint, synchronizer interstage timing and consumer timing remain enabled.
This follows Intel's distinction between an asynchronous input and the timed
register-to-register settling path in its [Standard Edition synchronizer
guidance](https://www.intel.com/content/www/us/en/docs/programmable/683323/18-1/how-timing-constraints-affect-synchronizer.html).
The physical gate independently requires `get_path -min_path` delay at least
0 ns and longest `get_path` delay at most 10 ns, retaining both detailed
`report_path` reports for every corner. These queries include no clock-path
credit and remain active despite the hold-only exception. The serial return
budget is `5 + 2 + 100 + 10 + 60 = 177 ns` within the 200 ns half-period,
leaving 23 ns for the stated 20 ns guard and 3 ns residual margin; see
[physical timing](physical_timing.md).

The nominal 12.288 MHz MCLK has a 100 ppm acceptance allocation for PLL synthesis
quantization in `config/boards/physical_timing.json`; board oscillator tolerance
is separate. The native 20.1 clock ratio is `50 MHz × 519 / 64 / 33`, approximately
12.2869 MHz, with an 81.387 ns reported period. At the codec's 256:1 divider this
is approximately 47995.83 samples/s. The gate allows 1 ps separately for STA
period-query precision. This does not relax the 50 MHz fabric clock or I/O route
bounds.

Results are retained in `fitted-timing/fitted_timing.tsv` with full worst-slack
reports for each corner. The stage exits unsuccessfully on a violated bound or a
missing required path. A produced SOF alone does not establish that this gate
passed; consult the run's stage result and report. These tool results do not
establish functional correctness or measured board behavior.

### Hard-IP clock-model boundary

The native Quartus 20.1 fitted report contains 6995 `no_clock` entries. We retain
that raw count and classify each full node name. The count itself is not proof
of clock coverage. The gate requires the following separate, exact hierarchy
and count groups; any unrecognized node, duplicate row, missing detail, or count
change fails for review. Source-owned fabric registers have no exclusion.

| Reviewed model group | Native 20.1 count | Scope evidence |
| --- | ---: | --- |
| HPS FPGA interfaces | 1858 | `system_hps_0_fpga_interfaces.sv`:174,363,596 instantiate dedicated clocks/resets, lightweight bridge and FPGA-to-SDRAM primitives; each primitive has its own required count. |
| HPS peripheral border | 5128 | `system_hps_0_hps_io_border.sv` instantiates the dedicated HPS peripheral primitives; eight pseudo-register groups and sixteen exact Ethernet border nodes are bounded separately. |
| Dedicated HPS clock/input ports | 3 | Exact names `HPS_USB_CLKOUT`, `HPS_I2C1_SCLK`, `HPS_I2C2_SCLK`; the source-owned peripheral alias SDC covers their hard-I/O boundary. |
| DDR hard-PLL output aliases | 2 | `hps_sdram_pll.sv`:151–178 wires `afi_clk` and `pll_write_clk` from the hard PLL outputs; these are not RTL data registers. |
| DDR DQS postamble model nodes | 4 | One exact `POS_POSTAMBLE_DFF` node per DQS group; accepted only after the current fitted corner's vendor DDR analysis passes. |

The two PLL aliases additionally require the actual vendor clocks
`afi_clk_write_clk` and `pll_write_clk_dq_write_clk` at 2.5 ns. The generated
`hps_sdram_p0.sdc`:271–282 establishes these clocks from discovered memory pins.
We do not create replacement clocks on the generic report's model nodes.

The postamble nodes belong to the calibrated `cyclonev_dqs_delay_chain`
primitive in `altdq_dqs2_acv_connect_to_hard_phy_cyclonev.sv`:1043–1060.
They need dedicated DDR analysis: the generic SDC's `POSTAMBLE_DFF` comment is
not sufficient evidence to discard a `POS_POSTAMBLE_DFF` warning.
`hps_sdram_p0_report_timing_core.tcl`:1733–1937 computes postamble margins,
including actual DQS-to-postamble paths, calibration, jitter and device/memory
variation; `hps_sdram_p0_report_timing.tcl`:365 invokes that calculation.
The gate sources the unedited report at each fitted corner, requires one
interface with four DQS groups and valid model assumptions, and requires every
applicable DDR margin to be nonnegative. It preserves explicitly absent
analytic sides, such as bus-turnaround hold, and retains each vendor CSV with
the corresponding corner's gate report.

The native09 audit completed all four available 1100 mV slow/fast, 0/85 °C
corners with positive applicable DDR margins. The minimum postamble setup and
hold margins were both 0.475479375 ns; read-capture hold was 0.185625347143 ns.
The project-entry QSF SHA-256 was unchanged. These results apply to that fitted
database; each new build reruns the analysis. They do not resolve the separately
reported fabric timing failures or establish functional board behavior.

The reviewed generated report SHA-256 values are
`ae8cffba0b736d4b5c4288bb1647e030e08e08a1d9e2bfb631503a583d54359f`
(`hps_sdram_p0_report_timing.tcl`) and
`659ba5de15e194b67a814ae73fad4c27027640aed5d7c7ec162398c08b543e09`
(`hps_sdram_p0_report_timing_core.tcl`). Generated source line references above
are relative to `platform/de1soc/qsys/system/synthesis/submodules/`.

### Volatile programming from Windows

Pass the exact built image to the native programming entry point:

```powershell
.\scripts\quartus\program_sof.ps1 `
    -QuartusRoot $env:QUARTUS_ROOTDIR `
    -Sof platform/de1soc/quartus/output_files/trecap_de1soc.sof `
    -BuildManifest 'runs/quartus/windows/<run-id>/build_manifest.json' `
    -Cable 'DE-SoC [USB-1]' `
    -DeviceIndex 2
```

The matching build manifest must record a completed build, passed fitted-pin
and timing gates, their matching report hashes, and the same freshly produced
nonempty SOF hash and size. Both build wrappers
run the fitted-pin gate after fitting and preserve any old SOF before building.
The script logs a fresh `jtagconfig` inventory and requires exactly one matching
cable with the two-device chain: HPS ID `4BA00477`, followed by FPGA ID `02D120DD`
at index 2. It hashes the explicit SOF, checks that the file remains unchanged
during inventory, then invokes `quartus_pgm -m JTAG -c <selected-cable>` with the
single operation `p;<explicit-sof>@2`. The SOF parameter is required; no image is
selected by modification time. Only volatile FPGA programming is exposed.

Logs, observed device identities, SOF hash, command arguments, and exit codes are
stored under `runs/quartus/program/windows/` by default, or an empty directory
selected with `-RunDirectory`. A cable/chain mismatch or tool failure stops the
operation and is recorded in `program_manifest.json`. The programming result is
separate from subsequent BRAM replay and hardware behavior checks.

With the Quartus tools on `PATH`, the Bash helper requires the same explicit
image and matching build manifest:

```bash
scripts/quartus/program_sof.sh \
  --sof platform/de1soc/quartus/output_files/trecap_de1soc.sof \
  --build-manifest 'runs/quartus/<run-id>/build_manifest.json' \
  --cable 'DE-SoC [USB-1]' --device-index 2 --list-cables
```

Its `--sof` and `--build-manifest` arguments are required, and it accepts only
volatile JTAG operation `p`. Select a cable name from the attached inventory.

### Quartus 20.1.1 compatibility decisions

The native 20.1.1 Build 720 HPS API exposed 1822 parameter names. Our source-owned
preset has 520 rows: 476 writable values and 44 values captured from tool
readback. The remaining 1302 names are vendor internal/derived parameters.
`platform/de1soc/qsys/platform_designer.tcl` requires the entire preset partition
but does not treat extra internal names as new writable configuration.

Setting an unchanged HPS parameter still triggers expensive vendor callbacks.
We compare semantic values before writing, then read back every required value,
including unchanged defaults, after instance/system validation. Skipping a
redundant write does not skip the corresponding readback requirement.

Validation returns severity-prefixed messages, including `Debug:` and `Info:`.
Raw messages are retained beside the HPS readback file. HPS instance validation
accepts three reviewed optional-clock warning forms: configuration/user0 requested
100 MHz versus 97.368421 MHz, QSPI requested 400 MHz versus 370 MHz, and their
summary warning. These warnings do not bypass parameter readback checks or change
the 50 MHz fabric-clock contract. The generated IRQ mappers have zero receivers
and drive a constant `32'b0`; their unused clock/reset warnings are benign for
this zero-input configuration only. Adding an interrupt receiver requires revisiting
those connections. These exceptions do not permit arbitrary warnings or errors.

Quartus saves a normalized `system.qsys` with the literal name `$${FILENAME}` and
omits our bootstrap metadata. The source checker accepts this vendor representation
for that file while retaining the source-owned platform and address contracts.
The bundled Java Tcl interpreter also requires an existing file for append mode,
so validation logging creates the file before appending. Its `file rename -force`
cannot reliably replace an existing Windows target; saving the normalized system
uses a Python `os.replace` fallback on the same filesystem.

We tie the required HPS cold/debug/warm reset requests inactive, hold STM hardware
events at zero, and tie the DDR bridge's debug-access input low. The source-owned
CSR bridge preserves delayed write-error responses through `writeresponsevalid`.
Its IP catalog path is `<component-dir>/*,$`; reloading the catalog inside Tcl
would discard that command-line search path.

The native integration run generated 33 modules and 90 files. The generated
SOPCINFO address check and the 99-port wrapper interface check passed. The staged
build uses the default `config/profiles/de1soc_bram_replay.json` profile and
`artifacts/test_vectors/zero_Ns4096_thr0/x_in.memh`: 4096 zero-valued input samples
at 48 ksample/s. These are Platform Designer generation and integration results;
Quartus compilation and FPGA programming outcomes are recorded separately in
their run manifests.

### Reviewed HPS timing messages

The generated `system_hps_0_hps_io_border.sdc` uses exported `hps_io_hps_io_*`
port names. Our board wrapper maps those to `HPS_*`, so the original global SDC
entries do not match the board's ports. We apply the same 84 directional cuts
through [hps_peripheral_timing.sdc](../../constraints/de1soc/hps_peripheral_timing.sdc):
40 from-pin and 44 to-pin exceptions across 55 scalar hard-peripheral pins.
Every endpoint must resolve exactly once. These explicit aliases exclude HPS
DDR, FPGA audio/ADC/I2C ports, and the CSR/DDR fabric interfaces. The unchanged
vendor entries can still report unmatched exported names; this does not permit
unrelated unmatched constraints.

The alias source is generated SDC lines 1–84, mapped by
[platform_designer_wrapper.sv](../../rtl/platform/de1soc/platform_designer_wrapper.sv)
lines 195–249. The inspected source identities are:

| Input | SHA-256 |
| --- | --- |
| Generated `system_hps_0_hps_io_border.sdc` | `208f249ea4a140fcecc8eb60a33d2ffb4c3f679f9c6a2acb19d0c250d2e2397a` |
| Wrapper containing the board-name mapping | `3123d253447c91903e41c646049a3f4c837ff871f3ca493b3019382d00934c4e` |
| Generated `hps_sdram_p0.sdc` | `f9f415061c150ed6959b73a06e0434c136e27f9f29d156dc408991ed61961767` |

The generated `hps_sdram_p0.sdc` deliberately sets DQS input/output clock
uncertainty to zero at lines 345–346, 360–361 and 369–370: its adjacent comments
state that the path-jitter terms already account for uncertainty. Lines 79–86
query jitter, lines 103–120 include jitter, board skew, signal-integrity and
switching-noise terms in data input/output budgets, and lines 123–126 include PLL
jitter and phase error in address/command budgets. We preserve that vendor model;
adding the generic recommended uncertainty would count parts of the budget twice.
This explanation applies to those documented DDR transfers and does not justify
zeroing our fabric or peripheral uncertainty constraints.

### Quartus source compatibility

We use a literal project-relative source path for the QSF entry because
`info script` resolves differently during `project_open`. The production QSF
defines `SYNTHESIS=1` to exclude the existing simulator assertions from synthesis.
Across 44 module/interface headers, package names are qualified in the header
and imports are placed inside the body for Quartus 20.1 compatibility.

Memory-file path parameters use untyped packed Verilog values because this
Quartus version rejects SystemVerilog `string` parameters in `$readmemh`.
Unary negation around cast expressions is explicitly parenthesized. FFT/IFFT
RAMs use a local `no_rw_check` attribute for the reason recorded in the
[transform microarchitecture](transform_microarchitecture.md). Native-12's
Fitter RAM Summary confirms M10K true-dual-port inference for both FFT and IFFT
work memories; the complete fitted design uses 55 M10K blocks. This establishes
the implemented storage mapping for that build. The final native-12 fitted timing
gate also passes; neither result establishes functional correctness.

## Runtime sequence

BRAM replay is the default profile. Bring up the direct Ethernet/HPS path with STATUS, then waveform, metrics, and one spectrum format. Configure the DDR ring and initial consumer state before enabling the writer. Use the defined reset/configure/enable lifecycle and visible command results.

LINE-IN and ADC require their explicit profiles and peripheral setup. They are not selected merely by installing a Python dependency or editing a runtime sample-rate label. Follow the dedicated [LINE-IN](../bringup/audio_linein_bringup.md) and [ADC](../bringup/adc_bringup.md) guides.

## Source maintenance

`python scripts/repo_hygiene.py` performs repository hygiene checks described in the [maintenance guide](../repository_maintenance.md). The GitHub source workflow is limited to source hygiene, production RTL elaboration and host compilation. Hardware verification, simulation, synthesis signoff, and board measurements remain separate work.

Keep generated build outputs under ignored directories. Record the toolchain, profile, and source/configuration identity when reporting a build. Report a build failure directly rather than treating a missing tool or skipped step as success.

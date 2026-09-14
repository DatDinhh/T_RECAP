# Quartus build and FPGA programming

We build the physical DE1-SoC image from the maintained RTL, shared contracts and Platform Designer source. The default BRAM replay profile targets the Cyclone V `5CSEMA5F31C6` at a 50 MHz fabric clock. The build records its profile, generated platform, fitted pins, timing results and image hash so a programming run can identify the exact image it used.

The [integrated specification](../specs/README.md) defines the interfaces. The [build guide](../architecture/build_order.md) gives the complete command sequence and native-tool compatibility notes. Functional verification and physical source characterization remain separate project work.

## Current implementation evidence

Quartus Standard 20.1.1 Build 720 has generated the real HPS system and fitted the BRAM profile. The current native-12 I/O placement uses 20,280 of 32,070 ALMs, 55 of 397 memory blocks and 36 of 87 DSP blocks. All 209 board-top pins match the source contracts, and the required fitted timing gate passes at all four available operating corners. See the [implementation results](../results/fpga_implementation.md) for resources, per-corner margins and source identities.

The installed Standard Edition remains in Evaluation Mode: warning 292011 prevents `.sof` generation even though Assembler returns zero. The final continuation is therefore recorded as `incomplete_no_sof`, with passing pin and timing results. No FPGA programming or board execution has occurred.

The connected board was visible as `DE-SoC [USB-1]`, with HPS ID `4BA00477` in position 1 and FPGA ID `02D120DD` in position 2. This inventory establishes cable visibility only. The programming helper checks the current chain again before selecting the FPGA.

## Tool and source ownership

The native flow uses Quartus Standard 20.1.x, the matching Cyclone V device package and Python with `scripts/requirements-source.txt`. The exercised version is 20.1.1 Build 720. Installation paths are arguments or local environment settings, never repository constants.

A valid license is required for the installed Standard Edition to create the image. A separate [Quartus Prime Lite 20.1.1 installation](https://www.altera.com/downloads/fpga-development-tools/quartus-prime-lite-edition-design-software-version-20-1-1-windows) is a license-free Cyclone V option; it is not the toolchain used for the recorded native results. Downloading and selecting another edition does not replace a new build and its reports.

| Source | Responsibility |
| --- | --- |
| `config/profiles/` | Paired FPGA parameters and HPS runtime configuration |
| `platform/de1soc/qsys/platform_designer.tcl` | HPS platform construction and pinned configuration |
| `platform/de1soc/qsys/system.qsys` | Normalized Platform Designer source |
| `platform/de1soc/quartus/trecap_de1soc.qpf` | Physical board project |
| `constraints/de1soc/de1soc.qsf` | Device, top, source/QIP/SDC includes |
| `constraints/de1soc/pin_assignments.tcl` | FPGA board pins and I/O settings |
| `constraints/de1soc/hps_peripheral_io.tcl` | Dedicated HPS peripheral I/O standards |
| `constraints/de1soc/*.sdc` | Fabric, clock/reset, peripheral and CDC timing |
| `filelists/quartus_de1soc.qsf.inc` | Generated RTL file list |

Generated vendor HDL, databases, reports and images belong in ignored build/run directories. We retain vendor HDL unchanged. The generated HPS DDR assignment script owns its electrical/OCT settings; the source pin ledger independently checks the fitted package locations.

## Build on Windows

From the repository root, use the actual local installation path:

```powershell
.\scripts\quartus\build_de1soc.ps1 `
    -QuartusRoot '<Quartus installation>/quartus' `
    -Python python `
    -Profile config/profiles/de1soc_bram_replay.json `
    -RunDirectory runs/quartus/windows/<run-id>
```

The run directory must be empty. The wrapper checks generated source contracts, resolves the profile, constructs and generates the platform, checks its actual exports/address map, then runs:

1. Analysis and Synthesis.
2. Generated HPS DDR electrical-assignment capture from the mapped netlist.
3. Fitter and the 209-pin comparison.
4. Assembler and explicit fresh-image detection.
5. TimeQuest and the fitted timing gate at every available corner.

`-GenerateOnly` stops after platform generation and interface checks. `-SkipPlatformGenerate` reuses existing normalized Qsys and generated HDL, but still captures fresh HPS readbacks and checks the generated interface/address contracts. These two switches are mutually exclusive.

A previous `.sof` is preserved in the new run before compilation so an old image cannot appear to be a successful new assembly. If assembly emits no nonempty image, the wrapper continues timing diagnostics and ultimately reports failure. A completed build requires a fresh image, matching pins and passing timing; an assembler exit code alone is insufficient.

For Bash, use `scripts/quartus/build_de1soc.sh` and the environment/arguments documented in the [build guide](../architecture/build_order.md). The root Makefile wraps the staged source and board targets.

## Timing evidence

The fitted gate requires the actual 50 MHz fabric clock, the derived audio PLL clock, codec BCLK, setup/hold/recovery/removal margins, bounded ADC/I2C routes and audio FIFO crossings. It also retains the raw clock-coverage report. Reviewed hard-HPS model nodes are identified by exact primitive groups; any unrecognized clockless fabric node remains a failure.

DDR has an additional generated microtiming report. Its current-corner margins and assumptions must pass before the four calibrated postamble model nodes can be classified. A broad HPS timing waiver is not used. The [physical timing contract](../architecture/physical_timing.md) records each allocation, pin source and exception; the [build guide](../architecture/build_order.md) records the vendor-source evidence.

These are implementation checks. Positive timing margins do not establish arithmetic correctness, analog performance or sustained HPS/DDR/Ethernet operation.

## Program the completed image

Use the explicit image and the successful manifest from the same build:

```powershell
.\scripts\quartus\program_sof.ps1 `
    -QuartusRoot '<Quartus installation>/quartus' `
    -Sof platform/de1soc/quartus/output_files/trecap_de1soc.sof `
    -BuildManifest runs/quartus/windows/<run-id>/build_manifest.json `
    -Cable 'DE-SoC [USB-1]' `
    -DeviceIndex 2
```

The helper checks the selected image against the completed build and its pin/timing reports, inventories the cable, and programs device 2 through JTAG. It records the image hash, inventory, command and outcome in a separate run directory. This loads volatile FPGA configuration; it does not write flash or prepare an SD card.

Quartus GUI can open the same `.qpf`, but the authoritative build uses the resolved profile and captured DDR-assignment includes recorded in its manifest. A separate GUI session must load those same settings. Its presence on screen is not evidence that compilation or programming completed.

## HPS and system operation

The image and HPS runtime must agree on the CSR ABI, reserved-DDR geometry, source profile and ownership lifecycle. The checked-in Linux recipe still needs the matched kernel, DTB and module built and deployed. The driver owns noncached ring access and GPIO48 codec-mux permission; FPGA programming alone does not establish those services.

After the matched platform is deployed, follow the [HPS bring-up guide](hps_ethernet_bringup.md), then the [dashboard guide](pc_dashboard_bringup.md). BRAM is the baseline source; LINE-IN and optional ADC each have their own physical setup and operation requirements. The separate BRAM/source verification procedures are not executed by the build or programming helpers.

## Run records

Windows builds retain `build_manifest.json`, stage logs, generated-platform/profile records, `fitted_pins.json` and `fitted-timing/fitted_timing.tsv` under their chosen run directory. Failed builds retain the available diagnostics and the failing stage. Successful builds additionally identify the fresh `.sof` by path, size and SHA-256. Programming uses another run directory with its own manifest.

Keep generated files and personal installation paths out of Git. Publish selected, sanitized implementation results with a release when they are available; do not present source compilation, a successful fit or cable detection as a completed system demonstration.

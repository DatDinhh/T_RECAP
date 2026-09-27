# Quartus Lite build and DE1-SoC configuration - 15 September 2026

We rebuilt the current BRAM replay profile with **Quartus Prime Lite 20.1.1 Build 720** and successfully configured the DE1-SoC FPGA through USB-Blaster II. The programmer reported **one device configured, zero errors and zero warnings**. This records FPGA configuration; end-to-end BRAM, DDR, HPS and dashboard operation still needs hardware acceptance.

The build includes the RTL corrections from the [initial verification campaign](verification_baseline_20260915.md), followed by the [finite-boundary campaign](verification_boundaries_20260915.md). The 173 files in the preflight source inventory were unchanged through compilation. No production RTL or constraints were changed for this deployment. The earlier [Standard Edition result](fpga_implementation.md) remains a historical checkpoint; its evaluation-mode image restriction did not occur in this Lite build.

## Implemented image

| Item | Recorded result |
| --- | --- |
| Device | Cyclone V 5CSEMA5F31C6 |
| Profile | `config/profiles/de1soc_bram_replay.json` |
| ALMs | 21,220 / 32,070 (66%) |
| Registers | 29,452 |
| RAM blocks | 55 / 397 |
| Block-memory bits | 368,256 / 4,065,280 |
| DSP blocks | 36 / 87 |
| Fitted board pins | 209 comparisons, PASS |
| Image size | 7,365,337 bytes |
| JTAG target | `DE-SoC [USB-1]`, FPGA at device 2, ID `02D120DD` |
| Programming completed | `2026-09-15T23:27:33.6224543Z` |

The image SHA-256 is `b14d7b38f422d0e82c0c22d76e3b298c7602d38e075efdd8148d4f2890d1a9fa`. The archived image and the programmed image have this same identity. Programming changed volatile FPGA configuration only; no flash or SD card was written. After power loss, the image must be loaded again unless a separate boot configuration is prepared.

Resource differences from older source checkpoints are not a controlled energy or performance comparison.

## Fitted timing

The complete project gate passed all four operating conditions with **276 result rows and zero failed rows**. The following values are the gate's explicit CLOCK_50-to-CLOCK_50 queries:

| Operating condition | Setup slack | Hold slack |
| --- | ---: | ---: |
| Slow 1100mV 85C Model | +2.391 ns | +0.037 ns |
| Slow 1100mV 0C Model | +2.333 ns | +0.002 ns |
| Fast 1100mV 0C Model | +10.794 ns | +0.050 ns |
| Fast 1100mV 85C Model | +9.786 ns | +0.072 ns |

The smallest hold margin is **0.002 ns**. This is a positive modeled result with little margin; it does not establish margin outside the analyzed conditions. Required global slack, applicable generated DDR microtiming, clock coverage, physical I/O routes and CDC route/skew checks passed. The largest ADC output route is 2.968 ns against a 5 ns allocation; the largest ADC input route is 2.134 ns against 10 ns.

Four audio-TX route checks per corner are absent because this profile disables lineout. DDR bus-turnaround hold is inapplicable in the vendor model. Hard-IP clock classifications and external assumptions remain those of the [physical timing contract](../architecture/physical_timing.md). The timing gate is not a functional CDC or board qualification test.

## Warning review

Synthesis completed with 1,741 warnings and default TimeQuest with 291 warnings; the project timing script reported 1,530 warnings across its repeated analysis. The synthesis and default-TimeQuest warning sets match the reviewed native-12 checkpoint. Twiddle-ROM width warnings discard zero upper padding. The 23 ignored fitted assignments match historical vendor DDR templates; the board pin comparison and ADC I/O register packing passed. The Lite LogicLock notice does not discard an active floorplan: this design requests no reserved LogicLock region.

Generated DDR uncertainty notices follow the vendor timing budget and do not justify replacing it with generic clock uncertainty. Assembler warning **11713** requires a matching HPS preloader/SPL from this generated handoff. The FPGA image alone does not configure a compatible HPS boot chain.

## Remaining board bring-up

No LED state, HPS boot log, completed replay, DDR record or UDP capture was observed in this run. The full-board reset depends on HPS releasing `h2f_reset_n`, and KEY1 replay admission depends on a configured DDR ring and enabled transport. Follow the [post-program observations](../bringup/quartus_programming.md#first-observations-after-programming) before starting replay.

The next step is to identify the installed microSD/Linux image through the HPS UART, then deploy a matching preloader/SPL, kernel, DTB, platform driver and ARM transport application. The current host-built streamer is an x86-64 executable and cannot serve as the ARM HPS application. The generated handoff is archived with this build. No SD image was replaced during FPGA programming.

For the default Ns=4096 replay, the expected acceptance observations include 33 completed frames, 4,224 active core samples and 4,608 output samples including the tail, followed by the required STATUS commit to DDR. These are expected values, not measurements from this deployment. Numerical full-system verification and electrical energy measurements remain open.

## Evidence

The [public result JSON](de1soc_lite_bram_20260915.json) records image, report and manifest hashes with repository-relative paths. Raw logs, generated handoff, source snapshot and binary image stay in ignored local run directories:

- Build: `runs/quartus/windows/20260915-lite-bram-01/`.
- Archived image: `runs/quartus/windows/20260915-lite-bram-01/image/trecap_de1soc.sof`.
- Fitted reports: the build's `implementation-reports/` and `fitted-timing/` directories.
- HPS handoff: the build's `hps_isw_handoff/system_hps_0/` directory.
- Source provenance: the build's `source_integrity.json` and `checked-source-snapshot.zip`; the preflight inventory covers 173 selected build-source files, not every repository file.
- Programming: `runs/quartus/program/windows/20260915-lite-bram-01/`.

The successful Assembler also emitted a generated HPS handoff containing a binary `.hiof`. The source-hygiene check initially flagged this previously unlisted build directory. The exact `platform/de1soc/quartus/hps_isw_handoff/` path is now excluded by both `.gitignore` and the source-hygiene walker; its contents are retained and hashed in the build archive. This repository-maintenance change does not alter the programmed image.

The guarded programming script checked the completed build, fresh image identity, 209-pin result, passing timing report hashes and exact HPS/FPGA JTAG chain before configuration.

The final source-hygiene check inspected 718 files with zero findings. It checks repository hygiene and links, not functional behavior.

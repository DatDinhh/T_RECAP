# FPGA implementation results

We have completed full-board placement and routing for the BRAM replay profile on the Cyclone V **5CSEMA5F31C6**, using Quartus Prime Standard **20.1.1 Build 720** and its final timing models. The latest fit, **native12 / fitter-io-02**, uses **20,280 of 32,070 ALMs (63%)**. All 209 pins passed the post-fit board comparison. The complete fitted timing gate passed all four operating conditions, including the 50 MHz fabric and ADC output-route bounds. Assembler produced no `.sof` in Evaluation Mode, so the run remains incomplete for programming. These fitted results establish the implemented pin and timing contracts for this profile; they do not establish functional correctness or physical board operation. The [public machine-readable result](de1soc_bram_native12.json) records the values and provenance hashes.

Functional verification and hardware power/energy measurements remain pending. Resource counts and timing slack do not quantify energy savings; no measured savings are claimed.

## Fitted resources

The native09, native10, native11 and native12 retry01 rows are historical checkpoints. Native12 IO02 is the latest fitted implementation. All runs use `config/profiles/de1soc_bram_replay.json`; source and constraint changes mean the rows are not controlled performance experiments.

| Checkpoint | ALMs / 32,070 | Registers | RAM blocks / 397 | Block-memory bits / 4,065,280 | DSP blocks / 87 | Top-level pins |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| native09, historical | 24,831 (77%) | — | 55 (14%) | — | 32 (37%) | 209 |
| native10, historical | 24,711 (77%) | 30,480 | 55 (14%) | 368,256 (9%) | 32 (37%) | 209 |
| native11, historical | 24,100 (75%) | 30,440 | 55 (14%) | 368,256 (9%) | 32 (37%) | 209 |
| native12 retry01, historical | 20,273 (63%) | 29,108 | 55 (14%) | 368,256 (9%) | 36 (41%) | 209 |
| **native12 IO02, latest fit** | **20,280 (63%)** | **29,115** | **55 (14%)** | **368,256 (9%)** | **36 (41%)** | **209** |

Native09 values are the resource counts recorded at that checkpoint; its detailed fitted summary was not archived. A dash marks an unrecorded value. We do not reconstruct it from a later build. Native10/11 values come from their archived `fit.summary` files; native12 values come from the archived fitted summaries for each placement attempt. Resource use is not a power or throughput measurement.

## Timing and image status

The current **native12 / fitter-io-02 / postfit-02** gate reports **PASS** in all four operating conditions. The earlier native11 and retry01 placements remain historical comparisons:

| Operating condition | Native11 CLOCK_50 setup, historical | Native12 retry01 CLOCK_50 setup, historical | **Native12 IO02 CLOCK_50 setup** |
| --- | ---: | ---: | ---: |
| Slow, 1100 mV, 85 C | -8.893 ns | +2.841 ns | **+1.999 ns** |
| Slow, 1100 mV, 0 C | -9.247 ns | +2.963 ns | **+2.279 ns** |
| Fast, 1100 mV, 0 C | +4.928 ns | +10.836 ns | **+10.386 ns** |
| Fast, 1100 mV, 85 C | +3.918 ns | +9.770 ns | **+9.320 ns** |

Retry01 failed five ADC output-route checks across its two slow corners. IO02 requested fast output-register packing for the three affected outputs. The 91 mapped RTL/filelist identities and the **5 ns** output allocation were unchanged. The worst register-output-to-port delay for each output across all four corners is:

| Output | Retry01 worst delay, historical | **IO02 worst delay** | Required maximum |
| --- | ---: | ---: | ---: |
| `ADC_SCLK` | 5.289 ns, FAIL | **2.968 ns, PASS** | 5 ns |
| `ADC_CS_N` | 5.594 ns, FAIL | **2.938 ns, PASS** | 5 ns |
| `ADC_DIN` | 5.608 ns, FAIL | **2.929 ns, PASS** | 5 ns |

The IO02 gate also passed required global setup, hold, recovery/removal, all other physical routes, CDC skew, classified clock coverage and generated HPS DDR microtiming at all four corners. All 209 fitted pins passed the location/I/O-standard comparison. These results use the external assumptions and reviewed hard-IP model classifications in the [physical timing contract](../architecture/physical_timing.md); physical qualification remains separate.

Native12's initial Fitter process crashed during placement preparation. Retry01 completed after topology-inspection queries were moved from the fitting SDC into the post-fit timing gate. IO02 then completed the ADC output placement change. The original failed manifest and both placement/recovery records remain available.

The current Assembler exited **0** but emitted warning **292011** and no fresh `.sof` because Standard Edition was in Evaluation Mode. The continuation therefore records **`incomplete_no_sof`**, with `full_build_completed: false`, despite passing pins and timing. No programmable image, FPGA programming or board execution is claimed. A suitable licensed build or a separately installed supported Lite toolchain must produce a fresh image with its own passing reports before programming.

## Evidence and scope

Raw tool outputs remain under ignored `runs/` directories and the ignored Quartus `output_files/` directory. They are local build artifacts, not files shipped in a clean source checkout. The following paths are relative to the repository root and identify the records used for this summary:

| Evidence | Repository-relative path |
| --- | --- |
| Native09 fit log and original manifest | `runs/quartus/windows/20260913-bram-09/quartus-fit.log`, `runs/quartus/windows/20260913-bram-09/build_manifest.json` |
| Native10 fitted resources | `runs/quartus/windows/20260913-bram-10/implementation-reports/trecap_de1soc.fit.summary` |
| Native11 fitted resources | `runs/quartus/windows/20260913-bram-11/implementation-reports/trecap_de1soc.fit.summary` |
| Native11 timing and pin results | `runs/quartus/windows/20260913-bram-11/fitted-timing/fitted_timing.tsv`, `runs/quartus/windows/20260913-bram-11/fitted_pins.json` |
| Native12 retry01 successful fit | `runs/quartus/windows/20260913-bram-12/fitter-retry-01/manifest.json`, `runs/quartus/windows/20260913-bram-12/fitter-retry-01/quartus-fit.log` |
| Native12 retry01 pin result | `runs/quartus/windows/20260913-bram-12/fitter-retry-01/postfit-recovery-02/fitted_pins.json` |
| Native12 retry01 fitted resources | `runs/quartus/windows/20260913-bram-12/fitter-retry-01/postfit-recovery-02/implementation-reports/trecap_de1soc.fit.summary` |
| Native12 retry01 timing and recovery result | `runs/quartus/windows/20260913-bram-12/fitter-retry-01/postfit-recovery-02/fitted-timing/fitted_timing.tsv`, `runs/quartus/windows/20260913-bram-12/fitter-retry-01/postfit-recovery-02/recovery_manifest.json` |
| Native12 IO02 successful fit | `runs/quartus/windows/20260913-bram-12/fitter-io-02/manifest.json`, `runs/quartus/windows/20260913-bram-12/fitter-io-02/quartus-fit.log` |
| Native12 IO02 archived fitted resources | `runs/quartus/windows/20260913-bram-12/fitter-io-02/postfit-02/implementation-reports/trecap_de1soc.fit.summary` |
| Native12 IO02 pin result | `runs/quartus/windows/20260913-bram-12/fitter-io-02/postfit-02/fitted_pins.json` |
| Native12 IO02 timing and final continuation | `runs/quartus/windows/20260913-bram-12/fitter-io-02/postfit-02/fitted-timing/fitted_timing.tsv`, `runs/quartus/windows/20260913-bram-12/fitter-io-02/postfit-02/recovery_manifest.json` |
| Native12 IO02 image limitation | `runs/quartus/windows/20260913-bram-12/fitter-io-02/postfit-02/quartus-asm.log` |

For example, from the repository root, `Get-Content -LiteralPath 'platform/de1soc/quartus/output_files/trecap_de1soc.fit.summary'` reads the current local fit summary in PowerShell. The shared output directory changes on later builds; retained run reports and their manifest hashes identify a particular checkpoint.

Source elaboration and host compilation check source acceptance. Synthesis and fitting establish a mapped, placed and routed implementation. STA and the fitted-pin gate check the timing and pin contracts represented in their inputs. None of these results includes numerical equivalence, RTL simulation, a functional regression, physical board qualification, or HPS/Linux deployment. No new functional verification was run for this implementation work.

The [build flow](../architecture/build_order.md), [current architecture status](../architecture/architecture_implementation.md), and [physical timing design](../architecture/physical_timing.md) define the surrounding contracts and remaining work.

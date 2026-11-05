# Baseline PDF page 076

Historical Part III, repository architecture. Printed page 63. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=76).

[Previous](../../baseline/page-075.md) | [Index](../../README.md) | [Next](../../baseline/page-077.md)

```text
        | HPS-FPGA bridge + HPS DDR
        v
FPGA HPS bridge layer
  CSR bank + pointer control + DDR record builder + DDR ring writer
        ^
        | formatted record stream
        v
FPGA telemetry layer
  packet scheduler + WAVE/SPEC/METRICS/STATUS packetizers + packet FIFO
        ^
        | non-stalling core taps
        v
FPGA core layer
  source -> STFT/FFT -> mask -> IFFT/WOLA -> metrics
        ^
        | samples
        v
BRAM replay / LINE-IN audio / ADC / diagnostics
```

## 34 Repository Layout

### 34.1 Normative top-level tree

The initial Phase 2 implementation repository shall use the directory tree below. Verification-specific directories are intentionally absent.

```text
T_RECAP_Phase2/
  README.md
  Makefile
  .gitignore

  docs/
    specs/
    architecture/
    bringup/
    deprecation/

  spec/
    generated/
      core_config.json
      csr_map.json
      packet_layouts.json
      interface_types.json
      gen_manifest.json

  config/
    profiles/
      baseline_core.json
      sim_core_only.json
      de1soc_bram_replay.json
      de1soc_linein_demo.json
```

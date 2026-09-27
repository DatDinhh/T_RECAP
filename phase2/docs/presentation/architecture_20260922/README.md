# T-RECAP architecture presentation figures

Team #2

## Presentation order
For a short TA discussion, use 01 (system ownership), 02 (datapath), 06 (handshake) and 09 (fitted resources). Use 07 for numerical comparison and 10 for timing.

## Evidence boundaries
- Structure diagrams follow checked-in RTL and architecture contracts.
- Butterfly and deadline charts show source-derived schedules or analytical budgets.
- Waveforms come from fresh ModelSim finite-core simulation.
- Resource and timing charts use the archived 15 September 2026 Quartus Lite build.
- The multitone simulation differs from the deployed default 4096-zero-sample, STATUS-only board profile.
- End-to-end HPS/DDR/dashboard operation, CPU/FPGA speedup and electrical energy remain unmeasured.

## Files
- figures/: 2880 x 1620 PNGs and editable SVGs.
- T_RECAP_Architecture_Figures.pdf: ten presentation pages.
- data/: original VCD waveforms, selected CSV events, reference output and fitted-result snapshot.
- provenance.json: figure-to-source mapping and SHA-256 identities.
- plot_architecture_presentation.py: plot builder.

## Figure notes

### 01_system_ownership. System ownership
The physical board instantiates one core inside source/core integration. The HPS forwards committed telemetry records and writes controls. Observers have no ready return path into the DSP core. End-to-end HPS/DDR/dashboard board acceptance remains open.

Sources: rtl/platform/de1soc/de1_soc_trecap_top.sv, docs/architecture/architecture_implementation.md

### 02_fixed_point_datapath. Fixed-point datapath
Separate iterative FFT and IFFT engines use the frozen coefficient tables. The core captures THR2 at frame admission. WOLA uses the real IFFT component. Delayed-input history supports error calculation. The offline C++ reference model is not a physical FPGA block.

Sources: rtl/core/trecap_core_top.sv, rtl/include/generated/trecap_core_pkg.sv, spec/generated/width_config.json

### 03_butterfly_schedule. Registered butterfly schedule
The registered transaction separates multiplication, complex sum, quantization, addition and writeback. Counts include first and last accepted edges. Local transform service is 7936 clocks only under the stated conditions. It is not an end-to-end latency measurement.

Sources: docs/architecture/transform_microarchitecture.md, rtl/fft/trecap_fft_stage.sv

### 04_storage_geometry. Storage geometry
Large stores use synchronous embedded-memory schedules. Both history stores include sample indices. Selected logical capacities do not include every memory or register and are distinct from fitted device resource totals.

Sources: docs/architecture/storage_schedule.md, docs/architecture/transform_microarchitecture.md

### 05_observed_frame_timing. Observed frame timing
Actual handshakes bound the first frame's interface spans. Engine-state traces identify 7168 compute clocks for each transform. Interface spans include gaps. The burst-driven testbench differs from periodic board sampling, so this is not board latency.

Sources: runs/architecture_presentation_20260922/multitone/static/capture/frame_timing.csv

### 06_output_handshake. Output handshake
Gold marks valid=1 and ready=0. Output index and data remain held until acceptance. The testbench injects stalls at the reusable core output. Physical board telemetry taps cannot drive core ready.

Sources: runs/architecture_presentation_20260922/multitone/stalled/capture/cycle_trace.csv

### 07_rtl_reference_waveforms. RTL and reference waveforms
Every output matches the qualified reference for this multitone case in both static and stalled simulations. The lower graph shows scheduling separately from numerical sample order. It is not a CPU/FPGA speed comparison.

Sources: runs/architecture_presentation_20260922/multitone/static/capture/y_accepts.csv, runs/architecture_presentation_20260922/multitone/stalled/capture/y_accepts.csv, artifacts/reference_outputs/near_threshold_multitone_Ns1024_thr64/y_out.memh

### 08_frame_deadline_budget. Frame deadline budget
The source-derived connected bound including metrics allowance is 17673 clocks, rounded to an 18000-clock allocation. At 50 MHz this is 360 microseconds. The recurrent budget excludes finite tail, analog delay and transport. Unbounded external stalls invalidate a finite service guarantee.

Sources: docs/architecture/architecture_design.md, docs/architecture/transform_microarchitecture.md

### 09_fitted_resources. Fitted resources
The archived Lite build uses 21220 ALMs, 36 DSP blocks and 55 RAM blocks. Percentages use exact reported used/available counts. These are whole-board totals, including interfaces and telemetry, rather than isolated-core costs.

Sources: docs/results/de1soc_lite_bram_20260915.json, runs/quartus/windows/20260915-lite-bram-01/implementation-reports/trecap_de1soc.fit.rpt

### 10_fitted_timing. Fitted timing
All four explicit fabric-clock timing queries pass. Minimum fabric setup is +2.333 ns and minimum hold is +0.002 ns. That narrow positive hold margin applies to the analyzed model. Global minimum setup is +1.727 ns and differs from the fabric-only number.

Sources: docs/results/de1soc_lite_bram_20260915.json, runs/quartus/windows/20260915-lite-bram-01/fitted-timing/fitted_timing.tsv

## Reproduce
From the repository root with NumPy and Matplotlib installed:

    python scripts/analysis/plot_architecture_presentation.py --repo .

Recorded captures must exist in runs/architecture_presentation_20260922. The builder validates archived fitter/timing hashes and full output sequences against the qualified reference. It does not modify RTL or rebuild Quartus.

## Signal and timing conventions
- Signed 12-bit sample codes use LSB units.
- Numerical comparison includes all 1536 output samples.
- Handshake traces sample signals at rising edges before register updates.
- A transfer requires valid and ready together.
- Interface event spans include intervening gaps.
- D=384 samples is reference alignment, separate from service cycles and host/network delay.

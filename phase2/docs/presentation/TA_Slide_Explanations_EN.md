# T-RECAP: Slide-by-slide explanations and speaker notes

Team #2

These notes cover all seven reference-model pages and all ten architecture pages in the presentation packages dated 22 September 2026. The explanations follow the plotted data and the scope of the supporting evidence.

## Terminology

- A sample is one numerical input or output value. Sample index identifies its position in the signal.
- A frame is a group of 256 samples processed by the FFT. The hop is 128 samples, so adjacent frames overlap by 50%.
- A frequency bin is one discrete frequency location in the 256-point FFT.
- LSB means one least-significant-bit step of the integer sample representation. These plots show sample codes, not voltages.
- THR2 is the raw threshold compared with squared spectral magnitude. It is not a voltage, a decibel threshold, or a power-meter reading.
- RMSE is root mean square error. Here it summarizes numerical sample differences over the entire emitted output, including startup and the tail.
- An FPGA clock cycle is different from an input sample interval. The fabric clock runs at 50 MHz, while input sample rates can be much lower.
- The reference model is the offline C++ numerical implementation. RTL simulation executes the hardware description. Quartus fit and timing reports describe the compiled FPGA implementation.

## Reference model: seven slides

### Slide 1: Reconstruction with a 384-sample delay

**What the figure shows**

The first panel shows the original multitone input, extended with zeros after its 1024 samples. The second panel overlays the reference output with the input shifted by 384 samples. The third panel plots their difference over all 1536 output samples.

**How to interpret it**

The correct comparison is y[n] against x[n-384], with zero extension outside the original input. Comparing y[n] with unshifted x[n] would mistake the designed delay for an arithmetic error. With THR2 = 4096, the final quantized output matches the delayed input exactly for this test. Some very small spectral components are suppressed, but the final output codes remain unchanged.

The 384-sample shift is algorithmic reference alignment. It is not a measurement of FPGA execution cycles, codec delay, or network latency.

**Suggested narration**

"This slide checks reconstruction in our reference model. The upper plot is the input, and the middle plot compares the output with the input delayed by 384 samples. After this alignment, the two waveforms overlap. The bottom plot confirms zero numerical error across all 1536 output samples for this input and threshold, including startup and the tail."

### Slide 2: What the spectral mask removes

**What the figure shows**

The upper panel shows the canonical spectrum of frame 4 before masking. The horizontal axis contains the 129 unique bins, from DC at bin 0 through Nyquist at bin 128. The vertical axis uses a logarithmic scale for raw squared magnitude. The dashed line is THR2 = 10^11.

Maroon points identify retained bins. Gold crosses identify suppressed bins. The lower panel shows the actual binary mask: 1 means suppress and 0 means keep.

**How to interpret it**

An eligible bin is suppressed only when its squared magnitude is strictly below THR2. Equality is retained. DC is protected in this configuration, so it remains present even if its magnitude is below the threshold.

These are model-exported, canonical, pre-mask FFT values for one frame. They are not an FFT of the entire output waveform. A small component is not automatically noise; this plot demonstrates a threshold decision, not a validated denoising application.

**Suggested narration**

"This slide explains how the mask makes its decisions. We compare each eligible frequency bin's squared magnitude with the dashed threshold. The gold markers fall below that threshold and are set to zero. The stronger maroon components remain. DC is an intentional exception because this configuration protects it. The lower panel shows the exact mask applied to the frame."

### Slide 3: Higher thresholds change the reconstructed signal

**What the figure shows**

The upper panel compares an aligned waveform segment with outputs from THR2 = 10^11 and THR2 = 10^13. It compares input sample j with output sample j+384. The lower panel shows reconstruction error over the complete output stream.

**How to interpret it**

A higher threshold suppresses more spectral content. The 10^11 result remains closer to the input than the 10^13 result. Full-stream RMSE increases from approximately 22.71 LSB to 129.55 LSB.

The shaded regions lie outside the delayed input's original support. Masking can still produce reconstruction error in these regions because processing occurs over overlapping frames. Those samples remain in the error calculation.

**Suggested narration**

"Here we can see the effect of increasing the threshold. At the moderate threshold, the output stays relatively close to the input. At the larger threshold, more frequency content is removed and the waveform changes more visibly. The error plots quantify that difference across the full stream, rather than only the cleaner-looking middle section."

### Slide 4: Threshold sweep: suppression versus reconstruction error

**What the figure shows**

All three panels use the same input and coefficients across 11 threshold settings. The upper panel reports the percentage of eligible unique-bin instances suppressed across frames. The middle panel reports retained weighted spectral magnitude squared. The bottom panel reports full-stream RMSE.

The horizontal axis uses a symmetric-logarithmic scale so it can include both threshold zero and very large thresholds.

**How to interpret it**

Increasing THR2 increases suppression, eventually removes substantial spectral content, and increases reconstruction error for this input. At THR2 = 10^11, suppression is approximately 93.06%, spectral retention is 99.21%, and RMSE is 22.71 LSB. Many bins can have very small magnitudes, which explains how the model can suppress many bin instances while retaining most of the plotted spectral quantity.

Interior positive-frequency bins represent conjugate pairs and receive a weight of two in the spectral totals. This metric does not directly state time-domain reconstruction quality or electrical energy saved. The baseline FFT and IFFT still execute their full schedules.

**Suggested narration**

"This sweep shows the tradeoff we can control with the threshold. A higher threshold removes more bin instances, but the reconstruction error also grows. At one operating point, we suppress about 93 percent of eligible bin instances while retaining about 99.2 percent of the weighted spectral magnitude squared. That is a signal-representation result. We still need separate hardware measurements to evaluate electrical energy."

### Slide 5: Frame-by-frame spectrum and suppression

**What the figure shows**

The horizontal axis is the unique FFT bin, and the vertical axis is frame index. The upper heatmap displays pre-mask squared magnitudes on a logarithmic color scale. The lower heatmap displays the exact mask for THR2 = 10^11: maroon means suppress and the light color means keep.

**How to interpret it**

The upper heatmap shows where stronger frequency components occur and how they vary across frames. The lower heatmap shows how those values lead to different mask decisions. DC stays protected.

Frames 0 and 8 contain zero-padded boundaries of the finite input, so their spectra differ from interior frames. Frame number provides processing order; it is not a measured hardware time axis.

**Suggested narration**

"This view expands the spectrum from one frame to the entire finite run. The upper heatmap shows the strength of each frequency component in each frame. The lower heatmap shows which components the mask removes. The boundary frames look different because they include zero padding, while the interior frames show the repeated structure of the multitone input."

### Slide 6: Frozen window coefficients and 50% overlap

**What the figure shows**

The upper plot decodes the actual quantized square-root Hann window from the coefficient table. The lower plot evaluates w[i]^2 + w[i+128]^2 across the 128 overlap phases.

**How to interpret it**

Analysis and synthesis each apply a window, so their combined weighting involves the square of the window. With a hop of 128 and a frame length of 256, adjacent frames overlap by half a frame. For ideal, unquantized square-root Hann coefficients, the overlapping squared windows sum to one.

The actual finite-precision coefficients produce a sum very close to one, with a maximum deviation of approximately 4.1 x 10^-5. This supports approximately uniform reconstruction gain across overlap positions. It is one coefficient property, not a complete proof of zero-error reconstruction for all inputs.

**Suggested narration**

"This slide explains the window used in our overlap-add reconstruction. Adjacent 256-sample frames overlap by 128 samples. Because we apply a window during both analysis and synthesis, we inspect the sum of the squared overlapping windows. It stays very close to one, which helps avoid gain changes between overlap positions. The small deviation comes from coefficient quantization."

### Slide 7: Impulse response confirms the sample-domain delay

**What the figure shows**

The upper plot shows an isolated input impulse and its reference-model output. Their positions differ by 384 sample indices. The lower plot shows zero error after alignment over the complete output.

**How to interpret it**

An isolated impulse makes the displacement easy to see. This test uses THR2 = 0, so eligible spectral components are not suppressed. The output preserves the impulse for this test after the specified shift.

At an assumed sample rate of 48,000 samples per second, 384 samples correspond to 8 ms. That conversion describes the algorithmic alignment, not measured end-to-end board latency.

**Suggested narration**

"We use an impulse to make the reference delay easy to identify. The output impulse appears exactly 384 samples after the input impulse, and the aligned error is zero. This confirms the expected sample-domain alignment for this test. At a 48-kilohertz sample rate, the shift would correspond to eight milliseconds, excluding physical interfaces and transport."

## Architecture: ten slides

### Slide 1: System data flow and ownership

**What the figure shows**

The main data path runs from input sources through one FPGA mathematical core, then through observation and transport into DDR, the HPS, and the PC dashboard. Dashed paths show commands returning through the HPS and FPGA control registers.

**How to interpret it**

The FPGA performs the STFT, threshold masking, WOLA reconstruction, and numerical error calculations. The HPS is the ARM-based Hard Processor System. Its role includes consuming committed DDR records, sending UDP data, and issuing control-register writes.

Core observation taps carry valid data without a ready return path. Telemetry congestion can drop records, but cannot stall the mathematical core. Input-source loss is a separate issue and can require stopping or resetting the source epoch.

The diagram shows implemented ownership and intended integration. Complete HPS-to-dashboard board operation remains to be accepted.

**Suggested narration**

"This slide shows which part of the system owns each task. The FPGA performs the signal processing and computes the metrics. A separate telemetry path transfers observations through DDR to the ARM processor, which forwards them to the PC. Commands return through control registers. Separating these paths prevents dashboard or network congestion from stalling the DSP core."

### Slide 2: Fixed-point DSP datapath

**What the figure shows**

The upper row runs left to right through frame history, analysis window, FFT, and canonicalization. The path continues downward through the mask, then right to left through the spectrum builder, IFFT, and WOLA.

**How to interpret it**

The core accepts signed 12-bit samples. Internal widths increase to represent window products, complex transforms, squared magnitudes, and overlap accumulation. FFT and canonical spectrum components are 28 bits. IFFT components are 36 bits, and the overlap accumulator is 37 bits. Final output returns to signed 12-bit codes using the specified rounding and saturation.

The 4-entry metadata queue associates each admitted frame with its threshold. A later control update therefore cannot split one frame between two thresholds. The delayed-input history supports the error calculation. It is not a second copy of the offline C++ model.

**Suggested narration**

"This is the numerical pipeline implemented in RTL. We extract a frame, apply the analysis window, and compute the FFT. Canonicalization establishes the spectrum representation before the magnitude threshold selects which eligible bins to remove. The IFFT and weighted overlap-add then reconstruct the output. The annotated widths make the fixed-point representation explicit, and each frame retains its own threshold."

### Slide 3: Registered butterfly schedule

**What the figure shows**

Seven scheduled rising edges implement one butterfly: memory read, multiplication, complex product addition, quantization, butterfly addition, final rounding, and writeback.

**How to interpret it**

Each 256-point radix-2 transform has eight stages and 128 butterflies per stage: 1024 butterflies per frame. At seven clocks each, computation uses 7168 clocks. Under continuous input and ready output, loading and output add 256 and 512 clocks, giving an inclusive service count of 7936 clocks.

At 50 MHz, this local service interval corresponds to 158.72 microseconds. Register boundaries split the arithmetic across cycles. The FFT applies a divide-by-two stage shift, while the IFFT does not. Both engines still process all butterflies when bins are suppressed.

**Suggested narration**

"We reuse a registered butterfly across each transform. One butterfly takes seven scheduled clock edges, separating the arithmetic into shorter registered steps. Across eight stages, each transform performs 1024 butterflies. Including load and output, the unstalled local service count is 7936 clocks. Thresholding does not shorten that baseline computation."

### Slide 4: Selected storage in the implemented architecture

**What the figure shows**

The horizontal bars show the logical capacities of selected arrays, measured in Kibit, where one Kibit is 1024 bits. Labels identify each array's depth and word width.

**How to interpret it**

Memory holds input history, transform frames, overlap values, replay samples, and telemetry payloads. The input and delayed-input histories use 76-bit words because each stores a 64-bit logical sample index alongside a 12-bit sample.

For example, delayed history uses 1024 x 76 = 77,824 logical bits, while the telemetry payload uses 2700 x 32 = 86,400 bits. These are declared capacities. Physical RAM-block usage also depends on available block geometry and packing. The selected arrays omit other memories and control state, so this chart is not a complete device-utilization report.

**Suggested narration**

"This chart shows where the architecture stores data. The core needs history and transform workspaces, while the observation path needs bounded payload buffers. The histories also retain logical sample indices, which explains their wider words. These bars show logical storage requirements. The fitted RAM-block count is a separate result from Quartus."

### Slide 5: Observed first-frame pipeline activity

**What the figure shows**

The bars come from actual RTL simulation signals. Maroon bars identify FFT and IFFT compute phases. Teal bars span first through last accepted transfer at each interface. The horizontal axis is relative to the first window transfer, recorded at simulation cycle 525.

**How to interpret it**

Each transform compute phase lasts exactly 7168 clocks in this capture. Interfaces transfer 256 frame values, while WOLA emits 128 output samples for this frame.

An interface bar includes gaps between valid transfers. Its width is not a count of continuously active clocks. Canonicalizer, mask, and spectrum-builder spans overlap because those stages pass values between them. The WOLA output-transfer bar excludes later overlap-memory updates, so it is not the complete frame-service interval. This testbench supplies unpaced replay data, so it does not represent a live 48 ksample/s stream.

**Suggested narration**

"This slide shows actual activity from the RTL simulation. Both transform engines spend 7168 clocks in their compute phases, matching the documented schedule. The other bars show when values cross the stage interfaces. Some spans overlap because adjacent stages transfer data as it becomes available. These are simulation-cycle observations for unpaced replay, rather than measured board latency."

### Slide 6: Output handshake under backpressure

**What the figure shows**

The upper panel shows valid and ready. The middle and lower panels show the output sample index and value. Gold regions identify valid high while ready is low. Dotted lines mark accepted transfers.

**How to interpret it**

Valid means the producer has a sample available. Ready means the receiver can accept it. A transfer occurs only on a rising edge when both are high. During a stall, the producer must retain the sample and its index.

In the directed example, sample 600 holds the value 11 for eight blocked clocks, from cycles 52384 through 52391. It transfers at cycle 52392. Data shown when valid is low is not an accepted output sample.

This test stalls the reusable core's output interface. It does not contradict telemetry isolation in the physical board composition.

**Suggested narration**

"This waveform demonstrates how the core handles a receiver that temporarily stops accepting data. In the highlighted interval, valid stays high but ready is low. The output index and value remain unchanged until the handshake succeeds. Here, sample 600 holds the value eleven for eight blocked clocks and transfers when ready returns."

### Slide 7: RTL and reference output waveforms

**What the figure shows**

The first panel overlays RTL output with reference output. The second panel plots RTL minus reference. The last panel plots elapsed acceptance cycles against output sample index for the static and stalled runs.

**How to interpret it**

Both runs contain 1536 ordered output samples, and every sample matches the reference for this vector and threshold. The output-difference plot is zero across startup, active output, and the full tail.

RTL-minus-reference error measures agreement between implementations. It differs from reconstruction error, which compares the output with x[n-384]. Numerical equivalence does not require identical delivery cycles. Backpressure changes when samples transfer while preserving their values and order. At the plotted scale, the timing curves nearly overlap. This is evidence for this selected case, not complete RTL verification or measured speedup over software.

**Suggested narration**

"We compare every emitted RTL sample with the reference output. Both the static and stalled runs match all 1536 samples, including startup and the tail. The bottom graph separates delivery timing from numerical correctness. Stalls can delay acceptance without changing the output sequence, which is the behavior we want from the streaming interface."

### Slide 8: Frame-work allocation and sample-rate deadlines

**What the figure shows**

The maroon section reserves 18,000 fabric clocks for connected frame work. The gold section shows the remaining time before the next hop deadline, at two assumed periodic sample rates.

**How to interpret it**

At a 50 MHz fabric clock, 18,000 clocks correspond to 360 microseconds. With a hop of 128 samples:
- At 100 ksample/s, one hop provides 64,000 clocks or 1.28 ms. The allocation uses 28.125% of that interval.
- At 48 ksample/s, one hop provides approximately 133,333 clocks or 2.6667 ms. The allocation uses 13.5%.

The source-derived connected bound is 17,673 clocks, rounded up for allocation. This budget assumes an initialized epoch, healthy periodic input, and ready output. Remaining clocks are scheduling margin; they do not establish that circuitry is power-gated or saving energy. Finite tail flushing is separate.

**Suggested narration**

"This chart compares the frame-work allocation with the time available between hops. At 100 thousand samples per second, we allocate 18 thousand of the available 64 thousand clocks. At 48 thousand samples per second, the margin is larger. The calculation supports the documented processing schedule under its stated assumptions, but does not measure power savings."

### Slide 9: Fitted FPGA resource utilization

**What the figure shows**

The bars report the used fraction of each device resource from the archived Quartus Lite build dated 15 September 2026.

**How to interpret it**

The complete board implementation uses:
- 21,220 of 32,070 ALMs, approximately 66.17%.
- 36 of 87 DSP blocks, approximately 41.38%.
- 55 of 397 RAM blocks, approximately 13.85%.
- 368,256 of 4,065,280 block-memory bits, approximately 9.06%.

ALMs implement logic, DSP blocks support arithmetic, and embedded RAM stores data. The design also has 29,452 registers. These are whole-board totals, including interfaces and telemetry. The difference between RAM-block and memory-bit percentages reflects allocation and packing. Utilization alone does not determine electrical energy consumption.

**Suggested narration**

"These are actual resource counts from the fitted FPGA implementation. The complete design uses about 66 percent of the device's ALMs, 41 percent of its DSP blocks, and 14 percent of its RAM blocks. That confirms the archived implementation fits the selected device. The totals include the surrounding board and telemetry logic, not just the mathematical core."

### Slide 10: Fitted timing across four operating corners

**What the figure shows**

The upper panel reports setup slack and the lower panel reports hold slack for explicit CLOCK_50-to-CLOCK_50 timing checks. The tool evaluates slow and fast models at two temperatures, all at 1100 mV.

**How to interpret it**

Setup checks whether data arrives early enough before the capturing clock edge. Hold checks whether data remains stable long enough after that edge. Positive slack means the tool's analyzed requirement is met.

The smallest fabric setup slack is +2.333 ns. The smallest hold slack is +0.002 ns, a very small positive margin. These results apply to the analyzed implementation and timing assumptions. The whole design includes other clock domains: its global minimum setup slack is +1.727 ns, distinct from the fabric-only value.

Timing closure does not by itself prove algorithmic correctness, functional CDC behavior, or end-to-end board operation.

**Suggested narration**

"The final slide shows static timing results for the 50-megahertz fabric paths across four operating corners. Setup and hold slack are positive in every analyzed corner. The minimum setup margin is 2.333 nanoseconds, while the minimum hold margin is only 0.002 nanoseconds. These results support the archived timing constraints, alongside the separate functional verification work."

## Suggested closing statement

"Our current results connect the numerical reference model, the RTL datapath, and the fitted FPGA implementation. We have demonstrated threshold-dependent signal behavior and matching RTL outputs for selected simulations. The remaining work includes broader verification, complete board operation, application-level benchmarking, and direct electrical-energy measurements."

## Local evidence

- Reference figures: reference_model_20260922/T_RECAP_Reference_Model_Figures.pdf
- Reference methods: reference_model_20260922/README.md
- Architecture figures: architecture_20260922/T_RECAP_Architecture_Figures.pdf
- Architecture methods: architecture_20260922/README.md
- Per-figure source mapping: architecture_20260922/provenance.json
- Simulation capture provenance: architecture_20260922/data/capture_manifest.json

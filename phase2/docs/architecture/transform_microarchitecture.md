# Transform microarchitecture

Our analysis and reconstruction paths use separate iterative radix-2 DIT engines:
[FFT](../../rtl/fft/trecap_fft256.sv) and
[IFFT](../../rtl/fft/trecap_ifft256.sv). Each owns one frame store, one registered
butterfly, and its direction's frozen coefficient ROMs. Both load in bit-reversed
address order, execute the reference model's stage/base/butterfly order, and emit
natural-order samples. A frame owns its engine until its last output is accepted.

## Arithmetic and scheduling

The [butterfly](../../rtl/fft/trecap_fft_stage.sv) uses its registered mode in both
engines. The legacy combinational mode remains available to existing standalone
users; it is not the production transform datapath.

For one butterfly, the following seven consecutive rising edges implement the
complete transaction. The addresses and stage counter remain unchanged until
edge 7.

| Edge | Engine / butterfly state | Registered operation |
| --- | --- | --- |
| 1 | S_READ | Read both complex RAM operands and the twiddle ROMs. |
| 2 | S_START / B_IDLE | Accept operands; hold operand A and register four signed products for B times the twiddle. |
| 3 | S_WAIT / B_PRODUCT_SUM | Sign-extend the products and register the full real difference and imaginary sum. |
| 4 | S_WAIT / B_QUANTIZE | Apply the original FRAC_SHIFT=15 rounding and saturation to each complex-product component. |
| 5 | S_WAIT / B_ADD | Register widened A plus/minus the quantized complex product. |
| 6 | S_WAIT / B_ROUND | Apply the original final rounding/saturation; register four result components. |
| 7 | S_WAIT / B_OUTPUT | Accept the held butterfly result and write both RAM addresses; advance the iteration. |

There is no truncation between multiplication and the complex product sum. The
product-sum width remains DATA_W + TWIDDLE_W + 2; the butterfly sum width
remains DATA_W + 2. The forward transform divides by two at every stage using
the existing trecap_round_sat rule. The inverse transform has no stage shift.
The registered path uses exactly the same two rounding points as the retained
combinational arithmetic path.

| Arithmetic quantity | FFT | IFFT |
| --- | ---: | ---: |
| Data component | 28 bits | 36 bits |
| Twiddle component | 17 bits | 17 bits |
| Each of four signed products | 45 bits | 53 bits |
| Complex product sum/difference | 47 bits | 55 bits |
| Butterfly sum/difference | 30 bits | 38 bits |
| Final stage shift | 1 | 0 |

The four product registers carry multstyle="dsp". They are four logical signed
DSP multiplications per engine; physical DSP block packing depends on device
width decomposition. Register boundaries separate multiplication, product
addition, quantization, butterfly addition, and final rounding. There is no
single combinational path spanning all of those operations.

## Memory implementation

All production work stores use synchronous reads and explicitly select M10K
memory with `ramstyle="M10K"`. FFT and IFFT work RAM additionally specify
`no_rw_check` locally because their schedules never perform a read during a
write: reads occur only in `S_READ`/`S_OUT_READ`, while input writes occur only
in `S_IDLE`/`S_LOAD` and butterfly writes only in `S_WAIT`. Reset and clear gate
all accesses. The two butterfly write addresses differ by `2**(stage-1)` for
stages 1 through P, and `S_OUT_SEND` performs no access while holding output
data through backpressure. The attribute permits Quartus to choose a hardware
read-during-write mode for an unreachable case; it does not change any observed
data or cycle count. This is a per-memory inference setting, not a global
relaxation of memory behavior. Their packed complex words share the same address
for real and imaginary components.

| Store | Logical organization | Port A | Port B |
| --- | --- | --- | --- |
| FFT working frame | 256 x 56 bits | Input writes, operand-A reads/writes, output reads | Operand-B reads/writes |
| IFFT working frame | 256 x 72 bits | Input writes, operand-A reads/writes, output reads | Operand-B reads/writes |
| Canonicalizer frame | 256 x 56 bits | Input writes or positive-member reads | Negative-member reads |
| Each engine's twiddle pair | Two 256 x 17-bit ROMs | One synchronous read per component | Unused |

Quartus Prime Standard 20.1.1 Analysis & Synthesis completed in the native08
build on 2026-09-13. Its RAM report inferred both transform work stores as
M10K true-dual-port memories (`BIDIR_DUAL_PORT`), with 256 words per port:
56-bit words for FFT and 72-bit words for IFFT. This confirms synthesis
inference. In that native08 run, fitting stopped at I/O constraints before
placement, so the native08 evidence did not include fitted resource counts or
timing. Subsequent native11 placement/routing completed. Current results for
later source revisions are recorded in
[architecture_implementation.md](architecture_implementation.md), using the gates
in [build_order.md](build_order.md). Functional verification and physical board
operation remain pending.

The first three rows use a two-port coding template with a shared read/write
address on port A. Each transform's compute writeback writes distinct low/high
addresses. The next operand read occurs on the following edge, so read-during-
write behavior is not part of the arithmetic contract. Load, compute, and output
phases do not overlap within an engine.

RAM contents, RAM read data registers, and arithmetic data registers are not
reset. Reset and clear invalidate the controlling state, and a complete frame
load precedes the next compute read. This avoids a register-array implementation
caused by clearing every word. Valid signals qualify data during initialization.

The [twiddle wrapper](../../rtl/fft/twiddle_rom.sv) registers direct memory reads.
The engines set FIXED_DIRECTION=1 and their respective INVERSE_DIRECTION, making
the unused direction's ROM pair removable at elaboration/synthesis. The frozen
.memh files remain coefficient sources. The wrapper's default still supports a
dynamic direction for other callers.

These choices specify the RAM and DSP architecture now. Physical M10K count,
DSP packing, and fitted timing are implementation reports, not values inferred
from logical bit totals. The timing target is 50 MHz; the cycle schedule alone
does not establish a fitted maximum clock frequency.

## Hermitian canonicalizer

The [canonicalizer](../../rtl/core/trecap_hermitian_canonicalizer.sv) first accepts
all 256 natural-order FFT bins. Each output bin then takes four edges:

1. S_READ: read the positive and negative members together.
2. S_PRE: register the widened real sum and imaginary difference.
3. S_ROUND: round those pre-adds by two and register the selected output.
4. S_EMIT: accept the held output, then advance to the next read.

The negative half negates the already rounded positive imaginary component.
It does not round an independently negated pre-add; this preserves the specified
tie behavior. DC and Nyquist pass their real component through the existing
saturation operation and force the imaginary component to zero. Natural bin
order, unique/self-conjugate flags, frame identity, and last-bin indication are
retained. Ordinary valid gaps are allowed. Repeated/missing-bin, frame-identity,
or last-bin metadata errors discard the offending beat and hold the block in
S_FAULT until clear or disable. Clearing sticky flags alone does not release
this state. This prevents reading a frame store that was only partially loaded.
Nonzero DC/Nyquist input imaginary components and arithmetic saturation retain
their existing diagnostic behavior.

## Cycle contract and backpressure

Cycle counts below include the first input-acceptance edge and the last output-
acceptance edge. Subtract one to obtain the difference between those two edge
numbers. They assume a continuously available input frame, continuously ready
output, no reset/clear/disable, and a legal complete frame.

| Block | Load | Compute | Output | Total |
| --- | ---: | ---: | ---: | ---: |
| FFT | 256 | 7 * 8 * 128 = 7168 | 2 * 256 = 512 | 7936 |
| IFFT | 256 | 7 * 8 * 128 = 7168 | 2 * 256 = 512 | 7936 |
| Canonicalizer | 256 | Included in output | 4 * 256 = 1024 | 1280 |

For a transform, after the final input acceptance, there are 7168 compute edges
and 512 output edges until the final output acceptance. With the first accepted
input at edge 0, the final output is accepted at edge 7935, and the next frame
can begin at edge 7936. A transform output takes a synchronous read edge
followed by an acceptance edge; output throughput is one complex value every
two clocks. The registered butterfly itself makes its result valid four clocks
after operand acceptance and transfers it on the next edge.

Each absent input beat while loading adds one clock. Each clock spent holding
a valid output against deasserted ready adds one clock. Output data, index, frame
identity, and last indication remain stable during such a stall. Unbounded
external stalls therefore have no finite completion bound. The private
butterfly cannot be stalled by an external consumer during computation.

At 50 MHz the standalone transform service interval is 158.72 microseconds,
and the canonicalizer interval is 25.60 microseconds. The sum of the three
standalone intervals is 17152 clocks, or 343.04 microseconds, before accounting
for actual input gaps, other core stages, and any external stalls. In the
connected path, FFT output loading overlaps the canonicalizer's load, and
canonicalizer output loading overlaps the IFFT's load. Whole-core scheduling
must count these overlaps and the actual upstream cadence once, rather than
treating the standalone figures as a measured end-to-end latency.

Both transforms still execute all 1024 butterflies per frame. Suppressed bins
do not shorten this baseline schedule. The system deadline remains the hop
interval H/Fs: 64000 clocks at 100 ksample/s or about 133333 clocks at
48 ksample/s. The integrated core budget includes the remaining stages and
transport policy in addition to these transform costs.

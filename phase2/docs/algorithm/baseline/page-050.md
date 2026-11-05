# Baseline PDF page 050

Historical Part II, DDR and UDP telemetry. Printed page 37. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=50).

[Previous](page-049.md) | [Index](../README.md) | [Next](page-051.md)

[Edit Markdown and LaTeX source](../source/baseline/page-050.md). Equations are rendered locally as SVG.

### 17.3 Ring Initialization Rule

Ring initialization shall clear stale producer/consumer state before telemetry is enabled. The baseline sequence is:

1. HPS clears `CONTROL.telemetry_enable` and `CONTROL.ring_writer_enable`.

2. HPS pulses `CONTROL.telemetry_soft_reset`.

3. HPS writes `RING_BASE_LO`, `RING_BASE_HI`, and `RING_SIZE_BYTES`.

4. HPS pulses `RING_CONFIG_COMMIT` while telemetry is disabled.

5. HPS writes `RING_RD_LO_SHADOW`=0 and `RING_RD_HI_SHADOW`=0.

6. HPS pulses `RING_RD_COMMIT`.

7. Only after the preceding steps may HPS set `CONTROL.ring_writer_enable`=1 and `CONTROL.telemetry_enable`=1. A telemetry soft reset or `RING_CONFIG_COMMIT` while telemetry is disabled shall reset the FPGA producer pointer W to zero. HPS shall commit Rd = 0 before enabling the ring writer. This prevents stale pointers after board reset, HPS restart, or ring reconfiguration.

### 17.4 Free Space Rule Including Wrap

Before writing a record of aligned length Lrec , the FPGA shall compute the current offset and the physical tail space:

![Equation 17.8: o=&#92;operatorname{off}(W).&#92;tag{17.8}](../math/baseline-page-050-001.svg)

![Equation 17.9: T_{&#92;mathrm{tail}}=R-o.&#92;tag{17.9}](../math/baseline-page-050-002.svg)

If the record would cross the physical end of the ring, the required free space is the tail consumed by the WRAP record plus the actual record:

![Equation 17.10: L_{&#92;mathrm{req}}=&#92;begin{cases}T_{&#92;mathrm{tail}}+L_{&#92;mathrm{rec}},&o+L_{&#92;mathrm{rec}}>R&#92;&#92;L_{&#92;mathrm{rec}},&o+L_{&#92;mathrm{rec}}&#92;le R.&#92;end{cases}&#92;tag{17.10}](../math/baseline-page-050-003.svg)

The available free space is:

![Equation 17.11: F_{&#92;mathrm{free}}=R-(W-R_d)-G_{&#92;mathrm{guard}}.&#92;tag{17.11}](../math/baseline-page-050-004.svg)

where Gguard ≥ 64 bytes. A packet may be written only when:

![Equation 17.12: F_{&#92;mathrm{free}}&#92;ge L_{&#92;mathrm{req}}.&#92;tag{17.12}](../math/baseline-page-050-005.svg)

If not, the packet shall be dropped and `DMA_DROP_COUNT` shall increment. Checking only Ffree ≥ Lrec is not sufficient when a WRAP record is required.

### 17.5 Record Alignment and WRAP Record

For normal telemetry records, the aligned record length is:

![Equation 17.13: L_{&#92;mathrm{rec}}=&#92;operatorname{align}_{64}(H_{&#92;mathrm{bytes}}+P_{&#92;mathrm{bytes}}).&#92;tag{17.13}](../math/baseline-page-050-006.svg)

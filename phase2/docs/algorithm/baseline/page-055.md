# Baseline PDF page 055

Historical Part II, DDR and UDP telemetry. Printed page 42. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=55).

[Previous](page-054.md) | [Index](../README.md) | [Next](page-056.md)

### 18.7 Commit Protocol

The producer pointer is the only commit signal. A record is visible to HPS only after the FPGA has completed all writes for that record and then updated the producer pointer. The HPS shall not infer committed data from partially written headers.

### Algorithm 6 FPGA DDR record write and commit protocol with correct wrap-space accounting

```text
Require: packet payload P , packet type T , current producer pointer W , committed consumer
    pointer Rd
Ensure: either one committed DDR record or one dropped telemetry packet
 1: Hbytes ← 32
 2: Pbytes ← |P |
 3: Lrec ← align64 (Hbytes + Pbytes )
 4: o ← W & (ring_size - 1)
 5: Ttail ← ring_size - o
 6: if o + Lrec > ring_size then
 7:     Lreq ← Ttail + Lrec
 8: else
 9:     Lreq ← Lrec
10: end if
11: Ffree ← ring_size - (W - Rd ) - Gguard
12: if Ffree < Lreq then
13:     increment DMA_DROP_COUNT
14:     discard packet
15:     return
16: end if
17: if o + Lrec > ring_size then
18:     write a WRAP header at B + o
19:     write zero padding through the end of the ring
20:     wait for all WRAP writes to complete
21:     W ← W + Ttail ; commit producer pointer
22:     o←0
23: end if
24: write packet header at B + o
25: write packet payload immediately after header
26: write zero padding up to 64-byte alignment
27: wait for all DDR write transactions for this record to complete
28: W ← W + Lrec
29: commit producer pointer W
```

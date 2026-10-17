# TSH2 continuous finite audio stream

New application on the unchanged qualified HPS50 platform. One START covers all
384000 signed12 PCM samples and one full tail, without resets between chunks.
Geometry: 3001 frames, 384128 analysis tokens, 384 drain ticks, 384512 Y samples.
Threshold and sparse mode are immutable during the run. Mathematical core and
coefficients remain unchanged. File input is unpaced for this correctness test;
this is not yet live codec input or a real-time throughput acceptance test.

Source uses a 256-sample FIFO. The top permits at most one triggered frame not
yet emitted by the exporter, gating new-hop admission rather than core enable.
Exporter out_ready is driven by a 1024-word packed-byte FIFO. Y uses a separate
1024-word FIFO and native y_ready. Source pauses preserve overlap/history.
Host interleaves writes and drains throughout the same epoch, storing full
results in HPS RAM. Bus accesses never wait indefinitely on full/empty FIFOs:
illegal accesses respond error and latch fault. Valid data reads pop one word.

Registers: 21-bit byte addresses, aligned32, byteenable15, burstcount1. ABI2.

| Offset | Access | Meaning |
|---|---|---|
|000|R|Magic0x54534832 TSH2|
|004|R|ABI0x00020000|
|008|R|bit0busy,1done,2fault,3PCM ready,4spectral data available,5Y available|
|00c|R|fault mask: bit0bus,1core,2export/FIFO,3count/watchdog|
|010|W|1CLEAR,2START; START only IDLE/nofault, no preload|
|014|RW|THR2 low32, IDLE only|
|018|RW|THR2 upper24, IDLE only; upper8 zero|
|01c|RW|sparse0/1, IDLE only|
|020|W|append signextended12 PCM; only ready and fewer than Ns accepted|
|024|R|host PCM writes accepted|
|028/02c|R|epoch low/high; increments START, persists CLEAR|
|030|R|spectral FIFO available32-bit words|
|034|R|Y FIFO available32-bit words|
|038|R|input FIFO level|
|03c|R|input FIFO free slots =256-level, meaningful with status PCMready|
|040|R|pop spectral packed4bytes, little endian; only nonempty|
|044|R|pop signed12 Y signextended32; only nonempty|
|048|R|total Y produced|
|04c|R|elapsed FPGA cycles including source/host stalls; not isolated core time|
|050|R|export dropped frame count|
|054|R|export emitted frame count|
|058|R|actual source PCM consumed (not zero flush)|
|05c|R|configured Ns (384000 hardware; small simulation variants allowed)|
|060|R|total spectral bytes produced|
|064|R|spectral words read by host|
|068|R|Y samples read by host|
|06c|R|configured Ny|
|070|R|expected spectral frames|
|074|R|PCM capacity256|
|078|R|spectral capacity1024 words|
|07c|R|Y capacity1024 words|
|080..09c|R|SOURCE_ID256 lowwordfirst|

DONE means numerical core finished, all exporter records committed into output
FIFO, exact input/Y/frame totals and no partial packed word. Host still drains
remaining output after DONE and must verify read totals before CLEAR. Errors
remain sticky until explicit CLEAR. Hardware watchdog is60seconds at50MHz;
host monotonic deadline45seconds per epoch and outer process timeout60seconds.
No automatic MMIO recovery after a client fault. All five thresholds get both
dense and sparse validation if budget permits; minimum acceptance is dense0
plus allfive sparse runs, exactY and exactpacket gold, zero drops.

Core/top owner: stream_core_design. Root owns rtl/adapter and FIFO plus actual
hardware. ram_verification owns host/ client, gold package and comparison.
ram_board_build owns source-bound build/simulation orchestration under build/.
All old sources, packages and receipts remain immutable.

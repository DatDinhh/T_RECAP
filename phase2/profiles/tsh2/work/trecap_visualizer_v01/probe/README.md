# Read-only TSH2 idle admission

Root first checks boot identity, process/socket ownership, RAM-only mounts and
the separately qualified HPS system probe (`--require-lw-only`). Then root may
invoke this binary under an outer 10-second timeout:

`tsh2_probe.arm --read-only --source 39db0fdf3d451dfbf2d878575725cedd3df450980b40b2a742620dfb76a1a8ed`

The binary opens `/dev/mem` read-only, takes an exclusive nonblocking advisory
lock, maps just one 4096-byte page at 0xff200000 with PROT_READ, and reads a fixed
allowlist. No control, threshold or FIFO-pop address is read or written.
Snapshots are bounded and reject a changed epoch/status, wrong source/geometry,
busy/fault, nonempty input/output FIFOs, drops, inconsistent IDLE/DONE counts,
or an invalid cycle count. It accepts clean IDLE or fully drained DONE.
The elapsed counter can be nonzero in IDLE because CLEAR_CORE and WAIT_INIT
count as busy cycles in the frozen adapter; IDLE data counters must be zero.
It neither clears nor repairs state. The JSON records source, epoch, raw
register values and that no writes/pop reads were performed. A 5-second alarm
and caller timeout bound ordinary stalls; blocked physical bus access still
requires explicit operator recovery, never automatic retry.

`--self-test` never opens hardware. Twenty-four register scenarios cover valid
IDLE/DONE, wrong identity/source/geometry, busy/fault, all nonempty FIFOs, bad
totals, changed epoch and drops. Three source parsing checks are included.
The build runs the same tests with native UBSan and ARM QEMU; no FPGA operation
is performed. Build output and qualification are separate from frozen sources.

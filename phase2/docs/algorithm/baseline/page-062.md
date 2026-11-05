# Baseline PDF page 062

Historical Part II, DDR and UDP telemetry. Printed page 49. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=62).

[Previous](page-061.md) | [Index](../README.md) | [Next](page-063.md)

5. continue streaming unless a diagnostic mode explicitly requests stop-on-error. The HPS shall not stop advancing Rd indefinitely because the PC dashboard is slow or disconnected.

### 20.4 HPS Streamer Algorithm

### Algorithm 7 HPS DDR ring consumer and UDP streamer

```text
Require: configured CSR base, DDR ring mapping, UDP destination
 1: configure Ethernet and UDP socket as nonblocking or bounded-timeout
 2: clear CONTROL.telemetry_enable and CONTROL.ring_writer_enable
 3: pulse CONTROL.telemetry_soft_reset
 4: configure ring base, ring size, packet enables, decimation, and spectrum shift
 5: pulse RING_CONFIG_COMMIT while telemetry is disabled
 6: Rd ← 0
 7: write RING_RD_LO_SHADOW=0 and RING_RD_HI_SHADOW=0
 8: pulse RING_RD_COMMIT
 9: write CONTROL.ring_writer_enable=1 and CONTROL.telemetry_enable=1
10: while streaming do
11:     request RING_WR_SNAPSHOT
12:     W ← latched 64-bit producer pointer
13:     while Rd != W do
14:        read candidate record header at B + off(Rd )
15:        validate header and payload bounds using Section 20.5
16:        if record is malformed then
17:            increment malformed-record counter
18:            disable telemetry writer
19:            commit current Rd through RING_RD_COMMIT
20:            require telemetry soft reset and ring reconfiguration before streaming resumes
21:            break
22:        end if
23:        if packet type is WRAP then
24:            Rd ← Rd + (R - off(Rd ))
25:            commit Rd through RING_RD_COMMIT
26:            continue
27:        end if
28:        if record exceeds Pudp,max then
29:            increment oversized-record counter; drop UDP datagram
30:        else
31:            send header and payload as one UDP datagram
32:            if send would block or fails then
33:                increment udp_send_error_count; drop datagram
34:            end if
35:        end if
36:        Rd ← Rd + align64 (32 + payload_bytes)
```

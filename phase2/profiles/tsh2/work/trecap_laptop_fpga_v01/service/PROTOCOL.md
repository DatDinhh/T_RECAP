# Finite laptop to FPGA service

One IPv4 TCP listener binds only `169.254.196.128:18082`. Explicit invocation:
`service.arm --execute-hardware --source HEX64 --boot-id UUID --requests N`,
where N is1..165. Root admits the FPGA, bridges and source first. The service pins
and verifies HPS CPU0, locks `/dev/mem` exclusively and maps the existing TSH2
aperture. It does not program hardware, change bridges or receive gold files.

One request per connection. All fields and PCM values are little endian:

* Request header16 bytes: `<IQI>` = magic0x31515254, threshold unsigned64,
  input length1536000. Follow with384000 signed int32 PCM values in signed12
  range. The client must call `shutdown(SHUT_WR)` after the PCM to delimit the
  request. Extra or missing bytes are rejected before accelerator writes.
* Reply header40 bytes: `<IIIIQQQ>` = magic0x31535254, status0success/1failure,
  Y byte count, TSP1 byte count, epoch, board wall nanoseconds, board thread CPU
  nanoseconds. Success payload is full Y int32le then sparse TSP1; no extra data.
  Failure header has status1 and all remaining fields zero. Any failed request
  ends the service, without retrying or automatically issuing MMIO abort.

The original host02 source is included through a renamed main. Its `run()` and
`timed_run()` are unchanged. The board timer encloses only that existing timed
call; input receipt and output prefault occur before it, reply transmission
after it. Laptop transport timing encloses connect/upload/compute/download and
must be measured on the laptop alone. Exact reference checks happen afterward.

Upload and reply each have an absolute10-second phase deadline. Idle accept is
also bounded to10seconds, so start the client promptly after LISTENING. A60second
alarm bounds a blocked MMIO request. Up to N requests are served serially and
then the process exits. Root owns listener launch/stop and all network access.

`--mock` runs the inherited13 register-mock cases and five socketpair cases:
full request/full output exact check, wrong magic, wrong length, truncated PCM
and trailing byte. Native UBSan and ARM QEMU both exercise them without TCP or
hardware. Socket mocks do not prove physical timer, affinity or network results.

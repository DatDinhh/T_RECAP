# Architecture implementation status

We organize implementation around one deterministic core and a best-effort observation path. The [integrated specification](../specs/README.md) fixes the arithmetic and interface baseline. The [architecture design](architecture_design.md) records the microarchitecture, capacity calculations, and remaining design limits.

## Main deliverable

Our main deliverable combines a finite reference model, a reusable FPGA STFT/WOLA core, deterministic BRAM input replay, threshold control, and FPGA-to-PC telemetry through HPS DDR/Ethernet. It must have a clear relationship between the input, delayed reference `x[n-D]`, reconstructed output, and core-owned metrics.

LINE-IN is the primary live-source extension. The optional ADC profile is independent and cannot block BRAM or LINE-IN milestones. Additional downstream compute skipping, runtime precision modes, cloud services, and new transport protocols are outside the baseline.

The reference model defines a finite stream and full-tail output. The FPGA integration also handles source epochs and continuous input. A finite software run does not by itself define physical sample pacing, CDC, or how a live source recovers after overflow.

## Implementation state

| Area | Implemented source | Next tool or board result |
| --- | --- | --- |
| Reference model | C++ arithmetic, frozen coefficients/vectors, strict configuration/export boundary | Numerical verification remains a separate phase |
| Mathematical core | Registered transforms; synchronous frame/history/OLA RAM; connected 18000-clock allocation; native M10K inference and passing 50 MHz fitted timing | Functional verification remains a separate phase |
| Sources | Synchronous replay ROM, audio/ADC adapters, source supervisor, explicit epoch stop/rearm | Physical live-source operation |
| Telemetry | Valid-only taps, nine-slot payload RAM, priority eviction, streamed DDR record construction | DDR/HPS sustained operation and loss measurements |
| HPS platform | Static Linux 6.12.109 DTS, noncached ring driver, GPIO48 owner, paired services | Matching kernel/DTB/module and target deployment |
| HPS/dashboard | Transport/control, source-health utility, waveform/spectrum/status/control UI | Main-demo capture and operation on the board |
| Board timing | Generated vendor IP; 63% ALM; 209 fitted pins checked; required timing, DDR and physical-route checks pass at all four corners | Board measurements and matched HPS/Linux operation |

The baseline architecture implementation is present in source. Production RTL
elaboration and host compilation check its language/integration boundary; they
do not establish arithmetic correctness, synthesis fit, timing closure or board
operation. Historical Step/R labels identify development history, not achieved
hardware evidence. Detailed source schedules and physical allocations are in the
[architecture design](architecture_design.md).

## System ownership

```text
source adapters
    -> trecap_source_core_integration (one core)
    -> core valid-only taps
    -> telemetry packetizers and priority FIFO
    -> record builder and FPGA DDR ring writer
    -> HPS DDR ring reader / UDP sender
    -> PC dashboard

PC command -> HPS parser/result cache -> CSR bridge
           -> FPGA shadow/commit owners -> applied result
```

The standalone `trecap_core_telemetry_top` is a reusable composition for an already-normalized source. The physical board instead uses the core inside `trecap_source_core_integration` and connects its taps to the telemetry-only HPS composition. These are alternative top-level arrangements, not two cores in one system.

## Decisions we preserve

| Decision | Reason |
| --- | --- |
| Core independent of HPS and board peripherals | Keep mathematical behavior reusable and isolate transport/platform dependencies |
| Exact fixed-point arithmetic and frozen coefficient artifacts | Make widths, rounding and representation explicit |
| Core owns error aggregates | Preserve sample alignment and keep HPS/PC out of real-time arithmetic |
| Telemetry may drop but never stall the core | Bound interference from DDR, Ethernet and display load |
| Single 50 MHz fabric clock | Keep core/control/DDR interfaces in one defined domain |
| Complete-frame audio FIFO crossings | Preserve coherent I2S words across the codec clock boundary |
| FPGA owns producer; HPS owns consumer | Give each DDR pointer one writer and a defined reset epoch |
| Shadow/commit configuration | Apply controls at documented safe boundaries rather than tearing live state |
| BRAM replay as default profile | Provide deterministic input independent of analog and codec setup |

The full interface and failure contracts remain in [interface_contracts.md](interface_contracts.md), [clock_reset_plan.md](clock_reset_plan.md), [cdc_plan.md](cdc_plan.md), and [de1soc_ddr_ring_ownership.md](de1soc_ddr_ring_ownership.md).

## Build and deployment sequence

1. Regenerate interface bindings and filelists from the shared contracts.
2. Elaborate production RTL and compile the reference/HPS software without running models or tests.
3. Generate the pinned Platform Designer/PLL implementation and reconcile its exported ports, address map and constraints.
4. Fit the FPGA and build the matched Linux kernel, board DTB and platform module using the source recipe.
5. Deploy the matched FPGA/kernel/DTB/runtime profile, establish bridge and GPIO ownership, and configure the DDR consumer lifecycle.
6. Operate the main BRAM profile, then LINE-IN. Optional ADC operation follows its own profile and hardware setup.

Platform Designer generation, full-board placement/routing and the required fitted timing gate have completed with Quartus Standard 20.1.1 Build 720. The current BRAM-profile native-12 I/O placement uses 20,280 of 32,070 ALMs, 55 of 397 memory blocks and 36 of 87 DSP blocks. All 209 fitted pins match their source contracts. The gate passes at all four available operating corners: worst 50 MHz fabric setup slack is +1.999 ns, and the largest ADC output data-path delay is 2.968 ns against its 5 ns allocation. The [implementation results](../results/fpga_implementation.md) retain the current evidence and historical checkpoints.

The installed Standard Edition evaluation mode still prevents assembly from producing a `.sof`; the completed timing analysis does not remove that image-generation limitation. No FPGA programming or board execution has occurred. Raw implementation records remain in ignored `runs/quartus/` directories. The matched target software build and deployment still remain.

## Transport and control behavior

The FPGA never waits for dashboard refresh or Ethernet delivery. FIFO/ring capacity limits produce attributable drop counters. HPS advances the consumer after forwarding or dropping a validated datagram; it does not accumulate an unbounded backlog for a disconnected PC.

Malformed DDR data stops the transport path and requires its documented reset/reconfigure lifecycle. It does not trigger byte-scanning recovery. Threshold and source changes follow their owning safe-boundary rules. Source changes must not silently combine unrelated metric epochs.

Version-1 commands retain the Revision-G baseline behavior. Version 2 explicitly adds request/result handling, sequencing, lifecycle and replay behavior. DDR addresses come from the trusted local runtime configuration, not network command payloads. See [de1soc_command_path.md](de1soc_command_path.md).

## Detailed implementation references

- [Build order and tools](build_order.md)
- [Repository ownership](repo_architecture.md)
- [Module inventory](module_inventory.md) and [module API](module_api.md)
- [Source/core integration](source_core_integration.md)
- [Core/telemetry composition](core_telemetry_composition.md)
- [BRAM replay boundary](de1soc_bram_replay_path.md)
- [Board top](de1soc_board_top_integration.md) and [Platform Designer wrapper](platform_designer_wrapper.md)
- [HPS transport](de1soc_hps_transport.md) and [dashboard setup](../bringup/pc_dashboard_bringup.md)

Verification testbench architecture, assertion/coverage design, final implementation results, analog characterization, and measured power evaluation are not defined by this plan.

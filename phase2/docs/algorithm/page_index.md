# Complete source-page index

Every page of the original 106-page PDF is represented below. The historical printed page number differs from the physical PDF page because the source has a cover and front matter.

[Read all content](complete_specification.md) | [Reading guide](README.md) | [Current profiles and RF](current_profiles_and_rf.md)

| PDF page | Printed page | Content on the page |
| --- | --- | --- |
| [1](baseline/page-001.md) | Cover | T-RECAP: Transform-domain Representation and Energy-aware Computation Accelerator with Controlled Precision / Phase 2 Algorithm, Ethernet/HPS Telemetry, and Repository Architecture Specification |
| [2](baseline/page-002.md) | i | Executive Summary |
| [3](baseline/page-003.md) | ii | Contents |
| [4](baseline/page-004.md) | iii | Contents |
| [5](baseline/page-005.md) | iv | Contents |
| [6](baseline/page-006.md) | v | Contents |
| [7](baseline/page-007.md) | vi | Contents |
| [8](baseline/page-008.md) | vii | Contents |
| [9](baseline/page-009.md) | viii | Contents |
| [10](baseline/page-010.md) | ix | Contents |
| [11](baseline/page-011.md) | x | List of Algorithms |
| [12](baseline/page-012.md) | xi | List of Tables |
| [13](baseline/page-013.md) | xii | List of Tables |
| [14](baseline/page-014.md) | 1 | Part I - Core Algorithm and Signoff Contract / 1 Overview and Scope / 1.1 Purpose / 1.2 Problem statement / 1.3 Continuity from Phase 1 |
| [15](baseline/page-015.md) | 2 | 1.4 Core boundary / 2 Parameters, Timing, and Finite-Stream Policy / 2.1 Baseline parameters / 2.2 Frame timing |
| [16](baseline/page-016.md) | 3 | 2.3 Finite-stream signoff policy |
| [17](baseline/page-017.md) | 4 | 3 Bit-Accurate Fixed-Point Contract / 3.1 Sample range and saturation / 3.2 Arithmetic shift and rounded right shift / 3.3 Coefficient quantization and storage widths |
| [18](baseline/page-018.md) | 5 | 3.4 Fixed-point products and complex multiplication |
| [19](baseline/page-019.md) | 6 | 3.5 Internal width schedule / 4 STFT/WOLA Core Mathematics / 4.1 Periodic square-root Hann window |
| [20](baseline/page-020.md) | 7 | 4.2 Analysis windowing and normalized FFT / 4.3 Hermitian canonicalization / 4.4 Magnitude-squared mask |
| [21](baseline/page-021.md) | 8 | 4.5 Protection rules and masked spectrum / 4.6 Unscaled IFFT, synthesis window, and WOLA |
| [22](baseline/page-022.md) | 9 | 5 Normative Core Algorithm Tables / Algorithm 1 Finite-stream Phase 2 core operator with full-tail scoring / Algorithm 2 ProcessFrameAnalysisMask: frame construction, FFT, canonicalization, masking, |
| [23](baseline/page-023.md) | 10 | Algorithm 3 ProcessFrameSynthesisWOLA: IFFT, synthesis window, and WOLA accumulation / 5.1 Required invariants |
| [24](baseline/page-024.md) | 11 | 6 Exact Custom FFT/IFFT Integer Algorithms / 6.1 Bit reversal and twiddle tables / Algorithm 4 Exact custom FFTnorm integer algorithm |
| [25](baseline/page-025.md) | 12 | Algorithm 5 Exact custom IFFTunscaled integer algorithm / 7 Metrics and Artifact Contract / 7.1 Spectral metrics |
| [26](baseline/page-026.md) | 13 | 7.2 Time-domain quality metrics / 7.3 Canonical memory-file encoding |
| [27](baseline/page-027.md) | 14 | 7.4 Canonical SHA-256 hashing / 7.5 Normative coefficient artifacts / 7.6 Frozen stream artifacts / 7.7 Artifact line counts |
| [28](baseline/page-028.md) | 15 | 7.8 Required artifacts |
| [29](baseline/page-029.md) | 16 | 7.9 CSV field contracts / 7.10 JSON integer rule and schemas |
| [30](baseline/page-030.md) | 17 | Continuation of the preceding source page |
| [31](baseline/page-031.md) | 18 | Continuation of the preceding source page |
| [32](baseline/page-032.md) | 19 | 8 Signoff Test Suite, Generators, and Acceptance Criteria / 8.1 Required test-vector classes |
| [33](baseline/page-033.md) | 20 | 8.2 Frozen generator algorithms |
| [34](baseline/page-034.md) | 21 | 8.3 Golden-model quality bounds |
| [35](baseline/page-035.md) | 22 | 8.4 Acceptance criteria / 9 Live Source Abstraction and Threshold Mapping |
| [36](baseline/page-036.md) | 23 | 10 Throughput and Power Interpretation / 11 Conclusion |
| [37](baseline/page-037.md) | 24 | Part II - Ethernet/HPS DDR Telemetry and Control Architecture / 12 Purpose and Scope / 12.1 Purpose / 12.2 Relationship to Part I / 12.3 Non-Goals |
| [38](baseline/page-038.md) | 25 | 13 System Boundary and Ownership Rules / 13.1 Core Ownership Rule / 13.2 Transport Ownership Rule / 13.3 Non-Stall Rule |
| [39](baseline/page-039.md) | 26 | 13.4 Signoff Rule / 14 Physical Connection Profile / 14.1 Required Connections / 14.2 Recommended Demo Topology / 15 Level-3 Architecture / 15.1 Top-Level Dataflow |
| [40](baseline/page-040.md) | 27 | 15.2 Functional Blocks / 15.3 DE1-SoC Bridge and Address-Mapping Assumption |
| [41](baseline/page-041.md) | 28 | 16 CSR Register Contract / 16.1 Register Access Rules / 16.2 CSR Map |
| [42](baseline/page-042.md) | 29 | Continuation of the preceding source page |
| [43](baseline/page-043.md) | 30 | 16.3 Version Compatibility Rule / 16.4 CSR Bit Definitions |
| [44](baseline/page-044.md) | 31 | 16.5 Spectrum Packet Selection Rule |
| [45](baseline/page-045.md) | 32 | Continuation of the preceding source page |
| [46](baseline/page-046.md) | 33 | 16.6 Atomic 64-bit Pointer Transfer |
| [47](baseline/page-047.md) | 34 | 16.7 Core Counter Snapshot Rule / 16.8 Sticky-Flag Clear Rule / 16.9 Command-Reject Counter Ownership / 16.10 Packet-FIFO Drop Accounting Rule |
| [48](baseline/page-048.md) | 35 | 16.11 Threshold Commit Rule / 16.12 Source-Mode Change Rule / 16.13 Clock-Domain Crossing Requirements |
| [49](baseline/page-049.md) | 36 | 17 DDR Ring Buffer Contract / 17.1 Ring Size, Base Address, and Alignment / 17.2 Absolute Pointers |
| [50](baseline/page-050.md) | 37 | 17.3 Ring Initialization Rule / 17.4 Free Space Rule Including Wrap / 17.5 Record Alignment and WRAP Record |
| [51](baseline/page-051.md) | 38 | 17.6 Memory Coherency Requirement / 18 DDR Packet Record Format / 18.1 Common Header |
| [52](baseline/page-052.md) | 39 | 18.2 Header Flags |
| [53](baseline/page-053.md) | 40 | 18.3 Timestamp Semantics / 18.4 Packet Types / 18.5 Packet Validation Rules |
| [54](baseline/page-054.md) | 41 | 18.6 Maximum Payload Rules |
| [55](baseline/page-055.md) | 42 | 18.7 Commit Protocol / Algorithm 6 FPGA DDR record write and commit protocol with correct wrap-space accounting |
| [56](baseline/page-056.md) | 43 | 19 Telemetry Payload Formats / 19.1 Magnitude Compression Operator / 19.2 WAVE Payload |
| [57](baseline/page-057.md) | 44 | 19.3 SPEC129 Payload / 19.4 SPEC64 Payload |
| [58](baseline/page-058.md) | 45 | 19.5 METRICS Payload |
| [59](baseline/page-059.md) | 46 | 19.6 STATUS Ownership and HPS Patch Rule |
| [60](baseline/page-060.md) | 47 | 19.7 STATUS Payload |
| [61](baseline/page-061.md) | 48 | 20 HPS UDP Streamer Contract / 20.1 HPS Responsibilities / 20.2 UDP Datagrams and Fragmentation Policy / 20.3 Nonblocking Send Rule |
| [62](baseline/page-062.md) | 49 | 20.4 HPS Streamer Algorithm / Algorithm 7 HPS DDR ring consumer and UDP streamer |
| [63](baseline/page-063.md) | 50 | 20.5 Runtime Packet Validation Checklist / 20.6 Ethernet Port Assignments |
| [64](baseline/page-064.md) | 51 | 21 PC Command Contract / 21.1 Command Header / 21.2 Command Types and Valid Ranges |
| [65](baseline/page-065.md) | 52 | 21.3 Command Source Rule and Security Scope / 21.4 Command Safety Rules / 22 Telemetry Scheduling and Bandwidth / 22.1 Frame Rate / 22.2 Recommended Packet Rates |
| [66](baseline/page-066.md) | 53 | 22.3 Bandwidth Estimates / 23 Memory Allocation and Cache Policy / 23.1 Option A: Reserved DDR Region / 23.2 Option B: DMA-Coherent Kernel Driver / 24 PC Dashboard Contract / 24.1 Required Plots |
| [67](baseline/page-067.md) | 54 | 24.2 Dashboard Update Rate / 24.3 Packet Loss Handling / 25 Startup and Shutdown Sequence / 25.1 Startup Sequence |
| [68](baseline/page-068.md) | 55 | 25.2 Shutdown Sequence / 26 Failure Modes and Required Counters |
| [69](baseline/page-069.md) | 56 | 27 Acceptance Criteria |
| [70](baseline/page-070.md) | 57 | Continuation of the preceding source page |
| [71](baseline/page-071.md) | 58 | 28 First Implementation Scope / 28.1 Required First-Demo Scope / 28.2 Deferred Optional Scope |
| [72](baseline/page-072.md) | 59 | 29 Development Milestones / 30 Conclusion |
| [73](baseline/page-073.md) | 60 | Part III - Core Implementation Repository Architecture / 31 Repository Architecture Executive Summary |
| [74](baseline/page-074.md) | 61 | 32 Scope and Inputs / 32.1 Normative inputs / 32.2 In scope |
| [75](baseline/page-075.md) | 62 | 32.3 Out of scope / 33 Architectural Principles / 33.1 Non-negotiable implementation rules / 33.2 Ownership diagram |
| [76](baseline/page-076.md) | 63 | 34 Repository Layout / 34.1 Normative top-level tree |
| [77](baseline/page-077.md) | 64 | Continuation of the preceding source page |
| [78](baseline/page-078.md) | 65 | 34.2 Directory responsibilities |
| [79](baseline/page-079.md) | 66 | 35 Generated Shared Contract Flow / 35.1 Purpose / 35.2 Schema files |
| [80](baseline/page-080.md) | 67 | 35.3 Generated outputs / 35.4 Generated-file commit policy |
| [81](baseline/page-081.md) | 68 | 35.5 Generated filelists / 35.6 Normative CSR map rule |
| [82](baseline/page-082.md) | 69 | 36 SystemVerilog Interface and Typedef Baseline / 36.1 Package organization / 36.2 Core sample and frame typedefs / 36.3 Telemetry record typedefs |
| [83](baseline/page-083.md) | 70 | 36.4 Core tap interface rule |
| [84](baseline/page-084.md) | 71 | 37 Module API, Parameter, and Naming Rules / 37.1 Parameter ownership / 37.2 Port naming rules / 37.3 Coding style baseline |
| [85](baseline/page-085.md) | 72 | 38 RTL Layer Ownership / 38.1 Layer partition / 38.2 Dataflow |
| [86](baseline/page-086.md) | 73 | 39 RTL Module Inventory / 39.1 Source modules / 39.2 Core modules |
| [87](baseline/page-087.md) | 74 | 39.3 FFT modules / 39.4 Telemetry modules / 39.5 HPS bridge modules |
| [88](baseline/page-088.md) | 75 | 39.6 DE1-SoC platform modules / 39.7 Top-level build variants |
| [89](baseline/page-089.md) | 76 | 40 Dependency Rules |
| [90](baseline/page-090.md) | 77 | 41 Clock and Reset Ownership / 41.1 Clock-domain baseline / 41.2 CDC rules / 42 Platform Designer and DE1-SoC Ownership / 42.1 Platform files |
| [91](baseline/page-091.md) | 78 | 42.2 Platform Designer generated-artifact policy / 42.3 Bridge assumptions |
| [92](baseline/page-092.md) | 79 | 42.4 Address map file / 43 Software Implementation Layout / 43.1 Golden software / 43.2 HPS software |
| [93](baseline/page-093.md) | 80 | 43.3 HPS runtime configuration manifest / 43.4 PC dashboard software |
| [94](baseline/page-094.md) | 81 | 44 Runtime and Build Profiles / 44.1 Profile separation rule / 44.2 Example profile / 45 Coefficient ROM and Memory Primitive Policy / 45.1 Coefficient ROM ownership |
| [95](baseline/page-095.md) | 82 | 45.2 Memory primitive policy / 46 Artifact and Data Layout / 46.1 Artifact directories |
| [96](baseline/page-096.md) | 83 | 46.2 Artifact authority rule / 47 Legacy and Deprecated Document Quarantine / 47.1 Phase 1 quarantine / 47.2 Deprecated Phase 2 warning |
| [97](baseline/page-097.md) | 84 | 48 Build System Architecture / 48.1 Required build targets |
| [98](baseline/page-098.md) | 85 | 49 Implementation Milestones / 50 Implementation Cuts / 50.1 Core Implementation Cut C0 |
| [99](baseline/page-099.md) | 86 | 50.2 Transport Implementation Cut T0 / 51 First Implementation Scope / 51.1 Core-first required now: Cut C0 |
| [100](baseline/page-100.md) | 87 | 51.2 First full-demo scope after C0/T0 / 51.3 Deferred / 52 Repository Acceptance Criteria |
| [101](baseline/page-101.md) | 88 | 53 Conclusion |
| [102](baseline/page-102.md) | 89 | Appendices / A Vendor FFT IP Contract Checklist / B Phase 1 Mathematical Anchor |
| [103](baseline/page-103.md) | 90 | C Repository Recommended File Inventory |
| [104](baseline/page-104.md) | 91 | D Repository Minimum Documentation Files |
| [105](baseline/page-105.md) | 92 | Continuation of the preceding source page |
| [106](baseline/page-106.md) | 93 | References |

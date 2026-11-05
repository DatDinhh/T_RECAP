# Project naming and scope

**T-RECAP: Threshold-based Reduction and Encoding for Configurable Analysis Pipelines**

Use this full name in current project descriptions, presentations and reports. The short name remains **T-RECAP**. The project applies one spectral-processing architecture to audio, recorded acceleration and RF inputs, with application-specific consumers on the laptop.

## What the name means

| Letters | Words | Meaning in this project |
|---|---|---|
| T | Threshold-based | An adjustable squared-magnitude threshold controls which spectral components are suppressed. |
| R | Reduction | Removing eligible components reduces retained spectral content. Sparse packet size depends on the signal, threshold and format overhead. |
| E | Encoding | TSP1 encodes spectral powers, metadata and retained-bin indices for a compatible consumer. Reconstructed Y is a separate sample output. |
| C | Configurable | TSH2 and TRF1 select real-sample or I/Q input at build time. Host software configures threshold and packet mode for each finite run. |
| A | Analysis | Application evaluation examines audio fidelity and archive size, walking-event errors, and RF background and message retention. |
| P | Pipelines | Input preparation, FPGA processing and laptop consumers form distinct end-to-end application workflows around the same numerical core. |

The shared FPGA path performs windowing, FFT, thresholding, IFFT and weighted overlap-add. Audio and acceleration use the real-sample input configuration. RF uses an FPGA I/Q frontend that presents the same real-sample contract to the core. Each fitted image has its own host register interface. Both builds use the documented fixed-point widths and transform geometry.

Reconstructed Y supplies FLAC encoding, step-event detection and RF recovery. Phase-free TSP1 packets supply spectral inspection and compatible sparse consumers. The [three application studies](applications/README.md) measure the benefits and information loss separately for their signals and consumers. The [unified architecture atlas](architecture/system/README.md) maps the implementation from system responsibilities to module internals.

## Hardware implementation and interface names

The documentation adopts **TSH** as **T-RECAP Signal-processing Hardware**, the agreed naming convention for those interface identifiers.

- **TSH1** is version 1, the earlier Phase 2 implementation used in the historical 1,024-sample resident-compute comparison.
- **TSH2** is version 2, the finite-record real-sample configuration used for audio and captured acceleration.
- **TRF1** identifies the recorded-I/Q configuration and its host register interface.

TSH1 and TSH2 both belong to Phase 2. Their version numbers are independent of the project's semester phases. The separate Phase 1 demonstration uses a Haar transform.

HPS software uses memory-mapped control/status registers and FIFO data ports to configure processing, transfer samples and results, and inspect counters and faults. FPGA datapath modules perform the numerical processing. Laptop software prepares inputs and consumes the returned outputs through each profile's documented transport workflow.

## Relationship to earlier documents

The previous audio-specific full name was *Threshold-based Reduction and Encoding for Controlled Audio Processing*. The current expansion describes the three application classes without changing the short name.

The original specification used *Transform-domain Representation and Energy-aware Computation Accelerator with Controlled Precision*. That title remains in original specification material and historical records as part of their identity.

The [integrated specification](specs/README.md) retains its original PDF, date, revision identity and hash. Reports using the short name TRECAP refer to the same project. Numerical contracts, interfaces and recorded verification results retain their original identities.

Repository URLs, filenames, code identifiers and the implementation/format labels TSH1, TSH2, TRF1, THR2 and TSP1 remain stable. Their meanings are explained in the [terms and abbreviations](../README.md#terms-and-abbreviations).

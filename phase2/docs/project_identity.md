# Project naming and scope

**T-RECAP: Threshold-based Reduction and Encoding for Controlled Audio Processing**

This is the current full project name. Use it in new project descriptions, presentations and reports. The short name remains **T-RECAP**.

## What the name means

| Letters | Words | Meaning in this project |
|---|---|---|
| T | Threshold-based | An adjustable squared-magnitude threshold controls which spectral coefficients are suppressed. |
| R | Reduction | Sparse output reduces the number of spectral values carried when bins are omitted. Reduction depends on the signal, threshold and format overhead. |
| E | Encoding | Retained spectral powers are encoded with metadata and bin indices for a compatible downstream consumer. |
| C | Controlled | Threshold selection controls the tradeoff between retained signal information and data reduction. The current finite-file profile fixes the threshold for each processing run. |
| A | Audio | The evaluated input consists of finite audio files. |
| P | Processing | The FPGA performs FFT, thresholding and IFFT/WOLA reconstruction, while the host consumes the spectral output. |

The objective is to reduce the spectral data a compatible host must receive and process while measuring the information lost at each threshold. The reconstructed waveform supports listening comparisons and numerical distortion measurements. Sparse spectral packets carry powers without phase and are separate from the reconstructed audio stream.

The name describes the implemented functions. It does not establish electrical energy savings, faster computation than the laptop CPU, AI inference acceleration or qualified live microphone operation. The current fixed-point precision remains fixed. See the [results and measurement boundaries](project_overview/README.md) and [current architecture](architecture/tsh2/README.md).

## Relationship to earlier documents

The former expansion was *Transform-domain Representation and Energy-aware Computation Accelerator with Controlled Precision*. It remains in original specification material and historical records as part of their identity, rather than as the current project name.

The [integrated specification](specs/README.md) retains its original PDF, date, revision identity and hash. Existing verification reports that use the short name TRECAP still refer to this same project. The naming update does not revise numerical contracts, interfaces, test results or historical claims.

Repository URLs, filenames, code identifiers and the implementation/format labels TSH1, TSH2, THR2 and TSP1 remain stable. Their meanings are explained in the [terms and abbreviations](../README.md#terms-and-abbreviations).

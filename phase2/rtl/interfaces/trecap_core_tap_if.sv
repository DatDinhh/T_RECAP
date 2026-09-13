// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL interface.
// Layer: rtl/interfaces/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Valid-only observation tap bundle from the mathematical core to telemetry.
// Contract: This interface never provides ready/backpressure into the sample, frame, FFT/IFFT,
//           WOLA, mask, or metrics path. Telemetry may drop/count tap observations, but the core
//           continues running.
// Generated dependencies: trecap_core_pkg, trecap_iface_pkg.

`default_nettype none

// T-RECAP core tap interface. These are already-computed observations, not a control path.
interface trecap_core_tap_if
  import trecap_core_pkg::*;
  import trecap_iface_pkg::*;
#(
    parameter int unsigned BIN_IDX_W = (T_UNIQUE_BINS <= 1) ? 1 : $clog2(T_UNIQUE_BINS)
) (
    input logic clk,
    input logic rst_n
);

    trecap_core_tap_sample_t sample;
    trecap_core_tap_frame_t  frame;

    logic                    bin_valid;
    logic [63:0]             bin_frame_idx;
    logic [BIN_IDX_W-1:0]    bin_idx;
    logic signed [T_CAN_W-1:0] bin_re;
    logic signed [T_CAN_W-1:0] bin_im;
    logic [T_MAG2_W-1:0]     bin_mag2;
    logic                    bin_pre_mask;
    logic                    bin_mask;
    logic                    bin_eligible;
    logic                    bin_last;

    logic                    any_valid;
    logic                    spectrum_valid;

    assign spectrum_valid = bin_valid;
    assign any_valid = sample.valid || frame.valid || bin_valid;

    function automatic logic sample_event_valid();
        return sample.valid;
    endfunction

    function automatic logic frame_event_valid();
        return frame.valid;
    endfunction

    function automatic logic bin_event_valid();
        return bin_valid;
    endfunction

    modport core_source (
        input  clk,
        input  rst_n,
        output sample,
        output frame,
        output bin_valid,
        output bin_frame_idx,
        output bin_idx,
        output bin_re,
        output bin_im,
        output bin_mag2,
        output bin_pre_mask,
        output bin_mask,
        output bin_eligible,
        output bin_last,
        input  any_valid,
        input  spectrum_valid
    );

    modport telemetry_sink (
        input clk,
        input rst_n,
        input sample,
        input frame,
        input bin_valid,
        input bin_frame_idx,
        input bin_idx,
        input bin_re,
        input bin_im,
        input bin_mag2,
        input bin_pre_mask,
        input bin_mask,
        input bin_eligible,
        input bin_last,
        input any_valid,
        input spectrum_valid
    );

    modport monitor (
        input clk,
        input rst_n,
        input sample,
        input frame,
        input bin_valid,
        input bin_frame_idx,
        input bin_idx,
        input bin_re,
        input bin_im,
        input bin_mag2,
        input bin_pre_mask,
        input bin_mask,
        input bin_eligible,
        input bin_last,
        input any_valid,
        input spectrum_valid
    );

`ifndef SYNTHESIS
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // No state to reset. The block only gates simulation checks after reset release.
        end else begin
            if (bin_last && !bin_valid) begin
                $error("trecap_core_tap_if: bin_last asserted without bin_valid");
            end
            if (bin_valid && (bin_idx >= BIN_IDX_W'(T_UNIQUE_BINS))) begin
                $error("trecap_core_tap_if: bin_idx out of unique-bin range");
            end
            if (frame.valid && (frame.stats.unique_bins > 32'(T_UNIQUE_BINS))) begin
                $error("trecap_core_tap_if: frame.stats.unique_bins exceeds T_UNIQUE_BINS");
            end
            if (frame.valid && (frame.stats.eligible_unique_bins > frame.stats.unique_bins)) begin
                $error("trecap_core_tap_if: eligible_unique_bins exceeds unique_bins");
            end
            if (frame.valid &&
                (frame.stats.eligible_suppressed_bins > frame.stats.eligible_unique_bins)) begin
                $error("trecap_core_tap_if: eligible_suppressed_bins exceeds eligible_unique_bins");
            end
        end
    end
`endif

endinterface : trecap_core_tap_if

`default_nettype wire

// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/hps_bridge/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Reusable CSR shadow/commit primitive for multiword controls.
// Contract: A multiword shadow value becomes active only through explicit commit and,
//           when configured, at a caller-supplied safe boundary.
// Generated dependencies: none.

`default_nettype none

// Same-clock shadow/commit cell.
//
// This module intentionally does not perform CDC. If active_value_o or active_update_pulse_o must
// cross into another clock domain, the hps_bridge top-level shall wrap that transfer with a
// documented CDC mechanism such as sync_pulse, sync_bus_snapshot, or an async FIFO.
//
// Protocol:
//   - shadow_we_i updates selected bits of the shadow value using shadow_wmask_i.
//   - commit_pulse_i captures the current post-write shadow value into pending_value_o.
//   - active_value_o updates only when the commit is accepted and the safe boundary is present.
//   - With REJECT_WRITES_WHILE_PENDING=1, shadow writes are rejected while a previous commit waits
//     for its safe boundary. This avoids changing the value associated with an accepted pending
//     commit.
//   - clear_i always cancels a pending commit. With CLEAR_VALUES_ON_CLEAR=1 it also restores the
//     shadow and active values; the default preserves their historical behavior across soft clear.
module trecap_csr_shadow_commit #(
    parameter int unsigned WIDTH = 32,
    parameter logic [WIDTH-1:0] RESET_VALUE = '0,
    parameter bit APPLY_ON_SAFE_BOUNDARY = 1'b1,
    parameter bit REJECT_WRITES_WHILE_PENDING = 1'b1,
    parameter bit CLEAR_VALUES_ON_CLEAR = 1'b0
) (
    input  logic             clk,
    input  logic             rst_n,

    input  logic             clear_i,

    input  logic             shadow_we_i,
    input  logic [WIDTH-1:0] shadow_wdata_i,
    input  logic [WIDTH-1:0] shadow_wmask_i,

    input  logic             commit_pulse_i,
    input  logic             safe_boundary_i,
    input  logic             commit_allowed_i,
    input  logic             shadow_value_valid_i,

    output logic [WIDTH-1:0] shadow_value_o,
    output logic [WIDTH-1:0] active_value_o,
    output logic [WIDTH-1:0] pending_value_o,
    output logic             pending_o,

    output logic             shadow_accept_pulse_o,
    output logic             shadow_reject_pulse_o,
    output logic             commit_accept_pulse_o,
    output logic             commit_reject_pulse_o,
    output logic             active_update_pulse_o
);

    logic [WIDTH-1:0] shadow_q;
    logic [WIDTH-1:0] active_q;
    logic [WIDTH-1:0] pending_value_q;
    logic             pending_q;
    logic [WIDTH-1:0] shadow_next;
    logic             commit_accept;
    logic             apply_pending;

    // A commit normally arrives on a distinct CSR address, so its W1P payload and the helper's
    // don't-care shadow mask must not alter the committed value. Preserve the post-write behavior
    // only for callers that intentionally assert shadow_we_i and commit_pulse_i together.
    assign shadow_next = shadow_we_i ?
                         ((shadow_q & ~shadow_wmask_i) |
                          (shadow_wdata_i & shadow_wmask_i)) :
                         shadow_q;
    assign commit_accept = commit_pulse_i &&
                           !pending_q &&
                           commit_allowed_i &&
                           shadow_value_valid_i;
    assign apply_pending = pending_q &&
                           (APPLY_ON_SAFE_BOUNDARY ? safe_boundary_i : 1'b1);

    assign shadow_value_o = shadow_q;
    assign active_value_o = active_q;
    assign pending_value_o = pending_value_q;
    assign pending_o = pending_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            shadow_q <= RESET_VALUE;
            active_q <= RESET_VALUE;
            pending_value_q <= RESET_VALUE;
            pending_q <= 1'b0;
            shadow_accept_pulse_o <= 1'b0;
            shadow_reject_pulse_o <= 1'b0;
            commit_accept_pulse_o <= 1'b0;
            commit_reject_pulse_o <= 1'b0;
            active_update_pulse_o <= 1'b0;
        end else begin
            shadow_accept_pulse_o <= 1'b0;
            shadow_reject_pulse_o <= 1'b0;
            commit_accept_pulse_o <= 1'b0;
            commit_reject_pulse_o <= 1'b0;
            active_update_pulse_o <= 1'b0;

            if (clear_i) begin
                pending_q <= 1'b0;
                pending_value_q <= RESET_VALUE;
                if (CLEAR_VALUES_ON_CLEAR) begin
                    shadow_q <= RESET_VALUE;
                    active_q <= RESET_VALUE;
                end
            end else begin
                if (shadow_we_i) begin
                    if (pending_q && REJECT_WRITES_WHILE_PENDING) begin
                        shadow_reject_pulse_o <= 1'b1;
                    end else begin
                        shadow_q <= shadow_next;
                        shadow_accept_pulse_o <= 1'b1;
                    end
                end

                if (commit_pulse_i) begin
                    if (!commit_accept) begin
                        commit_reject_pulse_o <= 1'b1;
                    end else begin
                        commit_accept_pulse_o <= 1'b1;
                        pending_value_q <= shadow_next;
                        if (APPLY_ON_SAFE_BOUNDARY && !safe_boundary_i) begin
                            pending_q <= 1'b1;
                        end else begin
                            active_q <= shadow_next;
                            pending_q <= 1'b0;
                            active_update_pulse_o <= 1'b1;
                        end
                    end
                end else if (apply_pending) begin
                    active_q <= pending_value_q;
                    pending_q <= 1'b0;
                    active_update_pulse_o <= 1'b1;
                end
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (WIDTH < 1) begin
            $fatal(1, "trecap_csr_shadow_commit: WIDTH must be at least 1");
        end
    end
`endif

endmodule : trecap_csr_shadow_commit

`default_nettype wire

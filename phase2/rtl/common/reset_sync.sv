// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/common/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Active-low reset synchronizer with asynchronous assertion and synchronous deassertion.
// Contract: Reset deassertion shall be synchronized per clock domain using at least two flip-flops.
// Generated dependencies: none; this reusable primitive is intentionally package-independent.

`default_nettype none

// Reset synchronizer for one destination clock domain.
//
// Assertion behavior:
//   async_rst_n = 0 drives rst_n low immediately through asynchronous flop reset.
//
// Deassertion behavior:
//   rst_n returns high only after STAGES_SAFE destination clock edges.
//
// This module is not a general CDC primitive. It is only for reset release.
module trecap_reset_sync #(
    parameter int unsigned STAGES = 2,
    // Most state releases on the rising edge.  Set this only for state whose active clock edge is
    // the falling edge (for example the I2S DAC serializer).  Assertion remains asynchronous in
    // both variants.
    parameter bit          RELEASE_ON_NEGEDGE = 1'b0
) (
    input  logic clk,
    input  logic async_rst_n,
    output logic rst_n
);

    localparam int unsigned STAGES_SAFE = (STAGES < 2) ? 2 : STAGES;

    (* async_reg = "true" *)
    (* preserve = "true" *)
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED" *)
    logic [STAGES_SAFE-1:0] sync_q;

    generate
        if (RELEASE_ON_NEGEDGE) begin : g_release_negedge
            always_ff @(negedge clk or negedge async_rst_n) begin
                if (!async_rst_n) begin
                    sync_q <= '0;
                end else begin
                    sync_q <= {sync_q[STAGES_SAFE-2:0], 1'b1};
                end
            end
        end else begin : g_release_posedge
            always_ff @(posedge clk or negedge async_rst_n) begin
                if (!async_rst_n) begin
                    sync_q <= '0;
                end else begin
                    sync_q <= {sync_q[STAGES_SAFE-2:0], 1'b1};
                end
            end
        end
    endgenerate

    assign rst_n = sync_q[STAGES_SAFE-1];

`ifndef SYNTHESIS
    initial begin
        if (STAGES < 2) begin
            $warning(
                "trecap_reset_sync: STAGES=%0d requested; using STAGES_SAFE=%0d",
                STAGES,
                STAGES_SAFE
            );
        end
    end
`endif

endmodule : trecap_reset_sync

`default_nettype wire

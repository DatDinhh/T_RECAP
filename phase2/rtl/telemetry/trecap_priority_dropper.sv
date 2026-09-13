// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/telemetry/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Priority admission helper for the telemetry packet FIFO.
// Contract: Implements Revision G resident-record eviction policy. This module does not know
//           packet types, CSR offsets, DDR ring addresses, HPS software, or Ethernet behavior.

`default_nettype none

// Selects whether a new telemetry record may enter a full priority-aware packet FIFO.
//
// Resident entries are presented in FIFO order: index 0 is the oldest resident record and higher
// indices are newer records. If storage is already available, the incoming record is admitted
// without eviction. If storage is full, this helper looks for an evictable resident whose priority is
// lower than the incoming record priority, then selects the lowest-priority resident; ties select the
// oldest matching resident. If no such resident exists, the incoming record is shed.
//
// Priority convention follows trecap_record_meta_t.drop_priority generated from the packet schema:
//   0 = lowest priority, 3 = highest priority.
module trecap_priority_dropper #(
    parameter int unsigned RECORD_DEPTH = 8,
    parameter int unsigned PRIORITY_W   = 2
) (
    input  logic                                      request_i,
    input  logic                                      incoming_malformed_i,
    input  logic                                      storage_available_i,
    input  logic [PRIORITY_W-1:0]                     incoming_priority_i,

    input  logic [RECORD_DEPTH-1:0]                   resident_valid_i,
    input  logic [RECORD_DEPTH-1:0]                   resident_evictable_i,
    input  logic [(RECORD_DEPTH*PRIORITY_W)-1:0]      resident_priority_flat_i,

    output logic                                      admit_o,
    output logic                                      admit_without_evict_o,
    output logic                                      admit_with_evict_o,
    output logic                                      evict_valid_o,
    output logic [((RECORD_DEPTH <= 1) ? 1 : $clog2(RECORD_DEPTH))-1:0]
                                                        evict_index_o,
    output logic [PRIORITY_W-1:0]                     evict_priority_o,
    output logic                                      drop_incoming_o,
    output logic                                      lower_priority_available_o
);

    localparam int unsigned IDX_W = (RECORD_DEPTH <= 1) ? 1 : $clog2(RECORD_DEPTH);

    function automatic logic [PRIORITY_W-1:0] resident_priority_at(
        input logic [(RECORD_DEPTH*PRIORITY_W)-1:0] flat,
        input int unsigned                         idx
    );
        return flat[(idx * PRIORITY_W) +: PRIORITY_W];
    endfunction : resident_priority_at

    logic [IDX_W-1:0]         best_index;
    logic [PRIORITY_W-1:0]    best_priority;
    logic                     found_lower;
    logic [PRIORITY_W-1:0]    candidate_priority;

    always_comb begin
        best_index = '0;
        best_priority = '1;
        found_lower = 1'b0;
        lower_priority_available_o = 1'b0;

        for (int unsigned i = 0; i < RECORD_DEPTH; i++) begin
            candidate_priority = resident_priority_at(resident_priority_flat_i, i);
            if (resident_valid_i[i] && resident_evictable_i[i] &&
                (candidate_priority < incoming_priority_i)) begin
                lower_priority_available_o = 1'b1;

                // Choose the lowest priority resident. For equal priority, keep the first/oldest
                // candidate because we do not update best_index on equality.
                if (!found_lower || (candidate_priority < best_priority)) begin
                    found_lower = 1'b1;
                    best_priority = candidate_priority;
                    best_index = i;
                end
            end
        end

        admit_without_evict_o = request_i && !incoming_malformed_i && storage_available_i;
        admit_with_evict_o = request_i && !incoming_malformed_i && !storage_available_i && found_lower;
        admit_o = admit_without_evict_o || admit_with_evict_o;

        evict_valid_o = admit_with_evict_o;
        evict_index_o = best_index;
        evict_priority_o = found_lower ? best_priority : '0;

        drop_incoming_o = request_i &&
                          (incoming_malformed_i || (!storage_available_i && !found_lower));
    end

`ifndef SYNTHESIS
    initial begin
        if (RECORD_DEPTH < 1) begin
            $fatal(1, "trecap_priority_dropper: RECORD_DEPTH must be at least 1");
        end
        if (PRIORITY_W < 1) begin
            $fatal(1, "trecap_priority_dropper: PRIORITY_W must be at least 1");
        end
    end

    always_comb begin
        if (evict_valid_o && storage_available_i) begin
            $error("trecap_priority_dropper: eviction selected even though storage is available");
        end
        if (evict_valid_o && !resident_valid_i[evict_index_o]) begin
            $error("trecap_priority_dropper: selected invalid resident for eviction");
        end
        if (evict_valid_o && !resident_evictable_i[evict_index_o]) begin
            $error("trecap_priority_dropper: selected non-evictable resident for eviction");
        end
    end
`endif

endmodule : trecap_priority_dropper

`default_nettype wire

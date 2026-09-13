// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/hps_bridge/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Strict Avalon-MM agent adapter for the HPS-visible CSR leaf.
// Contract: Decode the complete lightweight-aperture byte address before forwarding one aligned,
//           full-width, single-beat request to the private CSR request/response interface.
// Generated dependencies: none.

`default_nettype none

// T-RECAP Avalon-MM CSR adapter.
//
// Address contract:
//   - avs_address_i is a BYTE address relative to the HPS lightweight aperture.
//   - CSR_BASE_ADDR selects one 2**CSR_ADDR_W-byte window and must be window aligned.
//   - All AVMM_ADDR_W bits participate in decode; upper bits are never silently truncated.
//
// Transfer contract:
//   - exactly one transaction may be outstanding;
//   - read and write are mutually exclusive;
//   - only aligned 32-bit accesses with byteenable=4'b1111 and burstcount=1 are accepted;
//   - locally rejected requests are never presented to the CSR leaf;
//   - every accepted Avalon read/write receives exactly one corresponding response;
//   - response valid is never asserted in the request-acceptance cycle.
//
// Native CSR timing contract:
//   - csr_valid_o remains asserted, with stable request fields, until csr_ready_i;
//   - the connected trecap_csr_bank returns rdata/error one cycle after request acceptance;
//   - a failed read may assert csr_error_i without csr_rvalid_i and still completes as SLVERR;
//   - the bank owns leaf-level command-reject accounting. local_reject_pulse_o covers only
//     requests rejected here before a leaf request is issued.
module trecap_avmm_csr_adapter #(
    parameter int unsigned AVMM_ADDR_W       = 21,
    parameter int unsigned CSR_ADDR_W        = 12,
    parameter int unsigned BURSTCOUNT_W      = 1,
    parameter logic [AVMM_ADDR_W-1:0] CSR_BASE_ADDR = '0
) (
    input  logic                         clk,
    input  logic                         rst_n,

    // Avalon-MM agent boundary. Address units are bytes/symbols, not 32-bit words.
    input  logic [AVMM_ADDR_W-1:0]       avs_address_i,
    input  logic                         avs_read_i,
    input  logic                         avs_write_i,
    input  logic [31:0]                  avs_writedata_i,
    input  logic [3:0]                   avs_byteenable_i,
    input  logic [BURSTCOUNT_W-1:0]      avs_burstcount_i,
    output logic                         avs_waitrequest_o,
    output logic [31:0]                  avs_readdata_o,
    output logic                         avs_readdatavalid_o,
    output logic                         avs_writeresponsevalid_o,
    output logic [1:0]                   avs_response_o,

    // Private CSR leaf request/response boundary.
    output logic                         csr_valid_o,
    output logic                         csr_write_o,
    output logic [CSR_ADDR_W-1:0]        csr_addr_o,
    output logic [31:0]                  csr_wdata_o,
    input  logic                         csr_ready_i,
    input  logic                         csr_rvalid_i,
    input  logic [31:0]                  csr_rdata_i,
    input  logic                         csr_error_i,

    // Pulses only for malformed/out-of-window Avalon requests rejected before the leaf.
    output logic                         local_reject_pulse_o,
    output logic                         busy_o
);

    localparam logic [1:0] AVMM_RESPONSE_OKAY        = 2'b00;
    localparam logic [1:0] AVMM_RESPONSE_SLVERR      = 2'b10;
    localparam logic [1:0] AVMM_RESPONSE_DECODEERROR = 2'b11;

    typedef enum logic [2:0] {
        ASTATE_IDLE        = 3'd0,
        ASTATE_ISSUE       = 3'd1,
        ASTATE_WAIT_RESULT = 3'd2,
        ASTATE_RESPOND     = 3'd3
    } adapter_state_e;

    adapter_state_e state_q;

    logic                         request_present;
    logic                         dual_request;
    logic                         address_in_window;
    logic                         address_aligned;
    logic                         byteenable_full;
    logic                         burstcount_one;
    logic                         request_legal;
    logic [1:0]                   local_error_response;

    logic                         transaction_is_read_q;
    logic                         csr_write_q;
    logic [CSR_ADDR_W-1:0]        csr_addr_q;
    logic [31:0]                  csr_wdata_q;
    logic [31:0]                  response_data_q;
    logic [1:0]                   response_code_q;

    function automatic logic [BURSTCOUNT_W-1:0] one_burst();
        logic [BURSTCOUNT_W-1:0] value;

        value = '0;
        value[0] = 1'b1;
        return value;
    endfunction : one_burst

    // XOR-plus-shift compares every address bit above the leaf offset while remaining well formed
    // when AVMM_ADDR_W equals CSR_ADDR_W. CSR_BASE_ADDR alignment is guarded below.
    assign request_present = avs_read_i || avs_write_i;
    assign dual_request = avs_read_i && avs_write_i;
    assign address_in_window = (((avs_address_i ^ CSR_BASE_ADDR) >> CSR_ADDR_W) == '0);
    assign address_aligned = (avs_address_i[1:0] == 2'b00);
    assign byteenable_full = (avs_byteenable_i == 4'b1111);
    assign burstcount_one = (avs_burstcount_i == one_burst());
    assign request_legal = !dual_request && address_in_window && address_aligned &&
                           byteenable_full && burstcount_one;
    // Default unknown or out-of-window simulation values to the fail-closed decode error. An
    // unambiguous in-window request uses SLVERR for any remaining transfer-policy violation.
    always_comb begin
        local_error_response = AVMM_RESPONSE_DECODEERROR;
        if (address_in_window) begin
            local_error_response = AVMM_RESPONSE_SLVERR;
        end
    end

    // A transaction is accepted only in IDLE. All request fields must remain stable at the Avalon
    // host while waitrequest is asserted; the adapter itself uses the latched copy after acceptance.
    assign avs_waitrequest_o = !rst_n || (state_q != ASTATE_IDLE);
    assign busy_o = (state_q != ASTATE_IDLE);

    assign csr_valid_o = rst_n && (state_q == ASTATE_ISSUE);
    assign csr_write_o = csr_write_q;
    assign csr_addr_o = csr_addr_q;
    assign csr_wdata_o = csr_wdata_q;

    assign avs_readdata_o = (state_q == ASTATE_RESPOND) ? response_data_q : 32'd0;
    assign avs_response_o = (state_q == ASTATE_RESPOND) ? response_code_q :
                                                           AVMM_RESPONSE_OKAY;
    assign avs_readdatavalid_o = rst_n && (state_q == ASTATE_RESPOND) &&
                                 transaction_is_read_q;
    assign avs_writeresponsevalid_o = rst_n && (state_q == ASTATE_RESPOND) &&
                                      !transaction_is_read_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= ASTATE_IDLE;
            transaction_is_read_q <= 1'b0;
            csr_write_q <= 1'b0;
            csr_addr_q <= '0;
            csr_wdata_q <= 32'd0;
            response_data_q <= 32'd0;
            response_code_q <= AVMM_RESPONSE_OKAY;
            local_reject_pulse_o <= 1'b0;
        end else begin
            local_reject_pulse_o <= 1'b0;

            unique case (state_q)
                ASTATE_IDLE: begin
                    response_data_q <= 32'd0;
                    response_code_q <= AVMM_RESPONSE_OKAY;

                    if (request_present) begin
                        // Read priority makes a protocol-violating simultaneous read/write request
                        // deterministic while ensuring the shared response channel is used once.
                        transaction_is_read_q <= avs_read_i;
                        csr_write_q <= avs_write_i;
                        // The sized cast retains the low byte-offset bits without an elaboration-
                        // fragile part-select when a bad integration override changes widths.
                        csr_addr_q <= CSR_ADDR_W'(avs_address_i);
                        csr_wdata_q <= avs_writedata_i;

                        if (request_legal) begin
                            state_q <= ASTATE_ISSUE;
                        end else begin
                            response_code_q <= local_error_response;
                            local_reject_pulse_o <= 1'b1;
                            state_q <= ASTATE_RESPOND;
                        end
                    end
                end

                ASTATE_ISSUE: begin
                    if (csr_ready_i) begin
                        state_q <= ASTATE_WAIT_RESULT;
                    end
                end

                ASTATE_WAIT_RESULT: begin
                    response_data_q <= 32'd0;
                    if (csr_error_i) begin
                        response_code_q <= AVMM_RESPONSE_SLVERR;
                    end else if (transaction_is_read_q && !csr_rvalid_i) begin
                        // The bound CSR bank has fixed one-cycle response latency. Missing rvalid
                        // without an explicit error is therefore a malformed leaf completion.
                        response_code_q <= AVMM_RESPONSE_SLVERR;
                    end else begin
                        response_code_q <= AVMM_RESPONSE_OKAY;
                        if (transaction_is_read_q) begin
                            response_data_q <= csr_rdata_i;
                        end
                    end
                    state_q <= ASTATE_RESPOND;
                end

                ASTATE_RESPOND: begin
                    state_q <= ASTATE_IDLE;
                end

                default: begin
                    transaction_is_read_q <= 1'b1;
                    response_data_q <= 32'd0;
                    response_code_q <= AVMM_RESPONSE_SLVERR;
                    local_reject_pulse_o <= 1'b1;
                    state_q <= ASTATE_RESPOND;
                end
            endcase
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (AVMM_ADDR_W < CSR_ADDR_W) begin
            $fatal(1, "trecap_avmm_csr_adapter: AVMM_ADDR_W must be >= CSR_ADDR_W");
        end
        if (CSR_ADDR_W < 2) begin
            $fatal(1, "trecap_avmm_csr_adapter: CSR_ADDR_W must retain two byte-alignment bits");
        end
        if (BURSTCOUNT_W < 1) begin
            $fatal(1, "trecap_avmm_csr_adapter: BURSTCOUNT_W must be at least 1");
        end
        if (((CSR_BASE_ADDR >> CSR_ADDR_W) << CSR_ADDR_W) != CSR_BASE_ADDR) begin
            $fatal(1, "trecap_avmm_csr_adapter: CSR_BASE_ADDR must be CSR-window aligned");
        end
    end
`endif

endmodule : trecap_avmm_csr_adapter

`default_nettype wire

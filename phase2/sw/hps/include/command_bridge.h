/* SPDX-License-Identifier: MIT
 * T-RECAP Phase 2 HPS transactional command bridge.
 * File class: [1] hand-written.
 *
 * The bridge is the architecture boundary between authenticated UDP commands
 * and CSR/ring lifecycle mutations. It owns v2 serial-number replay
 * protection, result caching, state/readback verification, and fail-closed
 * recovery. Wire constants and CSR addresses remain generated authorities.
 */

#ifndef TRECAP_HPS_COMMAND_BRIDGE_H
#define TRECAP_HPS_COMMAND_BRIDGE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "command_server.h"
#include "ring_reader.h"
#include "udp_sender.h"

#ifdef __cplusplus
extern "C" {
#endif

#define TRECAP_COMMAND_BRIDGE_DEFAULT_POLL_LIMIT UINT32_C(1000000)

typedef enum trecap_command_bridge_status {
    TRECAP_COMMAND_BRIDGE_OK = 0,
    TRECAP_COMMAND_BRIDGE_DUPLICATE = 1,
    TRECAP_COMMAND_BRIDGE_REJECTED = 2,
    TRECAP_COMMAND_BRIDGE_FAILED = 3,
    TRECAP_COMMAND_BRIDGE_ERR_NULL = -1,
    TRECAP_COMMAND_BRIDGE_ERR_CONFIG = -2
} trecap_command_bridge_status_t;

typedef trecap_csr_status_t (*trecap_command_bridge_read32_fn)(
    void *context,
    const trecap_csr_window_t *csr,
    uint32_t offset,
    uint32_t *value);

typedef trecap_csr_status_t (*trecap_command_bridge_write32_fn)(
    void *context,
    const trecap_csr_window_t *csr,
    uint32_t offset,
    uint32_t value);

typedef trecap_ring_status_t (*trecap_command_bridge_ring_reset_fn)(
    void *context,
    trecap_ring_reader_t *reader);

typedef trecap_ring_status_t (*trecap_command_bridge_ring_configure_fn)(
    void *context,
    trecap_ring_reader_t *reader,
    uint64_t ring_base_fpga,
    uint32_t ring_size_bytes,
    uint32_t ring_guard_bytes);

typedef trecap_ring_status_t (*trecap_command_bridge_ring_commit_rd_fn)(
    void *context,
    trecap_ring_reader_t *reader,
    uint64_t rd);

typedef trecap_ring_status_t (*trecap_command_bridge_ring_snapshot_wr_fn)(
    void *context,
    trecap_ring_reader_t *reader,
    uint64_t *wr_out);

typedef struct trecap_command_bridge_ops {
    trecap_command_bridge_read32_fn read32;
    trecap_command_bridge_write32_fn write32;
    trecap_command_bridge_ring_reset_fn ring_reset;
    trecap_command_bridge_ring_configure_fn ring_configure;
    trecap_command_bridge_ring_commit_rd_fn ring_commit_rd;
    trecap_command_bridge_ring_snapshot_wr_fn ring_snapshot_wr;
} trecap_command_bridge_ops_t;

typedef struct trecap_command_bridge_bindings {
    trecap_csr_window_t *csr;
    trecap_ring_reader_t *ring_reader;
    const trecap_hps_runtime_config_t *runtime_config;
    trecap_command_counters_t *command_counters;
    trecap_udp_sender_counters_t *udp_counters;
    bool *transport_enabled;
    uint64_t *active_thr2;
    uint32_t *active_packet_enable;
    uint32_t *active_wave_decim;
    uint32_t *active_spec_mode;
    uint32_t *active_spec_shift;
    uint32_t *active_source_mode;
    uint64_t *records_consumed;
    uint64_t *records_sent_or_dropped;
} trecap_command_bridge_bindings_t;

typedef struct trecap_command_bridge_outcome {
    trecap_command_bridge_status_t status;
    trecap_cmd_disposition_t disposition;
    trecap_cmd_reject_reason_t reject_reason;
    trecap_csr_status_t csr_status;
    trecap_ring_status_t ring_status;
    trecap_command_v2_result_packet_t result_packet;
    bool has_result;
    bool duplicate;
    bool applied;
    bool counters_cleared;
    /* fail_closed means the software lifecycle is locked in RESET_REQUIRED.
     * Hardware is claimed disabled only when this separate readback proof is
     * true; an MMIO fault must never be reported as a verified disable. */
    bool fail_closed;
    bool hardware_disable_verified;
    trecap_csr_status_t hardware_disable_status;
} trecap_command_bridge_outcome_t;

typedef struct trecap_command_bridge {
    trecap_command_bridge_bindings_t bindings;
    trecap_command_bridge_ops_t ops;
    void *ops_context;
    uint32_t poll_limit;
    bool reset_required;
    bool ledger_valid;
    uint32_t last_seq;
    trecap_command_packet_t last_request;
    trecap_command_v2_result_packet_t cached_result;
    bool cached_result_valid;
} trecap_command_bridge_t;

void trecap_command_bridge_ops_set_defaults(trecap_command_bridge_ops_t *ops);

trecap_command_bridge_status_t trecap_command_bridge_init(
    trecap_command_bridge_t *bridge,
    const trecap_command_bridge_bindings_t *bindings,
    const trecap_command_bridge_ops_t *ops,
    void *ops_context);

void trecap_command_bridge_reset_peer_session(trecap_command_bridge_t *bridge);

void trecap_command_bridge_outcome_init(trecap_command_bridge_outcome_t *outcome);

bool trecap_command_bridge_serial_is_newer(uint32_t candidate, uint32_t reference);

trecap_command_bridge_status_t trecap_command_bridge_handle_v2(
    trecap_command_bridge_t *bridge,
    const trecap_command_packet_t *cmd,
    trecap_command_bridge_outcome_t *outcome,
    char *err_buf,
    size_t err_buf_len);

trecap_command_bridge_status_t trecap_command_bridge_apply_v1(
    trecap_command_bridge_t *bridge,
    const trecap_command_packet_t *cmd,
    trecap_command_bridge_outcome_t *outcome,
    char *err_buf,
    size_t err_buf_len);

#ifdef __cplusplus
}
#endif

#endif /* TRECAP_HPS_COMMAND_BRIDGE_H */

/* SPDX-License-Identifier: MIT
 * T-RECAP Phase 2 HPS transactional command bridge.
 * File class: [1] hand-written.
 */

#include "command_bridge.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

static void trecap_bridge_set_error(char *err_buf, size_t err_buf_len, const char *fmt, ...)
{
    if (err_buf == NULL || err_buf_len == 0u) {
        return;
    }
    va_list ap;
    va_start(ap, fmt);
    (void)vsnprintf(err_buf, err_buf_len, fmt != NULL ? fmt : "", ap);
    va_end(ap);
    err_buf[err_buf_len - 1u] = '\0';
}

static trecap_csr_status_t trecap_bridge_default_read32(void *context,
                                                        const trecap_csr_window_t *csr,
                                                        uint32_t offset,
                                                        uint32_t *value)
{
    (void)context;
    return trecap_csr_read32(csr, offset, value);
}

static trecap_csr_status_t trecap_bridge_default_write32(void *context,
                                                         const trecap_csr_window_t *csr,
                                                         uint32_t offset,
                                                         uint32_t value)
{
    (void)context;
    return trecap_csr_write32(csr, offset, value);
}

static trecap_ring_status_t trecap_bridge_default_ring_reset(void *context,
                                                             trecap_ring_reader_t *reader)
{
    (void)context;
    return trecap_ring_reader_reset_transport(reader);
}

static trecap_ring_status_t trecap_bridge_default_ring_configure(void *context,
                                                                 trecap_ring_reader_t *reader,
                                                                 uint64_t ring_base_fpga,
                                                                 uint32_t ring_size_bytes,
                                                                 uint32_t ring_guard_bytes)
{
    (void)context;
    return trecap_ring_reader_configure_fpga_ring(reader,
                                                  ring_base_fpga,
                                                  ring_size_bytes,
                                                  ring_guard_bytes);
}

static trecap_ring_status_t trecap_bridge_default_ring_commit_rd(void *context,
                                                                 trecap_ring_reader_t *reader,
                                                                 uint64_t rd)
{
    (void)context;
    return trecap_ring_reader_commit_rd(reader, rd);
}

static trecap_ring_status_t trecap_bridge_default_ring_snapshot_wr(void *context,
                                                                   trecap_ring_reader_t *reader,
                                                                   uint64_t *wr_out)
{
    (void)context;
    return trecap_ring_reader_snapshot_wr(reader, wr_out);
}

void trecap_command_bridge_ops_set_defaults(trecap_command_bridge_ops_t *ops)
{
    if (ops == NULL) {
        return;
    }
    ops->read32 = trecap_bridge_default_read32;
    ops->write32 = trecap_bridge_default_write32;
    ops->ring_reset = trecap_bridge_default_ring_reset;
    ops->ring_configure = trecap_bridge_default_ring_configure;
    ops->ring_commit_rd = trecap_bridge_default_ring_commit_rd;
    ops->ring_snapshot_wr = trecap_bridge_default_ring_snapshot_wr;
}

void trecap_command_bridge_outcome_init(trecap_command_bridge_outcome_t *outcome)
{
    if (outcome == NULL) {
        return;
    }
    memset(outcome, 0, sizeof(*outcome));
    outcome->status = TRECAP_COMMAND_BRIDGE_OK;
    outcome->disposition = TRECAP_CMD_DISPOSITION_NOOP;
    outcome->reject_reason = TRECAP_CMD_REJECT_NONE;
    outcome->csr_status = TRECAP_CSR_OK;
    outcome->ring_status = TRECAP_RING_OK;
    outcome->hardware_disable_status = TRECAP_CSR_OK;
}

static bool trecap_bridge_bindings_valid(const trecap_command_bridge_bindings_t *bindings)
{
    return bindings != NULL && bindings->csr != NULL && bindings->ring_reader != NULL &&
           bindings->runtime_config != NULL && bindings->command_counters != NULL &&
           bindings->udp_counters != NULL && bindings->transport_enabled != NULL &&
           bindings->active_thr2 != NULL && bindings->active_packet_enable != NULL &&
           bindings->active_wave_decim != NULL && bindings->active_spec_mode != NULL &&
           bindings->active_spec_shift != NULL && bindings->active_source_mode != NULL &&
           bindings->records_consumed != NULL && bindings->records_sent_or_dropped != NULL;
}

static bool trecap_bridge_ops_valid(const trecap_command_bridge_ops_t *ops)
{
    return ops != NULL && ops->read32 != NULL && ops->write32 != NULL &&
           ops->ring_reset != NULL && ops->ring_configure != NULL &&
           ops->ring_commit_rd != NULL && ops->ring_snapshot_wr != NULL;
}

trecap_command_bridge_status_t trecap_command_bridge_init(
    trecap_command_bridge_t *bridge,
    const trecap_command_bridge_bindings_t *bindings,
    const trecap_command_bridge_ops_t *ops,
    void *ops_context)
{
    if (bridge == NULL || bindings == NULL) {
        return TRECAP_COMMAND_BRIDGE_ERR_NULL;
    }
    if (!trecap_bridge_bindings_valid(bindings)) {
        return TRECAP_COMMAND_BRIDGE_ERR_CONFIG;
    }

    trecap_command_bridge_ops_t selected_ops;
    if (ops == NULL) {
        trecap_command_bridge_ops_set_defaults(&selected_ops);
    } else {
        selected_ops = *ops;
    }
    if (!trecap_bridge_ops_valid(&selected_ops)) {
        return TRECAP_COMMAND_BRIDGE_ERR_CONFIG;
    }

    memset(bridge, 0, sizeof(*bridge));
    bridge->bindings = *bindings;
    bridge->ops = selected_ops;
    bridge->ops_context = ops_context;
    bridge->poll_limit = TRECAP_COMMAND_BRIDGE_DEFAULT_POLL_LIMIT;
    bridge->reset_required = bindings->ring_reader->state == TRECAP_RING_READER_RESET_REQUIRED ||
                             bindings->ring_reader->state ==
                                 TRECAP_RING_READER_MALFORMED_LATCHED;
    return TRECAP_COMMAND_BRIDGE_OK;
}

void trecap_command_bridge_reset_peer_session(trecap_command_bridge_t *bridge)
{
    if (bridge == NULL) {
        return;
    }
    bridge->ledger_valid = false;
    bridge->last_seq = 0u;
    memset(&bridge->last_request, 0, sizeof(bridge->last_request));
    memset(&bridge->cached_result, 0, sizeof(bridge->cached_result));
    bridge->cached_result_valid = false;
}

bool trecap_command_bridge_serial_is_newer(uint32_t candidate, uint32_t reference)
{
    const uint32_t distance = candidate - reference;
    return distance != 0u && distance < UINT32_C(0x80000000);
}

static trecap_csr_status_t trecap_bridge_read32(trecap_command_bridge_t *bridge,
                                                uint32_t offset,
                                                uint32_t *value)
{
    if (bridge == NULL) {
        return TRECAP_CSR_ERR_NULL;
    }
    return bridge->ops.read32(bridge->ops_context, bridge->bindings.csr, offset, value);
}

static trecap_csr_status_t trecap_bridge_write32(trecap_command_bridge_t *bridge,
                                                 uint32_t offset,
                                                 uint32_t value)
{
    if (bridge == NULL) {
        return TRECAP_CSR_ERR_NULL;
    }
    return bridge->ops.write32(bridge->ops_context, bridge->bindings.csr, offset, value);
}

static trecap_csr_status_t trecap_bridge_snapshot_raw(trecap_command_bridge_t *bridge,
                                                      uint32_t *status_out,
                                                      uint32_t *version_out)
{
    if (status_out == NULL || version_out == NULL) {
        return TRECAP_CSR_ERR_NULL;
    }
    *status_out = 0u;
    *version_out = 0u;
    trecap_csr_status_t first_error = TRECAP_CSR_OK;
    trecap_csr_status_t status =
        trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, status_out);
    if (status != TRECAP_CSR_OK) {
        *status_out = 0u;
        first_error = status;
    }
    status = trecap_bridge_read32(bridge, TCSR_VERSION_OFFSET, version_out);
    if (status != TRECAP_CSR_OK) {
        *version_out = 0u;
        if (first_error == TRECAP_CSR_OK) {
            first_error = status;
        }
    }
    return first_error;
}

static trecap_csr_status_t trecap_bridge_require_identity(trecap_command_bridge_t *bridge,
                                                          uint32_t *version_out)
{
    uint32_t id_value = 0u;
    uint32_t version_value = 0u;
    trecap_csr_status_t status = trecap_bridge_read32(bridge, TCSR_ID_OFFSET, &id_value);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    status = trecap_bridge_read32(bridge, TCSR_VERSION_OFFSET, &version_value);
    if (version_out != NULL) {
        *version_out = version_value;
    }
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    if (id_value != TCSR_ID_VALUE || version_value != TCSR_VERSION_VALUE) {
        return TRECAP_CSR_ERR_VERSION;
    }
    return TRECAP_CSR_OK;
}

static trecap_csr_status_t trecap_bridge_read_reject_count(trecap_command_bridge_t *bridge,
                                                           uint32_t *count_out)
{
    return trecap_bridge_read32(bridge, TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET, count_out);
}

static bool trecap_bridge_status_has_controls(uint32_t status_word,
                                              bool telemetry_enable,
                                              bool writer_enable)
{
    const bool telemetry = (status_word & TCSR_STATUS_TELEMETRY_ENABLED_MASK) != 0u;
    const bool writer = (status_word & TCSR_STATUS_RING_WRITER_ENABLED_MASK) != 0u;
    return telemetry == telemetry_enable && writer == writer_enable;
}

static bool trecap_bridge_status_source_is(uint32_t status_word, uint32_t source_mode)
{
    const uint32_t actual = (status_word & TCSR_STATUS_ACTUAL_SOURCE_MODE_MASK) >>
                            TCSR_STATUS_ACTUAL_SOURCE_MODE_LSB;
    return actual == source_mode &&
           (status_word & (TCSR_STATUS_SOURCE_COMMIT_PENDING_MASK |
                           TCSR_STATUS_SOURCE_TRANSITION_BUSY_MASK)) == 0u;
}

static void trecap_bridge_set_result_state(trecap_command_bridge_outcome_t *outcome,
                                           trecap_cmd_disposition_t disposition,
                                           trecap_cmd_reject_reason_t reason)
{
    if (outcome == NULL) {
        return;
    }
    outcome->disposition = disposition;
    outcome->reject_reason = reason;
    outcome->applied = disposition == TRECAP_CMD_DISPOSITION_APPLIED;
    if (disposition == TRECAP_CMD_DISPOSITION_REJECTED) {
        outcome->status = TRECAP_COMMAND_BRIDGE_REJECTED;
    } else if (disposition == TRECAP_CMD_DISPOSITION_FAILED) {
        outcome->status = TRECAP_COMMAND_BRIDGE_FAILED;
    } else {
        outcome->status = TRECAP_COMMAND_BRIDGE_OK;
    }
}

static void trecap_bridge_latch_fail_closed(trecap_command_bridge_t *bridge,
                                            trecap_command_bridge_outcome_t *outcome)
{
    if (bridge == NULL) {
        return;
    }
    /* Always attempt the write, then make the hardware claim solely from
     * STATUS readback. Even a reported write fault can leave hardware already
     * disabled; conversely a successful store is never proof by itself. */
    (void)trecap_bridge_write32(bridge, TCSR_CONTROL_OFFSET, 0u);
    uint32_t status_word = 0u;
    trecap_csr_status_t disable_status =
        trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &status_word);
    if (disable_status == TRECAP_CSR_OK &&
        !trecap_bridge_status_has_controls(status_word, false, false)) {
        disable_status = TRECAP_CSR_ERR_BAD_VALUE;
    }
    bridge->reset_required = true;
    *bridge->bindings.transport_enabled = false;
    bridge->bindings.ring_reader->telemetry_disabled_by_reader = true;
    bridge->bindings.ring_reader->state = TRECAP_RING_READER_RESET_REQUIRED;
    if (outcome != NULL) {
        outcome->fail_closed = true;
        outcome->hardware_disable_status = disable_status;
        outcome->hardware_disable_verified = disable_status == TRECAP_CSR_OK;
    }
}

static trecap_csr_status_t trecap_bridge_wait_pending_clear(trecap_command_bridge_t *bridge,
                                                            uint32_t pending_mask,
                                                            bool verify_source,
                                                            uint32_t source_mode,
                                                            uint32_t *last_status_out)
{
    uint32_t last_status = 0u;
    for (uint32_t poll = 0u; poll < bridge->poll_limit; ++poll) {
        const trecap_csr_status_t status =
            trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &last_status);
        if (status != TRECAP_CSR_OK) {
            return status;
        }
        const bool pending_clear = (last_status & pending_mask) == 0u;
        const bool source_ready = !verify_source ||
                                  trecap_bridge_status_source_is(last_status, source_mode);
        if (pending_clear && source_ready) {
            if (last_status_out != NULL) {
                *last_status_out = last_status;
            }
            return TRECAP_CSR_OK;
        }
    }
    if (last_status_out != NULL) {
        *last_status_out = last_status;
    }
    return TRECAP_CSR_ERR_TIMEOUT;
}

static void trecap_bridge_fail_from_csr(trecap_command_bridge_t *bridge,
                                        trecap_command_bridge_outcome_t *outcome,
                                        trecap_csr_status_t csr_status,
                                        bool writes_started)
{
    outcome->csr_status = csr_status;
    const trecap_cmd_reject_reason_t reason =
        csr_status == TRECAP_CSR_ERR_TIMEOUT
            ? TRECAP_CMD_REJECT_TIMEOUT
            : (csr_status == TRECAP_CSR_ERR_VERSION ? TRECAP_CMD_REJECT_VERSION_MISMATCH
                                                    : TRECAP_CMD_REJECT_IO);
    trecap_bridge_set_result_state(outcome, TRECAP_CMD_DISPOSITION_FAILED, reason);
    if (writes_started) {
        trecap_bridge_latch_fail_closed(bridge, outcome);
    }
}

static bool trecap_bridge_check_identity(trecap_command_bridge_t *bridge,
                                         trecap_command_bridge_outcome_t *outcome)
{
    uint32_t raw_version = 0u;
    const trecap_csr_status_t status =
        trecap_bridge_require_identity(bridge, &raw_version);
    (void)raw_version;
    if (status == TRECAP_CSR_OK) {
        return true;
    }
    outcome->csr_status = status;
    trecap_bridge_set_result_state(
        outcome,
        TRECAP_CMD_DISPOSITION_FAILED,
        status == TRECAP_CSR_ERR_VERSION ? TRECAP_CMD_REJECT_VERSION_MISMATCH
                                         : TRECAP_CMD_REJECT_IO);
    return false;
}

static bool trecap_bridge_begin_mutation(trecap_command_bridge_t *bridge,
                                         trecap_command_bridge_outcome_t *outcome,
                                         uint32_t *reject_before)
{
    if (!trecap_bridge_check_identity(bridge, outcome)) {
        return false;
    }
    const trecap_csr_status_t status =
        trecap_bridge_read_reject_count(bridge, reject_before);
    if (status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, status, false);
        return false;
    }
    return true;
}

static bool trecap_bridge_reject_changed(trecap_command_bridge_t *bridge,
                                         trecap_command_bridge_outcome_t *outcome,
                                         uint32_t reject_before,
                                         uint32_t *reject_after_out)
{
    uint32_t reject_after = 0u;
    const trecap_csr_status_t status =
        trecap_bridge_read_reject_count(bridge, &reject_after);
    if (status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, status, true);
        return true;
    }
    if (reject_after_out != NULL) {
        *reject_after_out = reject_after;
    }
    return reject_after != reject_before;
}

static bool trecap_bridge_apply_rw32(trecap_command_bridge_t *bridge,
                                     uint32_t offset,
                                     uint32_t requested,
                                     uint32_t *active_mirror,
                                     trecap_command_bridge_outcome_t *outcome)
{
    uint32_t current = 0u;
    trecap_csr_status_t status = trecap_bridge_read32(bridge, offset, &current);
    if (status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, status, false);
        return false;
    }
    if (current == requested) {
        if (active_mirror != NULL) {
            *active_mirror = requested;
        }
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_NOOP,
                                       TRECAP_CMD_REJECT_NONE);
        return true;
    }

    status = trecap_bridge_write32(bridge, offset, requested);
    if (status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, status, true);
        return false;
    }

    uint32_t readback = 0u;
    status = trecap_bridge_read32(bridge, offset, &readback);
    if (status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, status, true);
        return false;
    }
    if (readback == current) {
        /* A synchronously readable RW register that stayed at the verified old
         * value cleanly rejected the write. The global reject counter is not a
         * per-command acknowledgement and is intentionally not consulted. */
        outcome->csr_status = TRECAP_CSR_ERR_BAD_VALUE;
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_REJECTED,
                                       TRECAP_CMD_REJECT_CSR);
        return false;
    }
    if (readback != requested) {
        trecap_bridge_fail_from_csr(bridge, outcome, TRECAP_CSR_ERR_BAD_VALUE, true);
        return false;
    }

    if (active_mirror != NULL) {
        *active_mirror = requested;
    }
    trecap_bridge_set_result_state(outcome,
                                   TRECAP_CMD_DISPOSITION_APPLIED,
                                   TRECAP_CMD_REJECT_NONE);
    return true;
}

static void trecap_bridge_execute_thr2(trecap_command_bridge_t *bridge,
                                       const trecap_command_packet_t *cmd,
                                       trecap_command_bridge_outcome_t *outcome)
{
    const uint64_t requested = trecap_cmd_thr2_from_args(cmd->arg0, cmd->arg1);
    uint32_t status_word = 0u;
    trecap_csr_status_t status =
        trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &status_word);
    if (status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, status, false);
        return;
    }
    uint32_t current_lo = 0u;
    uint32_t current_hi = 0u;
    status = trecap_bridge_read32(bridge, TCSR_THR2_LO_OFFSET, &current_lo);
    if (status == TRECAP_CSR_OK) {
        status = trecap_bridge_read32(bridge, TCSR_THR2_HI_OFFSET, &current_hi);
    }
    if (status != TRECAP_CSR_OK || (current_hi & UINT32_C(0xff000000)) != 0u) {
        trecap_bridge_fail_from_csr(bridge,
                                    outcome,
                                    status == TRECAP_CSR_OK ? TRECAP_CSR_ERR_BAD_VALUE : status,
                                    false);
        return;
    }
    const uint64_t current_shadow = trecap_csr_join_u64(current_lo, current_hi);
    if ((status_word & TCSR_STATUS_THR2_COMMIT_PENDING_MASK) != 0u) {
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_REJECTED,
                                       TRECAP_CMD_REJECT_UNSAFE_STATE);
        return;
    }
    if (current_shadow == requested) {
        *bridge->bindings.active_thr2 = requested;
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_NOOP,
                                       TRECAP_CMD_REJECT_NONE);
        return;
    }

    status = trecap_bridge_write32(bridge, TCSR_THR2_LO_OFFSET, trecap_csr_lo32(requested));
    if (status == TRECAP_CSR_OK) {
        status = trecap_bridge_write32(bridge,
                                       TCSR_THR2_HI_OFFSET,
                                       trecap_csr_hi32(requested));
    }
    if (status == TRECAP_CSR_OK) {
        status = trecap_bridge_write32(bridge, TCSR_THR2_COMMIT_OFFSET, UINT32_C(1));
    }
    if (status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, status, true);
        return;
    }
    status = trecap_bridge_wait_pending_clear(bridge,
                                              TCSR_STATUS_THR2_COMMIT_PENDING_MASK,
                                              false,
                                              0u,
                                              &status_word);
    if (status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, status, true);
        return;
    }
    uint32_t readback_lo = 0u;
    uint32_t readback_hi = 0u;
    status = trecap_bridge_read32(bridge, TCSR_THR2_LO_OFFSET, &readback_lo);
    if (status == TRECAP_CSR_OK) {
        status = trecap_bridge_read32(bridge, TCSR_THR2_HI_OFFSET, &readback_hi);
    }
    if (status != TRECAP_CSR_OK || (readback_hi & UINT32_C(0xff000000)) != 0u ||
        trecap_csr_join_u64(readback_lo, readback_hi) != requested) {
        trecap_bridge_fail_from_csr(bridge,
                                    outcome,
                                    status == TRECAP_CSR_OK ? TRECAP_CSR_ERR_BAD_VALUE : status,
                                    true);
        return;
    }
    *bridge->bindings.active_thr2 = requested;
    trecap_bridge_set_result_state(outcome,
                                   TRECAP_CMD_DISPOSITION_APPLIED,
                                   TRECAP_CMD_REJECT_NONE);
}

static void trecap_bridge_execute_source(trecap_command_bridge_t *bridge,
                                         const trecap_command_packet_t *cmd,
                                         trecap_command_bridge_outcome_t *outcome)
{
    uint32_t old_status = 0u;
    trecap_csr_status_t status =
        trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &old_status);
    if (status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, status, false);
        return;
    }
    if (trecap_bridge_status_source_is(old_status, cmd->arg0)) {
        *bridge->bindings.active_source_mode = cmd->arg0;
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_NOOP,
                                       TRECAP_CMD_REJECT_NONE);
        return;
    }
    if ((old_status & TCSR_STATUS_SOURCE_TRANSITION_BUSY_MASK) != 0u) {
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_REJECTED,
                                       TRECAP_CMD_REJECT_UNSAFE_STATE);
        return;
    }

    const uint32_t old_source =
        (old_status & TCSR_STATUS_ACTUAL_SOURCE_MODE_MASK) >>
        TCSR_STATUS_ACTUAL_SOURCE_MODE_LSB;
    status = trecap_bridge_write32(bridge, TCSR_SOURCE_MODE_SHADOW_OFFSET, cmd->arg0);
    if (status == TRECAP_CSR_OK) {
        status = trecap_bridge_write32(bridge, TCSR_SOURCE_MODE_COMMIT_OFFSET, UINT32_C(1));
    }
    if (status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, status, true);
        return;
    }

    uint32_t final_status = old_status;
    status = trecap_bridge_wait_pending_clear(bridge,
                                              TCSR_STATUS_SOURCE_COMMIT_PENDING_MASK,
                                              true,
                                              cmd->arg0,
                                              &final_status);
    if (status != TRECAP_CSR_OK) {
        if (trecap_bridge_status_source_is(final_status, old_source)) {
            outcome->csr_status = TRECAP_CSR_ERR_BAD_VALUE;
            trecap_bridge_set_result_state(outcome,
                                           TRECAP_CMD_DISPOSITION_REJECTED,
                                           TRECAP_CMD_REJECT_CSR);
            return;
        }
        trecap_bridge_fail_from_csr(bridge, outcome, status, true);
        return;
    }
    if (!trecap_bridge_status_source_is(final_status, cmd->arg0)) {
        trecap_bridge_fail_from_csr(bridge, outcome, TRECAP_CSR_ERR_BAD_VALUE, true);
        return;
    }
    *bridge->bindings.active_source_mode = cmd->arg0;
    trecap_bridge_set_result_state(outcome,
                                   TRECAP_CMD_DISPOSITION_APPLIED,
                                   TRECAP_CMD_REJECT_NONE);
}

static void trecap_bridge_execute_pulse(trecap_command_bridge_t *bridge,
                                        uint32_t offset,
                                        uint32_t mask,
                                        trecap_command_bridge_outcome_t *outcome)
{
    const trecap_csr_status_t status = trecap_bridge_write32(bridge, offset, mask);
    if (status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, status, true);
        return;
    }
    /* CONTROL W1P legality is established before the write. The global CSR
     * reject counter also includes asynchronous sources and is not a correlated
     * acknowledgement for this pulse. */
    trecap_bridge_set_result_state(outcome,
                                   TRECAP_CMD_DISPOSITION_APPLIED,
                                   TRECAP_CMD_REJECT_NONE);
}

static trecap_csr_status_t trecap_bridge_reset_rearm_replay(
    trecap_command_bridge_t *bridge)
{
    uint32_t replay_status = 0u;
    trecap_csr_status_t status =
        trecap_bridge_read32(bridge, TCSR_REPLAY_STATUS_OFFSET, &replay_status);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    if ((replay_status & TCSR_REPLAY_STATUS_RESERVED_15_11_MASK) != 0u) {
        return TRECAP_CSR_ERR_BAD_VALUE;
    }
    const uint32_t replay_busy = TCSR_REPLAY_STATUS_PENDING_MASK |
                                 TCSR_REPLAY_STATUS_REPLAY_ACTIVE_MASK |
                                 TCSR_REPLAY_STATUS_REPLAY_PATH_BUSY_MASK |
                                 TCSR_REPLAY_STATUS_E2E_BUSY_MASK;
    if ((replay_status & replay_busy) != 0u) {
        /* RESET is not an abort. A live/pending replay must reach a terminal,
         * quiescent state before software may clear a failed replay epoch. */
        return TRECAP_CSR_ERR_BAD_VALUE;
    }

    const uint32_t unsafe_status = TCSR_STATUS_WRITER_BUSY_MASK |
                                   TCSR_STATUS_THR2_COMMIT_PENDING_MASK |
                                   TCSR_STATUS_SOURCE_COMMIT_PENDING_MASK |
                                   TCSR_STATUS_SOURCE_TRANSITION_BUSY_MASK;
    bool transport_quiescent = false;
    for (uint32_t poll = 0u; poll < bridge->poll_limit; ++poll) {
        uint32_t status_word = 0u;
        status = trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &status_word);
        if (status != TRECAP_CSR_OK) {
            return status;
        }
        if (trecap_bridge_status_has_controls(status_word, false, false) &&
            (status_word & unsafe_status) == 0u &&
            (status_word & TCSR_STATUS_TRANSPORT_EPOCH_IDLE_MASK) != 0u) {
            transport_quiescent = true;
            break;
        }
    }
    if (!transport_quiescent) {
        return TRECAP_CSR_ERR_TIMEOUT;
    }

    if ((replay_status & TCSR_REPLAY_STATUS_REARM_REQUIRED_MASK) == 0u) {
        /* REARM is illegal when no failed epoch owns the latch. Healthy RESET
         * therefore performs no replay-control write at all. */
        return TRECAP_CSR_OK;
    }

    const uint32_t baseline_epoch = replay_status & TCSR_REPLAY_STATUS_RESULT_EPOCH_MASK;
    status = trecap_bridge_write32(bridge,
                                   TCSR_REPLAY_CONTROL_OFFSET,
                                   TCSR_REPLAY_CONTROL_REARM_MASK);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    const uint32_t must_clear = replay_busy |
                                TCSR_REPLAY_STATUS_LAST_ACCEPT_MASK |
                                TCSR_REPLAY_STATUS_LAST_REJECT_MASK |
                                TCSR_REPLAY_STATUS_ERROR_MASK |
                                TCSR_REPLAY_STATUS_REARM_REQUIRED_MASK;
    for (uint32_t poll = 0u; poll < bridge->poll_limit; ++poll) {
        status = trecap_bridge_read32(bridge, TCSR_REPLAY_STATUS_OFFSET, &replay_status);
        if (status != TRECAP_CSR_OK) {
            return status;
        }
        if ((replay_status & TCSR_REPLAY_STATUS_RESERVED_15_11_MASK) != 0u ||
            (replay_status & TCSR_REPLAY_STATUS_RESULT_EPOCH_MASK) != baseline_epoch) {
            return TRECAP_CSR_ERR_BAD_VALUE;
        }
        if ((replay_status & must_clear) == 0u) {
            return TRECAP_CSR_OK;
        }
    }
    return TRECAP_CSR_ERR_TIMEOUT;
}

static trecap_csr_status_t trecap_bridge_reset_write_verify32(
    trecap_command_bridge_t *bridge,
    uint32_t offset,
    uint32_t requested)
{
    uint32_t current = 0u;
    trecap_csr_status_t status = trecap_bridge_read32(bridge, offset, &current);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    if (current == requested) {
        return TRECAP_CSR_OK;
    }
    status = trecap_bridge_write32(bridge, offset, requested);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    uint32_t readback = 0u;
    status = trecap_bridge_read32(bridge, offset, &readback);
    return status == TRECAP_CSR_OK && readback == requested ? TRECAP_CSR_OK
                                                            : (status == TRECAP_CSR_OK
                                                                   ? TRECAP_CSR_ERR_BAD_VALUE
                                                                   : status);
}

static trecap_csr_status_t trecap_bridge_reset_reconcile_config(
    trecap_command_bridge_t *bridge)
{
    trecap_csr_status_t status = trecap_bridge_require_identity(bridge, NULL);
    if (status != TRECAP_CSR_OK) {
        return status;
    }

    const uint64_t desired_thr2 = *bridge->bindings.active_thr2;
    const uint32_t desired_source = *bridge->bindings.active_source_mode;
    if (!trecap_csr_thr2_is_valid(desired_thr2) ||
        !trecap_csr_source_mode_is_valid(desired_source) ||
        !trecap_csr_packet_enable_is_valid(*bridge->bindings.active_packet_enable) ||
        !trecap_csr_wave_decim_is_valid(*bridge->bindings.active_wave_decim) ||
        !trecap_csr_spec_mode_is_valid(*bridge->bindings.active_spec_mode) ||
        !trecap_csr_spec_shift_is_valid(*bridge->bindings.active_spec_shift)) {
        return TRECAP_CSR_ERR_BAD_VALUE;
    }

    uint32_t status_word = 0u;
    const uint32_t unsafe_status = TCSR_STATUS_WRITER_BUSY_MASK |
                                   TCSR_STATUS_THR2_COMMIT_PENDING_MASK |
                                   TCSR_STATUS_SOURCE_COMMIT_PENDING_MASK |
                                   TCSR_STATUS_SOURCE_TRANSITION_BUSY_MASK;
    bool transport_quiescent = false;
    for (uint32_t poll = 0u; poll < bridge->poll_limit; ++poll) {
        status = trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &status_word);
        if (status != TRECAP_CSR_OK) {
            return status;
        }
        if (trecap_bridge_status_has_controls(status_word, false, false) &&
            (status_word & unsafe_status) == 0u &&
            (status_word & TCSR_STATUS_TRANSPORT_EPOCH_IDLE_MASK) != 0u) {
            transport_quiescent = true;
            break;
        }
    }
    if (!transport_quiescent) {
        return TRECAP_CSR_ERR_TIMEOUT;
    }

    uint32_t thr2_lo = 0u;
    uint32_t thr2_hi = 0u;
    status = trecap_bridge_read32(bridge, TCSR_THR2_LO_OFFSET, &thr2_lo);
    if (status == TRECAP_CSR_OK) {
        status = trecap_bridge_read32(bridge, TCSR_THR2_HI_OFFSET, &thr2_hi);
    }
    if (status != TRECAP_CSR_OK || (thr2_hi & UINT32_C(0xff000000)) != 0u) {
        return status == TRECAP_CSR_OK ? TRECAP_CSR_ERR_BAD_VALUE : status;
    }
    if (trecap_csr_join_u64(thr2_lo, thr2_hi) != desired_thr2) {
        status = trecap_bridge_write32(bridge,
                                       TCSR_THR2_LO_OFFSET,
                                       trecap_csr_lo32(desired_thr2));
        if (status == TRECAP_CSR_OK) {
            status = trecap_bridge_write32(bridge,
                                           TCSR_THR2_HI_OFFSET,
                                           trecap_csr_hi32(desired_thr2));
        }
        if (status == TRECAP_CSR_OK) {
            status = trecap_bridge_write32(bridge, TCSR_THR2_COMMIT_OFFSET, UINT32_C(1));
        }
        if (status != TRECAP_CSR_OK) {
            return status;
        }
        status = trecap_bridge_wait_pending_clear(bridge,
                                                  TCSR_STATUS_THR2_COMMIT_PENDING_MASK,
                                                  false,
                                                  0u,
                                                  &status_word);
        if (status != TRECAP_CSR_OK) {
            return status;
        }
        status = trecap_bridge_read32(bridge, TCSR_THR2_LO_OFFSET, &thr2_lo);
        if (status == TRECAP_CSR_OK) {
            status = trecap_bridge_read32(bridge, TCSR_THR2_HI_OFFSET, &thr2_hi);
        }
        if (status != TRECAP_CSR_OK || (thr2_hi & UINT32_C(0xff000000)) != 0u ||
            trecap_csr_join_u64(thr2_lo, thr2_hi) != desired_thr2) {
            return status == TRECAP_CSR_OK ? TRECAP_CSR_ERR_BAD_VALUE : status;
        }
    }

    status = trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &status_word);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    if (!trecap_bridge_status_source_is(status_word, desired_source)) {
        status = trecap_bridge_write32(bridge,
                                       TCSR_SOURCE_MODE_SHADOW_OFFSET,
                                       desired_source);
        if (status == TRECAP_CSR_OK) {
            status = trecap_bridge_write32(bridge,
                                           TCSR_SOURCE_MODE_COMMIT_OFFSET,
                                           UINT32_C(1));
        }
        if (status != TRECAP_CSR_OK) {
            return status;
        }
        status = trecap_bridge_wait_pending_clear(bridge,
                                                  TCSR_STATUS_SOURCE_COMMIT_PENDING_MASK,
                                                  true,
                                                  desired_source,
                                                  &status_word);
        if (status != TRECAP_CSR_OK ||
            !trecap_bridge_status_source_is(status_word, desired_source)) {
            return status == TRECAP_CSR_OK ? TRECAP_CSR_ERR_BAD_VALUE : status;
        }
    }

    status = trecap_bridge_reset_write_verify32(bridge,
                                                TCSR_PACKET_ENABLE_OFFSET,
                                                *bridge->bindings.active_packet_enable);
    if (status == TRECAP_CSR_OK) {
        status = trecap_bridge_reset_write_verify32(bridge,
                                                    TCSR_WAVE_DECIM_OFFSET,
                                                    *bridge->bindings.active_wave_decim);
    }
    if (status == TRECAP_CSR_OK) {
        status = trecap_bridge_reset_write_verify32(bridge,
                                                    TCSR_SPEC_MODE_OFFSET,
                                                    *bridge->bindings.active_spec_mode);
    }
    if (status == TRECAP_CSR_OK) {
        status = trecap_bridge_reset_write_verify32(bridge,
                                                    TCSR_SPEC_SHIFT_OFFSET,
                                                    *bridge->bindings.active_spec_shift);
    }
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    status = trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &status_word);
    if (status != TRECAP_CSR_OK ||
        !trecap_bridge_status_has_controls(status_word, false, false) ||
        (status_word & unsafe_status) != 0u ||
        (status_word & TCSR_STATUS_TRANSPORT_EPOCH_IDLE_MASK) == 0u ||
        !trecap_bridge_status_source_is(status_word, desired_source)) {
        return status == TRECAP_CSR_OK ? TRECAP_CSR_ERR_BAD_VALUE : status;
    }
    return TRECAP_CSR_OK;
}

static void trecap_bridge_execute_reset(trecap_command_bridge_t *bridge,
                                        trecap_command_bridge_outcome_t *outcome)
{
    if (!trecap_bridge_check_identity(bridge, outcome)) {
        return;
    }
    /* The software lock is cleared only after reset and persistent-config
     * reconciliation have both completed with readback proof. */
    bridge->reset_required = true;
    *bridge->bindings.transport_enabled = false;
    bridge->bindings.ring_reader->telemetry_disabled_by_reader = true;
    const trecap_ring_status_t ring_status =
        bridge->ops.ring_reset(bridge->ops_context, bridge->bindings.ring_reader);
    outcome->ring_status = ring_status;
    if (ring_status != TRECAP_RING_OK) {
        const trecap_csr_status_t csr_status = ring_status == TRECAP_RING_ERR_TIMEOUT
                                                   ? TRECAP_CSR_ERR_TIMEOUT
                                                   : TRECAP_CSR_ERR_IO;
        trecap_bridge_fail_from_csr(bridge, outcome, csr_status, true);
        return;
    }
    trecap_csr_status_t csr_status = trecap_bridge_reset_rearm_replay(bridge);
    if (csr_status == TRECAP_CSR_OK) {
        csr_status = trecap_bridge_reset_reconcile_config(bridge);
    }
    if (csr_status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, csr_status, true);
        return;
    }
    bridge->reset_required = false;
    *bridge->bindings.transport_enabled = false;
    trecap_bridge_set_result_state(outcome,
                                   TRECAP_CMD_DISPOSITION_APPLIED,
                                   TRECAP_CMD_REJECT_NONE);
}

static void trecap_bridge_execute_configure(trecap_command_bridge_t *bridge,
                                            trecap_command_bridge_outcome_t *outcome)
{
    if (!trecap_bridge_check_identity(bridge, outcome)) {
        return;
    }
    trecap_ring_reader_t *reader = bridge->bindings.ring_reader;
    if (bridge->reset_required || reader->state == TRECAP_RING_READER_RESET_REQUIRED ||
        reader->state == TRECAP_RING_READER_MALFORMED_LATCHED) {
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_REJECTED,
                                       TRECAP_CMD_REJECT_RESET_REQUIRED);
        return;
    }
    if (reader->state != TRECAP_RING_READER_RECONFIG_REQUIRED) {
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_REJECTED,
                                       TRECAP_CMD_REJECT_UNSAFE_STATE);
        return;
    }

    const trecap_hps_runtime_config_t *cfg = bridge->bindings.runtime_config;
    trecap_ring_status_t ring_status = bridge->ops.ring_configure(bridge->ops_context,
                                                                 reader,
                                                                 cfg->ring_base_fpga,
                                                                 cfg->ring_size_bytes,
                                                                 cfg->ring_guard_bytes);
    outcome->ring_status = ring_status;
    if (ring_status == TRECAP_RING_OK) {
        ring_status = bridge->ops.ring_commit_rd(bridge->ops_context, reader, 0u);
        outcome->ring_status = ring_status;
    }
    uint64_t wr = UINT64_MAX;
    if (ring_status == TRECAP_RING_OK) {
        ring_status = bridge->ops.ring_snapshot_wr(bridge->ops_context, reader, &wr);
        outcome->ring_status = ring_status;
        if ((ring_status != TRECAP_RING_OK && ring_status != TRECAP_RING_EMPTY) || wr != 0u) {
            ring_status = TRECAP_RING_ERR_CONFIG;
            outcome->ring_status = ring_status;
        }
    }
    uint32_t status_word = 0u;
    trecap_csr_status_t csr_status = TRECAP_CSR_OK;
    if (ring_status == TRECAP_RING_OK || ring_status == TRECAP_RING_EMPTY) {
        csr_status = trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &status_word);
        if (csr_status == TRECAP_CSR_OK &&
            ((status_word & TCSR_STATUS_RING_CONFIGURED_MASK) == 0u ||
             (status_word & TCSR_STATUS_MALFORMED_CONFIG_MASK) != 0u ||
             !trecap_bridge_status_has_controls(status_word, false, false))) {
            csr_status = TRECAP_CSR_ERR_BAD_VALUE;
        }
    }
    if ((ring_status != TRECAP_RING_OK && ring_status != TRECAP_RING_EMPTY) ||
        csr_status != TRECAP_CSR_OK) {
        outcome->csr_status = csr_status;
        const trecap_csr_status_t failure =
            ring_status == TRECAP_RING_ERR_TIMEOUT ? TRECAP_CSR_ERR_TIMEOUT
                                                   : (csr_status != TRECAP_CSR_OK
                                                          ? csr_status
                                                          : TRECAP_CSR_ERR_IO);
        trecap_bridge_fail_from_csr(bridge, outcome, failure, true);
        return;
    }
    reader->telemetry_disabled_by_reader = true;
    *bridge->bindings.transport_enabled = false;
    trecap_bridge_set_result_state(outcome,
                                   TRECAP_CMD_DISPOSITION_APPLIED,
                                   TRECAP_CMD_REJECT_NONE);
}

static void trecap_bridge_execute_enable(trecap_command_bridge_t *bridge,
                                         bool enable,
                                         trecap_command_bridge_outcome_t *outcome)
{
    if (!trecap_bridge_check_identity(bridge, outcome)) {
        return;
    }
    trecap_ring_reader_t *reader = bridge->bindings.ring_reader;
    if (bridge->reset_required || reader->state == TRECAP_RING_READER_RESET_REQUIRED ||
        reader->state == TRECAP_RING_READER_MALFORMED_LATCHED) {
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_REJECTED,
                                       TRECAP_CMD_REJECT_RESET_REQUIRED);
        return;
    }

    uint32_t status_word = 0u;
    trecap_csr_status_t status =
        trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &status_word);
    if (status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, status, false);
        return;
    }
    if (enable) {
        const uint32_t required = TCSR_STATUS_RING_CONFIGURED_MASK |
                                  TCSR_STATUS_TRANSPORT_EPOCH_IDLE_MASK;
        if (reader->state != TRECAP_RING_READER_ACTIVE ||
            (status_word & required) != required ||
            (status_word & (TCSR_STATUS_MALFORMED_CONFIG_MASK |
                            TCSR_STATUS_WRITER_BUSY_MASK)) != 0u) {
            trecap_bridge_set_result_state(outcome,
                                           TRECAP_CMD_DISPOSITION_REJECTED,
                                           TRECAP_CMD_REJECT_UNSAFE_STATE);
            return;
        }
        if (trecap_bridge_status_has_controls(status_word, true, true)) {
            reader->telemetry_disabled_by_reader = false;
            *bridge->bindings.transport_enabled = true;
            trecap_bridge_set_result_state(outcome,
                                           TRECAP_CMD_DISPOSITION_NOOP,
                                           TRECAP_CMD_REJECT_NONE);
            return;
        }

        status = trecap_bridge_write32(bridge,
                                       TCSR_CONTROL_OFFSET,
                                       TCSR_CONTROL_RING_WRITER_ENABLE_MASK);
        if (status == TRECAP_CSR_OK) {
            status = trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &status_word);
        }
        if (status != TRECAP_CSR_OK ||
            !trecap_bridge_status_has_controls(status_word, false, true)) {
            trecap_bridge_fail_from_csr(bridge,
                                        outcome,
                                        status == TRECAP_CSR_OK ? TRECAP_CSR_ERR_BAD_VALUE : status,
                                        true);
            return;
        }
        status = trecap_bridge_write32(bridge,
                                       TCSR_CONTROL_OFFSET,
                                       TCSR_CONTROL_TELEMETRY_ENABLE_MASK |
                                           TCSR_CONTROL_RING_WRITER_ENABLE_MASK);
        if (status == TRECAP_CSR_OK) {
            status = trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &status_word);
        }
        if (status != TRECAP_CSR_OK ||
            !trecap_bridge_status_has_controls(status_word, true, true)) {
            trecap_bridge_fail_from_csr(bridge,
                                        outcome,
                                        status == TRECAP_CSR_OK ? TRECAP_CSR_ERR_BAD_VALUE : status,
                                        true);
            return;
        }
        reader->telemetry_disabled_by_reader = false;
        *bridge->bindings.transport_enabled = true;
    } else {
        if (trecap_bridge_status_has_controls(status_word, false, false)) {
            reader->telemetry_disabled_by_reader = true;
            *bridge->bindings.transport_enabled = false;
            trecap_bridge_set_result_state(outcome,
                                           TRECAP_CMD_DISPOSITION_NOOP,
                                           TRECAP_CMD_REJECT_NONE);
            return;
        }
        status = trecap_bridge_write32(bridge, TCSR_CONTROL_OFFSET, 0u);
        if (status == TRECAP_CSR_OK) {
            status = trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &status_word);
        }
        if (status != TRECAP_CSR_OK ||
            !trecap_bridge_status_has_controls(status_word, false, false)) {
            trecap_bridge_fail_from_csr(bridge,
                                        outcome,
                                        status == TRECAP_CSR_OK ? TRECAP_CSR_ERR_BAD_VALUE : status,
                                        true);
            return;
        }
        reader->telemetry_disabled_by_reader = true;
        *bridge->bindings.transport_enabled = false;
    }
    trecap_bridge_set_result_state(outcome,
                                   TRECAP_CMD_DISPOSITION_APPLIED,
                                   TRECAP_CMD_REJECT_NONE);
}

static void trecap_bridge_execute_clear_counters(trecap_command_bridge_t *bridge,
                                                 trecap_command_bridge_outcome_t *outcome)
{
    if (!trecap_bridge_check_identity(bridge, outcome)) {
        return;
    }
    if (bridge->reset_required) {
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_REJECTED,
                                       TRECAP_CMD_REJECT_RESET_REQUIRED);
        return;
    }
    trecap_csr_status_t status =
        trecap_bridge_write32(bridge,
                              TCSR_COUNTER_CLEAR_OFFSET,
                              TCSR_COUNTER_CLEAR_TRANSPORT_COUNTERS_MASK);
    if (status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, status, true);
        return;
    }
    const uint32_t counter_offsets[] = {
        TCSR_DMA_DROP_COUNT_OFFSET,
        TCSR_DMA_PACKET_COUNT_OFFSET,
        TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET,
        TCSR_PACKET_FIFO_DROP_COUNT_OFFSET,
    };
    for (size_t i = 0u; i < sizeof(counter_offsets) / sizeof(counter_offsets[0]); ++i) {
        uint32_t value = UINT32_MAX;
        status = trecap_bridge_read32(bridge, counter_offsets[i], &value);
        if (status != TRECAP_CSR_OK || value != 0u) {
            trecap_bridge_fail_from_csr(bridge,
                                        outcome,
                                        status == TRECAP_CSR_OK ? TRECAP_CSR_ERR_BAD_VALUE : status,
                                        true);
            return;
        }
    }

    trecap_command_counters_reset(bridge->bindings.command_counters);
    trecap_ring_reader_counters_reset(&bridge->bindings.ring_reader->counters);
    trecap_udp_sender_counters_reset(bridge->bindings.udp_counters);
    *bridge->bindings.records_consumed = 0u;
    *bridge->bindings.records_sent_or_dropped = 0u;
    outcome->counters_cleared = true;
    trecap_bridge_set_result_state(outcome,
                                   TRECAP_CMD_DISPOSITION_APPLIED,
                                   TRECAP_CMD_REJECT_NONE);
}

static bool trecap_bridge_replay_decode(uint32_t raw,
                                        uint16_t *epoch,
                                        bool *pending,
                                        bool *accept,
                                        bool *reject,
                                        bool *rearm_required)
{
    if (epoch == NULL || pending == NULL || accept == NULL || reject == NULL ||
        rearm_required == NULL) {
        return false;
    }
    *epoch = (uint16_t)((raw & TCSR_REPLAY_STATUS_RESULT_EPOCH_MASK) >>
                        TCSR_REPLAY_STATUS_RESULT_EPOCH_LSB);
    *pending = (raw & TCSR_REPLAY_STATUS_PENDING_MASK) != 0u;
    *accept = (raw & TCSR_REPLAY_STATUS_LAST_ACCEPT_MASK) != 0u;
    *reject = (raw & TCSR_REPLAY_STATUS_LAST_REJECT_MASK) != 0u;
    *rearm_required = (raw & TCSR_REPLAY_STATUS_REARM_REQUIRED_MASK) != 0u;
    return (raw & TCSR_REPLAY_STATUS_RESERVED_15_11_MASK) == 0u;
}

static void trecap_bridge_execute_replay(trecap_command_bridge_t *bridge,
                                         trecap_command_bridge_outcome_t *outcome)
{
    if (!trecap_bridge_check_identity(bridge, outcome)) {
        return;
    }
    if (bridge->reset_required ||
        bridge->bindings.ring_reader->state != TRECAP_RING_READER_ACTIVE) {
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_REJECTED,
                                       TRECAP_CMD_REJECT_RESET_REQUIRED);
        return;
    }

    uint32_t status_word = 0u;
    trecap_csr_status_t status =
        trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &status_word);
    if (status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, status, false);
        return;
    }
    if (!*bridge->bindings.transport_enabled ||
        !trecap_bridge_status_source_is(status_word, TCSR_SOURCE_MODE_BRAM_REPLAY)) {
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_REJECTED,
                                       TRECAP_CMD_REJECT_UNSAFE_STATE);
        return;
    }

    uint32_t reject_before = 0u;
    if (!trecap_bridge_begin_mutation(bridge, outcome, &reject_before)) {
        return;
    }
    uint32_t replay_raw = 0u;
    status = trecap_bridge_read32(bridge, TCSR_REPLAY_STATUS_OFFSET, &replay_raw);
    if (status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, status, false);
        return;
    }
    uint16_t baseline_epoch = 0u;
    bool pending = false;
    bool accept = false;
    bool reject = false;
    bool rearm_required = false;
    if (!trecap_bridge_replay_decode(replay_raw,
                                     &baseline_epoch,
                                     &pending,
                                     &accept,
                                     &reject,
                                     &rearm_required)) {
        trecap_bridge_fail_from_csr(bridge, outcome, TRECAP_CSR_ERR_BAD_VALUE, false);
        return;
    }

    /* A retained CSR request already pending has no free result owner. Writing
     * another START would be rejected by the bank and could misattribute the
     * older terminal epoch to this command. */
    if (pending) {
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_REJECTED,
                                       TRECAP_CMD_REJECT_UNSAFE_STATE);
        return;
    }

    if (rearm_required) {
        const uint32_t replay_busy = TCSR_REPLAY_STATUS_REPLAY_ACTIVE_MASK |
                                     TCSR_REPLAY_STATUS_REPLAY_PATH_BUSY_MASK |
                                     TCSR_REPLAY_STATUS_E2E_BUSY_MASK;
        const uint32_t transport_busy = TCSR_STATUS_WRITER_BUSY_MASK |
                                        TCSR_STATUS_THR2_COMMIT_PENDING_MASK |
                                        TCSR_STATUS_SOURCE_COMMIT_PENDING_MASK |
                                        TCSR_STATUS_SOURCE_TRANSITION_BUSY_MASK;
        if ((replay_raw & replay_busy) != 0u ||
            (status_word & transport_busy) != 0u ||
            (status_word & TCSR_STATUS_TRANSPORT_EPOCH_IDLE_MASK) == 0u) {
            /* REARM clears only a completed failed epoch. It is never a live
             * replay abort and must not rely on an intentionally rejected CSR
             * write as its admission test. */
            trecap_bridge_set_result_state(outcome,
                                           TRECAP_CMD_DISPOSITION_REJECTED,
                                           TRECAP_CMD_REJECT_UNSAFE_STATE);
            return;
        }
        status = trecap_bridge_write32(bridge,
                                       TCSR_REPLAY_CONTROL_OFFSET,
                                       TCSR_REPLAY_CONTROL_REARM_MASK);
        if (status != TRECAP_CSR_OK) {
            trecap_bridge_fail_from_csr(bridge, outcome, status, true);
            return;
        }
        bool rearmed = false;
        for (uint32_t poll = 0u; poll < bridge->poll_limit; ++poll) {
            status = trecap_bridge_read32(bridge, TCSR_REPLAY_STATUS_OFFSET, &replay_raw);
            if (status != TRECAP_CSR_OK) {
                trecap_bridge_fail_from_csr(bridge, outcome, status, true);
                return;
            }
            uint16_t epoch = 0u;
            if (!trecap_bridge_replay_decode(replay_raw,
                                             &epoch,
                                             &pending,
                                             &accept,
                                             &reject,
                                             &rearm_required)) {
                trecap_bridge_fail_from_csr(bridge, outcome, TRECAP_CSR_ERR_BAD_VALUE, true);
                return;
            }
            if (epoch != baseline_epoch) {
                /* REARM clears admission state but is not a START decision and
                 * therefore must not consume a result epoch. */
                trecap_bridge_fail_from_csr(bridge,
                                            outcome,
                                            TRECAP_CSR_ERR_BAD_VALUE,
                                            true);
                return;
            }
            const uint32_t must_clear = TCSR_REPLAY_STATUS_PENDING_MASK |
                                        TCSR_REPLAY_STATUS_LAST_ACCEPT_MASK |
                                        TCSR_REPLAY_STATUS_LAST_REJECT_MASK |
                                        TCSR_REPLAY_STATUS_REPLAY_ACTIVE_MASK |
                                        TCSR_REPLAY_STATUS_REPLAY_PATH_BUSY_MASK |
                                        TCSR_REPLAY_STATUS_E2E_BUSY_MASK |
                                        TCSR_REPLAY_STATUS_ERROR_MASK |
                                        TCSR_REPLAY_STATUS_REARM_REQUIRED_MASK;
            if ((replay_raw & must_clear) == 0u) {
                rearmed = true;
                break;
            }
        }
        if (!rearmed) {
            trecap_bridge_fail_from_csr(bridge, outcome, TRECAP_CSR_ERR_TIMEOUT, true);
            return;
        }
    }

    /* Do not pre-gate on start_ready: the FPGA admission owner must retain an
     * explicit accept or reject result for every raw CSR START request. */
    status = trecap_bridge_write32(bridge,
                                   TCSR_REPLAY_CONTROL_OFFSET,
                                   TCSR_REPLAY_CONTROL_START_MASK);
    if (status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, status, true);
        return;
    }

    bool terminal = false;
    for (uint32_t poll = 0u; poll < bridge->poll_limit; ++poll) {
        status = trecap_bridge_read32(bridge, TCSR_REPLAY_STATUS_OFFSET, &replay_raw);
        if (status != TRECAP_CSR_OK) {
            trecap_bridge_fail_from_csr(bridge, outcome, status, true);
            return;
        }
        uint16_t epoch = 0u;
        if (!trecap_bridge_replay_decode(replay_raw,
                                         &epoch,
                                         &pending,
                                         &accept,
                                         &reject,
                                         &rearm_required)) {
            trecap_bridge_fail_from_csr(bridge, outcome, TRECAP_CSR_ERR_BAD_VALUE, true);
            return;
        }
        if (!pending && epoch != baseline_epoch) {
            if (accept == reject) {
                trecap_bridge_fail_from_csr(bridge, outcome, TRECAP_CSR_ERR_BAD_VALUE, true);
                return;
            }
            terminal = true;
            break;
        }
    }
    if (!terminal) {
        if (trecap_bridge_reject_changed(bridge, outcome, reject_before, NULL) &&
            outcome->status != TRECAP_COMMAND_BRIDGE_FAILED) {
            outcome->csr_status = TRECAP_CSR_ERR_BAD_VALUE;
            trecap_bridge_set_result_state(outcome,
                                           TRECAP_CMD_DISPOSITION_REJECTED,
                                           TRECAP_CMD_REJECT_CSR);
            return;
        }
        trecap_bridge_fail_from_csr(bridge, outcome, TRECAP_CSR_ERR_TIMEOUT, true);
        return;
    }
    if (accept) {
        /* The origin-correlated replay epoch/result is authoritative. A KEY
         * request can legitimately increment the global CSR reject counter
         * while this CSR START is pending, so that unrelated delta must not
         * invalidate a retained CSR accept. */
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_APPLIED,
                                       TRECAP_CMD_REJECT_NONE);
    } else {
        /* A retained, origin-correlated admission reject is likewise a
         * terminal healthy FPGA decision. Its associated global reject-count
         * increment is diagnostic, not the correlation mechanism. */
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_REJECTED,
                                       TRECAP_CMD_REJECT_UNSAFE_STATE);
    }
}

typedef struct trecap_bridge_control_snapshot {
    bool telemetry_enabled;
    bool writer_enabled;
    bool controls_changed;
} trecap_bridge_control_snapshot_t;

typedef struct trecap_bridge_config_mirror_snapshot {
    uint32_t packet_enable;
    uint32_t wave_decim;
    uint32_t spec_mode;
    uint32_t spec_shift;
    uint32_t source_mode;
} trecap_bridge_config_mirror_snapshot_t;

static void trecap_bridge_snapshot_config_mirrors(
    const trecap_command_bridge_t *bridge,
    trecap_bridge_config_mirror_snapshot_t *snapshot)
{
    snapshot->packet_enable = *bridge->bindings.active_packet_enable;
    snapshot->wave_decim = *bridge->bindings.active_wave_decim;
    snapshot->spec_mode = *bridge->bindings.active_spec_mode;
    snapshot->spec_shift = *bridge->bindings.active_spec_shift;
    snapshot->source_mode = *bridge->bindings.active_source_mode;
}

static void trecap_bridge_restore_config_mirrors(
    trecap_command_bridge_t *bridge,
    const trecap_bridge_config_mirror_snapshot_t *snapshot)
{
    *bridge->bindings.active_packet_enable = snapshot->packet_enable;
    *bridge->bindings.active_wave_decim = snapshot->wave_decim;
    *bridge->bindings.active_spec_mode = snapshot->spec_mode;
    *bridge->bindings.active_spec_shift = snapshot->spec_shift;
    *bridge->bindings.active_source_mode = snapshot->source_mode;
}

static bool trecap_bridge_is_quiesced_config_command(uint16_t cmd_type)
{
    return cmd_type == TCMD_TYPE_SET_SOURCE_MODE ||
           cmd_type == TCMD_TYPE_SET_PACKET_ENABLE ||
           cmd_type == TCMD_TYPE_SET_WAVE_DECIM || cmd_type == TCMD_TYPE_SET_SPEC_MODE ||
           cmd_type == TCMD_TYPE_SET_SPEC_SHIFT;
}

static bool trecap_bridge_config_noop(trecap_command_bridge_t *bridge,
                                      const trecap_command_packet_t *cmd,
                                      trecap_command_bridge_outcome_t *outcome)
{
    if (!trecap_bridge_check_identity(bridge, outcome)) {
        return true;
    }
    uint32_t value = 0u;
    trecap_csr_status_t status = TRECAP_CSR_OK;
    uint32_t *mirror = NULL;
    uint32_t offset = 0u;
    switch (cmd->cmd_type) {
    case TCMD_TYPE_SET_SOURCE_MODE:
        status = trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &value);
        if (status == TRECAP_CSR_OK && trecap_bridge_status_source_is(value, cmd->arg0)) {
            *bridge->bindings.active_source_mode = cmd->arg0;
            trecap_bridge_set_result_state(outcome,
                                           TRECAP_CMD_DISPOSITION_NOOP,
                                           TRECAP_CMD_REJECT_NONE);
            return true;
        }
        break;
    case TCMD_TYPE_SET_PACKET_ENABLE:
        offset = TCSR_PACKET_ENABLE_OFFSET;
        mirror = bridge->bindings.active_packet_enable;
        break;
    case TCMD_TYPE_SET_WAVE_DECIM:
        offset = TCSR_WAVE_DECIM_OFFSET;
        mirror = bridge->bindings.active_wave_decim;
        break;
    case TCMD_TYPE_SET_SPEC_MODE:
        offset = TCSR_SPEC_MODE_OFFSET;
        mirror = bridge->bindings.active_spec_mode;
        break;
    case TCMD_TYPE_SET_SPEC_SHIFT:
        offset = TCSR_SPEC_SHIFT_OFFSET;
        mirror = bridge->bindings.active_spec_shift;
        break;
    default:
        return false;
    }
    if (cmd->cmd_type != TCMD_TYPE_SET_SOURCE_MODE) {
        status = trecap_bridge_read32(bridge, offset, &value);
        if (status == TRECAP_CSR_OK && value == cmd->arg0) {
            *mirror = cmd->arg0;
            trecap_bridge_set_result_state(outcome,
                                           TRECAP_CMD_DISPOSITION_NOOP,
                                           TRECAP_CMD_REJECT_NONE);
            return true;
        }
    }
    if (status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, status, false);
        return true;
    }
    return false;
}

static bool trecap_bridge_replay_is_quiescent(uint32_t replay_status)
{
    const uint32_t busy_mask = TCSR_REPLAY_STATUS_PENDING_MASK |
                               TCSR_REPLAY_STATUS_REPLAY_ACTIVE_MASK |
                               TCSR_REPLAY_STATUS_REPLAY_PATH_BUSY_MASK |
                               TCSR_REPLAY_STATUS_E2E_BUSY_MASK;
    return (replay_status & (busy_mask | TCSR_REPLAY_STATUS_RESERVED_15_11_MASK)) == 0u;
}

static bool trecap_bridge_quiesce_config(trecap_command_bridge_t *bridge,
                                         trecap_bridge_control_snapshot_t *snapshot,
                                         trecap_command_bridge_outcome_t *outcome)
{
    memset(snapshot, 0, sizeof(*snapshot));
    uint32_t status_word = 0u;
    trecap_csr_status_t status =
        trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &status_word);
    if (status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, status, false);
        return false;
    }
    snapshot->telemetry_enabled =
        (status_word & TCSR_STATUS_TELEMETRY_ENABLED_MASK) != 0u;
    snapshot->writer_enabled =
        (status_word & TCSR_STATUS_RING_WRITER_ENABLED_MASK) != 0u;
    if (snapshot->telemetry_enabled && !snapshot->writer_enabled) {
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_REJECTED,
                                       TRECAP_CMD_REJECT_UNSAFE_STATE);
        return false;
    }

    uint32_t replay_status = 0u;
    status = trecap_bridge_read32(bridge, TCSR_REPLAY_STATUS_OFFSET, &replay_status);
    if (status != TRECAP_CSR_OK) {
        trecap_bridge_fail_from_csr(bridge, outcome, status, false);
        return false;
    }
    if (!trecap_bridge_replay_is_quiescent(replay_status)) {
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_REJECTED,
                                       TRECAP_CMD_REJECT_UNSAFE_STATE);
        return false;
    }

    if (snapshot->telemetry_enabled || snapshot->writer_enabled) {
        status = trecap_bridge_write32(bridge, TCSR_CONTROL_OFFSET, 0u);
        snapshot->controls_changed = true;
        if (status != TRECAP_CSR_OK) {
            trecap_bridge_fail_from_csr(bridge, outcome, status, true);
            return false;
        }
    }

    for (uint32_t poll = 0u; poll < bridge->poll_limit; ++poll) {
        status = trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &status_word);
        if (status != TRECAP_CSR_OK) {
            trecap_bridge_fail_from_csr(bridge,
                                        outcome,
                                        status,
                                        snapshot->controls_changed);
            return false;
        }
        status = trecap_bridge_read32(bridge, TCSR_REPLAY_STATUS_OFFSET, &replay_status);
        if (status != TRECAP_CSR_OK) {
            trecap_bridge_fail_from_csr(bridge,
                                        outcome,
                                        status,
                                        snapshot->controls_changed);
            return false;
        }
        const uint32_t status_busy = TCSR_STATUS_WRITER_BUSY_MASK |
                                     TCSR_STATUS_SOURCE_COMMIT_PENDING_MASK |
                                     TCSR_STATUS_SOURCE_TRANSITION_BUSY_MASK;
        if (trecap_bridge_status_has_controls(status_word, false, false) &&
            (status_word & status_busy) == 0u &&
            (status_word & TCSR_STATUS_TRANSPORT_EPOCH_IDLE_MASK) != 0u &&
            trecap_bridge_replay_is_quiescent(replay_status)) {
            *bridge->bindings.transport_enabled = false;
            bridge->bindings.ring_reader->telemetry_disabled_by_reader = true;
            return true;
        }
    }
    trecap_bridge_fail_from_csr(bridge,
                                outcome,
                                TRECAP_CSR_ERR_TIMEOUT,
                                snapshot->controls_changed);
    return false;
}

static bool trecap_bridge_restore_controls(trecap_command_bridge_t *bridge,
                                           const trecap_bridge_control_snapshot_t *snapshot,
                                           trecap_command_bridge_outcome_t *outcome)
{
    uint32_t status_word = 0u;
    trecap_csr_status_t status = TRECAP_CSR_OK;
    if (snapshot->writer_enabled) {
        status = trecap_bridge_write32(bridge,
                                       TCSR_CONTROL_OFFSET,
                                       TCSR_CONTROL_RING_WRITER_ENABLE_MASK);
        if (status == TRECAP_CSR_OK) {
            status = trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &status_word);
        }
        if (status != TRECAP_CSR_OK ||
            !trecap_bridge_status_has_controls(status_word, false, true)) {
            trecap_bridge_fail_from_csr(bridge,
                                        outcome,
                                        status == TRECAP_CSR_OK ? TRECAP_CSR_ERR_BAD_VALUE : status,
                                        true);
            return false;
        }
    }
    if (snapshot->telemetry_enabled) {
        status = trecap_bridge_write32(bridge,
                                       TCSR_CONTROL_OFFSET,
                                       TCSR_CONTROL_TELEMETRY_ENABLE_MASK |
                                           TCSR_CONTROL_RING_WRITER_ENABLE_MASK);
        if (status == TRECAP_CSR_OK) {
            status = trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &status_word);
        }
        if (status != TRECAP_CSR_OK ||
            !trecap_bridge_status_has_controls(status_word, true, true)) {
            trecap_bridge_fail_from_csr(bridge,
                                        outcome,
                                        status == TRECAP_CSR_OK ? TRECAP_CSR_ERR_BAD_VALUE : status,
                                        true);
            return false;
        }
    }
    /* Always prove the final levels, including the prior-disabled case where
     * restoration requires no write. This is the local-state commit barrier. */
    status = trecap_bridge_read32(bridge, TCSR_STATUS_OFFSET, &status_word);
    if (status != TRECAP_CSR_OK ||
        !trecap_bridge_status_has_controls(status_word,
                                           snapshot->telemetry_enabled,
                                           snapshot->writer_enabled)) {
        trecap_bridge_fail_from_csr(bridge,
                                    outcome,
                                    status == TRECAP_CSR_OK ? TRECAP_CSR_ERR_BAD_VALUE : status,
                                    true);
        return false;
    }
    *bridge->bindings.transport_enabled =
        snapshot->telemetry_enabled && snapshot->writer_enabled;
    bridge->bindings.ring_reader->telemetry_disabled_by_reader =
        !*bridge->bindings.transport_enabled;
    return true;
}

static void trecap_bridge_execute_command_unwrapped(trecap_command_bridge_t *bridge,
                                                    const trecap_command_packet_t *cmd,
                                                    trecap_command_bridge_outcome_t *outcome)
{
    switch (cmd->cmd_type) {
    case TCMD_TYPE_SET_THR2:
        trecap_bridge_execute_thr2(bridge, cmd, outcome);
        break;
    case TCMD_TYPE_CLEAR_METRICS:
        trecap_bridge_execute_pulse(bridge,
                                    TCSR_CONTROL_OFFSET,
                                    TCSR_CONTROL_CLEAR_METRICS_MASK,
                                    outcome);
        break;
    case TCMD_TYPE_SET_SOURCE_MODE:
        trecap_bridge_execute_source(bridge, cmd, outcome);
        break;
    case TCMD_TYPE_SET_PACKET_ENABLE:
        (void)trecap_bridge_apply_rw32(bridge,
                                       TCSR_PACKET_ENABLE_OFFSET,
                                       cmd->arg0,
                                       bridge->bindings.active_packet_enable,
                                       outcome);
        break;
    case TCMD_TYPE_SET_WAVE_DECIM:
        (void)trecap_bridge_apply_rw32(bridge,
                                       TCSR_WAVE_DECIM_OFFSET,
                                       cmd->arg0,
                                       bridge->bindings.active_wave_decim,
                                       outcome);
        break;
    case TCMD_TYPE_SET_SPEC_SHIFT:
        (void)trecap_bridge_apply_rw32(bridge,
                                       TCSR_SPEC_SHIFT_OFFSET,
                                       cmd->arg0,
                                       bridge->bindings.active_spec_shift,
                                       outcome);
        break;
    case TCMD_TYPE_SET_SPEC_MODE:
        (void)trecap_bridge_apply_rw32(bridge,
                                       TCSR_SPEC_MODE_OFFSET,
                                       cmd->arg0,
                                       bridge->bindings.active_spec_mode,
                                       outcome);
        break;
    case TCMD_TYPE_SET_TELEMETRY_ENABLE:
        trecap_bridge_execute_enable(bridge, cmd->arg0 != 0u, outcome);
        break;
    case TCMD_TYPE_CONFIGURE_DDR_RING:
        trecap_bridge_execute_configure(bridge, outcome);
        break;
    case TCMD_TYPE_RESET_TRANSPORT:
        trecap_bridge_execute_reset(bridge, outcome);
        break;
    case TCMD_TYPE_CLEAR_COUNTERS:
        trecap_bridge_execute_clear_counters(bridge, outcome);
        break;
    case TCMD_TYPE_START_BRAM_REPLAY:
        trecap_bridge_execute_replay(bridge, outcome);
        break;
    case TCMD_TYPE_READ_STATUS_VERSION:
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_NOOP,
                                       TRECAP_CMD_REJECT_NONE);
        break;
    default:
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_REJECTED,
                                       TRECAP_CMD_REJECT_UNSUPPORTED_TYPE);
        break;
    }
}

static void trecap_bridge_execute_command(trecap_command_bridge_t *bridge,
                                          const trecap_command_packet_t *cmd,
                                          trecap_command_bridge_outcome_t *outcome)
{
    const trecap_ring_reader_state_t reader_state = bridge->bindings.ring_reader->state;
    if (cmd->cmd_type != TCMD_TYPE_RESET_TRANSPORT &&
        cmd->cmd_type != TCMD_TYPE_READ_STATUS_VERSION &&
        (bridge->reset_required || reader_state == TRECAP_RING_READER_RESET_REQUIRED ||
         reader_state == TRECAP_RING_READER_MALFORMED_LATCHED)) {
        bridge->reset_required = true;
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_REJECTED,
                                       TRECAP_CMD_REJECT_RESET_REQUIRED);
        return;
    }
    /* READ_STATUS_VERSION is deliberately an identity-diagnostic exception.
     * Every mutation, including a potential no-op, proves the exact CSR ID and
     * VERSION before it can report success or issue a write. */
    if (cmd->cmd_type != TCMD_TYPE_READ_STATUS_VERSION &&
        !trecap_bridge_check_identity(bridge, outcome)) {
        return;
    }
    if (!trecap_bridge_is_quiesced_config_command(cmd->cmd_type)) {
        trecap_bridge_execute_command_unwrapped(bridge, cmd, outcome);
        return;
    }
    if (trecap_bridge_config_noop(bridge, cmd, outcome)) {
        return;
    }

    trecap_bridge_control_snapshot_t control_snapshot;
    trecap_bridge_config_mirror_snapshot_t mirror_snapshot;
    trecap_bridge_snapshot_config_mirrors(bridge, &mirror_snapshot);
    if (!trecap_bridge_quiesce_config(bridge, &control_snapshot, outcome)) {
        return;
    }
    trecap_bridge_execute_command_unwrapped(bridge, cmd, outcome);
    if (outcome->disposition != TRECAP_CMD_DISPOSITION_APPLIED &&
        outcome->disposition != TRECAP_CMD_DISPOSITION_NOOP) {
        /* Quiescing already changed transport levels. A post-quiesce reject is
         * kept disabled; a partial/ambiguous failure has already latched the
         * software RESET_REQUIRED state. Never re-enable after either case. */
        trecap_bridge_restore_config_mirrors(bridge, &mirror_snapshot);
        return;
    }
    if (!trecap_bridge_restore_controls(bridge, &control_snapshot, outcome)) {
        /* Local configuration becomes committed only after both target CSR
         * readback and safe control restore readback have succeeded. */
        trecap_bridge_restore_config_mirrors(bridge, &mirror_snapshot);
    }
}

static void trecap_bridge_build_result(trecap_command_bridge_t *bridge,
                                       const trecap_command_packet_t *cmd,
                                       trecap_command_bridge_outcome_t *outcome,
                                       bool require_snapshot)
{
    uint32_t fpga_status = 0u;
    uint32_t csr_version = 0u;
    const trecap_csr_status_t snapshot_status =
        trecap_bridge_snapshot_raw(bridge, &fpga_status, &csr_version);
    if (snapshot_status != TRECAP_CSR_OK && require_snapshot &&
        (outcome->disposition == TRECAP_CMD_DISPOSITION_APPLIED ||
         outcome->disposition == TRECAP_CMD_DISPOSITION_NOOP)) {
        const bool writes_started = outcome->disposition == TRECAP_CMD_DISPOSITION_APPLIED;
        trecap_bridge_fail_from_csr(bridge, outcome, snapshot_status, writes_started);
    }
    trecap_command_v2_result_init(&outcome->result_packet,
                                  cmd->cmd_type,
                                  cmd->seq,
                                  outcome->disposition,
                                  outcome->reject_reason,
                                  fpga_status,
                                  csr_version);
    outcome->has_result = true;
}

static void trecap_bridge_note_outcome(trecap_command_bridge_t *bridge,
                                       trecap_command_bridge_outcome_t *outcome)
{
    if (outcome->disposition == TRECAP_CMD_DISPOSITION_APPLIED &&
        !outcome->counters_cleared) {
        bridge->bindings.command_counters->commands_applied += 1u;
    }
    if ((outcome->disposition == TRECAP_CMD_DISPOSITION_REJECTED ||
         outcome->disposition == TRECAP_CMD_DISPOSITION_FAILED) &&
        outcome->reject_reason != TRECAP_CMD_REJECT_NONE) {
        /* The result reason is an HPS command outcome. FPGA's own CSR reject
         * counter remains separately included in STATUS accounting. */
        trecap_command_server_t counter_owner;
        memset(&counter_owner, 0, sizeof(counter_owner));
        counter_owner.counters = *bridge->bindings.command_counters;
        trecap_command_server_note_reject(&counter_owner, outcome->reject_reason);
        *bridge->bindings.command_counters = counter_owner.counters;
    }
}

static void trecap_bridge_cache_result(trecap_command_bridge_t *bridge,
                                       const trecap_command_packet_t *cmd,
                                       const trecap_command_bridge_outcome_t *outcome)
{
    bridge->last_seq = cmd->seq;
    bridge->last_request = *cmd;
    bridge->cached_result = outcome->result_packet;
    bridge->cached_result_valid = true;
    bridge->ledger_valid = true;
}

trecap_command_bridge_status_t trecap_command_bridge_handle_v2(
    trecap_command_bridge_t *bridge,
    const trecap_command_packet_t *cmd,
    trecap_command_bridge_outcome_t *outcome,
    char *err_buf,
    size_t err_buf_len)
{
    if (bridge == NULL || cmd == NULL || outcome == NULL) {
        trecap_bridge_set_error(err_buf, err_buf_len, "null v2 command bridge argument");
        return TRECAP_COMMAND_BRIDGE_ERR_NULL;
    }
    trecap_command_bridge_outcome_init(outcome);
    if (cmd->version != (uint16_t)TCMD_VERSION_V2 || cmd->cmd_type == TCMD_TYPE_PING ||
        trecap_command_packet_validate_envelope(cmd) != TRECAP_CMD_REJECT_NONE) {
        trecap_bridge_set_error(err_buf, err_buf_len, "command is not an envelope-valid v2 transaction");
        return TRECAP_COMMAND_BRIDGE_ERR_CONFIG;
    }

    if (bridge->ledger_valid) {
        if (cmd->seq == bridge->last_seq) {
            if (trecap_command_packet_equal(cmd, &bridge->last_request) &&
                bridge->cached_result_valid) {
                outcome->status = TRECAP_COMMAND_BRIDGE_DUPLICATE;
                outcome->disposition =
                    (trecap_cmd_disposition_t)bridge->cached_result.disposition;
                outcome->reject_reason =
                    (trecap_cmd_reject_reason_t)bridge->cached_result.reject_reason;
                outcome->result_packet = bridge->cached_result;
                outcome->has_result = true;
                outcome->duplicate = true;
                outcome->applied = false;
                return outcome->status;
            }
            trecap_bridge_set_result_state(outcome,
                                           TRECAP_CMD_DISPOSITION_REJECTED,
                                           TRECAP_CMD_REJECT_SEQUENCE_CONFLICT);
            trecap_bridge_build_result(bridge, cmd, outcome, false);
            trecap_bridge_note_outcome(bridge, outcome);
            return outcome->status;
        }
        if (!trecap_command_bridge_serial_is_newer(cmd->seq, bridge->last_seq)) {
            trecap_bridge_set_result_state(outcome,
                                           TRECAP_CMD_DISPOSITION_REJECTED,
                                           TRECAP_CMD_REJECT_SEQUENCE_STALE);
            trecap_bridge_build_result(bridge, cmd, outcome, false);
            trecap_bridge_note_outcome(bridge, outcome);
            return outcome->status;
        }
    }

    const trecap_cmd_reject_reason_t args_reason =
        trecap_command_packet_validate_args(cmd);
    if (args_reason != TRECAP_CMD_REJECT_NONE) {
        trecap_bridge_set_result_state(outcome,
                                       TRECAP_CMD_DISPOSITION_REJECTED,
                                       args_reason);
    } else {
        trecap_bridge_execute_command(bridge, cmd, outcome);
    }

    const bool require_snapshot = cmd->cmd_type == TCMD_TYPE_READ_STATUS_VERSION ||
                                  outcome->disposition == TRECAP_CMD_DISPOSITION_APPLIED ||
                                  outcome->disposition == TRECAP_CMD_DISPOSITION_NOOP;
    trecap_bridge_build_result(bridge, cmd, outcome, require_snapshot);
    trecap_bridge_note_outcome(bridge, outcome);
    /* Cache before any caller attempts UDP transmission. Send failure therefore
     * cannot cause a retry to reapply an already-decided transaction. */
    trecap_bridge_cache_result(bridge, cmd, outcome);
    return outcome->status;
}

trecap_command_bridge_status_t trecap_command_bridge_apply_v1(
    trecap_command_bridge_t *bridge,
    const trecap_command_packet_t *cmd,
    trecap_command_bridge_outcome_t *outcome,
    char *err_buf,
    size_t err_buf_len)
{
    if (bridge == NULL || cmd == NULL || outcome == NULL) {
        trecap_bridge_set_error(err_buf, err_buf_len, "null v1 command bridge argument");
        return TRECAP_COMMAND_BRIDGE_ERR_NULL;
    }
    trecap_command_bridge_outcome_init(outcome);
    if (cmd->version != (uint16_t)TCMD_VERSION_V1 || cmd->cmd_type == TCMD_TYPE_PING) {
        trecap_bridge_set_error(err_buf, err_buf_len, "command is not a v1 CSR mutation");
        return TRECAP_COMMAND_BRIDGE_ERR_CONFIG;
    }
    const trecap_cmd_reject_reason_t reason = trecap_command_packet_validate_fields(cmd);
    if (reason != TRECAP_CMD_REJECT_NONE) {
        trecap_bridge_set_result_state(outcome, TRECAP_CMD_DISPOSITION_REJECTED, reason);
    } else {
        trecap_bridge_execute_command(bridge, cmd, outcome);
    }
    trecap_bridge_note_outcome(bridge, outcome);
    outcome->has_result = false;
    return outcome->status;
}

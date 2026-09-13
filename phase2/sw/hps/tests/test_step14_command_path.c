/* SPDX-License-Identifier: MIT
 * Deterministic host verification for the Step-14 HPS command path.
 * File class: [1] hand-written verification source.
 *
 * This dependency-free test drives command_server and command_bridge through
 * explicit MMIO/ring/socket seams. It is host evidence only; no claim is made
 * about /dev/mem, FPGA timing, Ethernet, or board execution.
 */

#include <arpa/inet.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>

#include "command_bridge.h"

#define TEST_FAKE_CSR_WORDS 1024u
#define TEST_MAX_WRITES 128u
#define TEST_CAPTURE_BYTES 2048u

_Static_assert(sizeof(trecap_command_packet_t) == TCMD_PACKET_BYTES,
               "command request host view must be 28 bytes");
_Static_assert(sizeof(trecap_command_v2_result_packet_t) == TCMD_RESULT_BYTES,
               "command result host view must be 32 bytes");
_Static_assert(TRECAP_CMD_DISPOSITION_APPLIED == TCMD_DISPOSITION_APPLIED,
               "disposition enum mismatch");
_Static_assert(TRECAP_CMD_DISPOSITION_NOOP == TCMD_DISPOSITION_NOOP,
               "disposition enum mismatch");
_Static_assert(TRECAP_CMD_DISPOSITION_REJECTED == TCMD_DISPOSITION_REJECTED,
               "disposition enum mismatch");
_Static_assert(TRECAP_CMD_DISPOSITION_FAILED == TCMD_DISPOSITION_FAILED,
               "disposition enum mismatch");
_Static_assert(TRECAP_CMD_REJECT_VERSION_MISMATCH == TCMD_REJECT_VERSION_MISMATCH,
               "reject enum mismatch");

#define TEST_CHECK(condition)                                                                  \
    do {                                                                                       \
        if (!(condition)) {                                                                    \
            fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #condition);             \
            return false;                                                                      \
        }                                                                                      \
    } while (0)

typedef enum test_replay_decision {
    TEST_REPLAY_ACCEPT = 0,
    TEST_REPLAY_REJECT = 1,
    TEST_REPLAY_TIMEOUT = 2
} test_replay_decision_t;

typedef struct test_write_trace {
    uint32_t offset;
    uint32_t value;
} test_write_trace_t;

typedef struct test_fake_hw {
    uint32_t regs[TEST_FAKE_CSR_WORDS];
    test_write_trace_t writes[TEST_MAX_WRITES];
    size_t write_calls;
    size_t successful_writes;
    size_t control_write_calls;
    size_t fail_write_call;
    uint32_t reject_write_offset;
    bool reject_write_enabled;
    size_t suppress_control_write_number;
    bool suppress_all_control_levels;
    uint32_t fail_read_offset;
    bool fail_read_enabled;
    test_replay_decision_t replay_decision;
    bool replay_accept_counter_increment;
    bool replay_rearm_epoch_increment;
    bool replay_rearm_leave_retained_state;
    bool unrelated_reject_on_thr2_commit;
    bool unrelated_reject_on_clear_metrics;
    uint32_t replay_start_pulses;
    uint32_t replay_rearm_write_attempts;
    uint32_t replay_rearm_pulses;
    uint32_t counter_clear_pulses;
    uint32_t ring_reset_calls;
    uint32_t ring_configure_calls;
    uint32_t ring_commit_calls;
    uint32_t ring_snapshot_calls;
    uint64_t ring_wr;
} test_fake_hw_t;

typedef struct test_fixture {
    test_fake_hw_t hw;
    trecap_csr_window_t csr;
    trecap_ring_reader_t reader;
    trecap_hps_runtime_config_t cfg;
    trecap_command_counters_t command_counters;
    trecap_udp_sender_counters_t udp_counters;
    trecap_command_bridge_t bridge;
    bool transport_enabled;
    uint64_t active_thr2;
    uint32_t active_packet_enable;
    uint32_t active_wave_decim;
    uint32_t active_spec_mode;
    uint32_t active_spec_shift;
    uint32_t active_source_mode;
    uint64_t records_consumed;
    uint64_t records_sent_or_dropped;
} test_fixture_t;

typedef struct test_send_capture {
    size_t calls;
    int fd;
    int flags;
    uint8_t bytes[TEST_CAPTURE_BYTES];
    size_t byte_count;
    struct sockaddr_in destination;
    socklen_t destination_len;
    int forced_errno;
} test_send_capture_t;

static test_send_capture_t g_send_capture;

ssize_t trecap_command_server_sendto(int fd,
                                     const void *buf,
                                     size_t len,
                                     int flags,
                                     const struct sockaddr *dest_addr,
                                     socklen_t addrlen)
{
    g_send_capture.calls += 1u;
    g_send_capture.fd = fd;
    g_send_capture.flags = flags;
    g_send_capture.destination_len = addrlen;
    if (g_send_capture.forced_errno != 0) {
        errno = g_send_capture.forced_errno;
        return -1;
    }
    if (buf == NULL || dest_addr == NULL || len > sizeof(g_send_capture.bytes) ||
        addrlen < (socklen_t)sizeof(struct sockaddr_in)) {
        errno = EINVAL;
        return -1;
    }
    memcpy(g_send_capture.bytes, buf, len);
    g_send_capture.byte_count = len;
    memcpy(&g_send_capture.destination, dest_addr, sizeof(g_send_capture.destination));
    return (ssize_t)len;
}

static uint32_t *test_fake_reg(test_fake_hw_t *hw, uint32_t offset)
{
    if (hw == NULL || (offset & UINT32_C(3)) != 0u ||
        (size_t)(offset / 4u) >= TEST_FAKE_CSR_WORDS) {
        return NULL;
    }
    return &hw->regs[offset / 4u];
}

static const uint32_t *test_fake_reg_const(const test_fake_hw_t *hw, uint32_t offset)
{
    if (hw == NULL || (offset & UINT32_C(3)) != 0u ||
        (size_t)(offset / 4u) >= TEST_FAKE_CSR_WORDS) {
        return NULL;
    }
    return &hw->regs[offset / 4u];
}

static void test_fake_set_status_controls(test_fake_hw_t *hw, bool telemetry, bool writer)
{
    uint32_t *status = test_fake_reg(hw, TCSR_STATUS_OFFSET);
    if (status == NULL) {
        return;
    }
    *status &= ~(TCSR_STATUS_TELEMETRY_ENABLED_MASK |
                 TCSR_STATUS_RING_WRITER_ENABLED_MASK);
    if (telemetry) {
        *status |= TCSR_STATUS_TELEMETRY_ENABLED_MASK;
    }
    if (writer) {
        *status |= TCSR_STATUS_RING_WRITER_ENABLED_MASK;
    }
}

static void test_fake_set_actual_source(test_fake_hw_t *hw, uint32_t source)
{
    uint32_t *status = test_fake_reg(hw, TCSR_STATUS_OFFSET);
    if (status == NULL) {
        return;
    }
    *status &= ~(TCSR_STATUS_ACTUAL_SOURCE_MODE_MASK |
                 TCSR_STATUS_SOURCE_COMMIT_PENDING_MASK |
                 TCSR_STATUS_SOURCE_TRANSITION_BUSY_MASK);
    *status |= (source << TCSR_STATUS_ACTUAL_SOURCE_MODE_LSB) &
               TCSR_STATUS_ACTUAL_SOURCE_MODE_MASK;
}

static trecap_csr_status_t test_fake_read32(void *context,
                                            const trecap_csr_window_t *csr,
                                            uint32_t offset,
                                            uint32_t *value)
{
    (void)csr;
    test_fake_hw_t *hw = (test_fake_hw_t *)context;
    if (hw == NULL || value == NULL) {
        return TRECAP_CSR_ERR_NULL;
    }
    if (hw->fail_read_enabled && offset == hw->fail_read_offset) {
        return TRECAP_CSR_ERR_IO;
    }
    const uint32_t *reg = test_fake_reg_const(hw, offset);
    if (reg == NULL) {
        return TRECAP_CSR_ERR_RANGE;
    }
    *value = *reg;
    return TRECAP_CSR_OK;
}

static void test_fake_apply_control(test_fake_hw_t *hw, uint32_t value)
{
    hw->control_write_calls += 1u;
    const uint32_t w1p = value & (TCSR_CONTROL_TELEMETRY_SOFT_RESET_MASK |
                                  TCSR_CONTROL_CLEAR_METRICS_MASK);
    if (w1p != 0u) {
        if (hw->unrelated_reject_on_clear_metrics &&
            (w1p & TCSR_CONTROL_CLEAR_METRICS_MASK) != 0u) {
            uint32_t *reject_count =
                test_fake_reg(hw, TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET);
            if (reject_count != NULL) {
                *reject_count += 1u;
            }
        }
        return;
    }
    if (hw->suppress_all_control_levels ||
        (hw->suppress_control_write_number != 0u &&
         hw->control_write_calls == hw->suppress_control_write_number)) {
        return;
    }
    test_fake_set_status_controls(hw,
                                  (value & TCSR_CONTROL_TELEMETRY_ENABLE_MASK) != 0u,
                                  (value & TCSR_CONTROL_RING_WRITER_ENABLE_MASK) != 0u);
}

static void test_fake_apply_replay_control(test_fake_hw_t *hw, uint32_t value)
{
    uint32_t *replay = test_fake_reg(hw, TCSR_REPLAY_STATUS_OFFSET);
    if (replay == NULL) {
        return;
    }
    if ((value & TCSR_REPLAY_CONTROL_REARM_MASK) != 0u) {
        hw->replay_rearm_write_attempts += 1u;
        if ((*replay & TCSR_REPLAY_STATUS_REARM_REQUIRED_MASK) == 0u) {
            /* Match RTL: REARM without a failed epoch is a clean CSR reject,
             * not an accepted pulse. This makes healthy RESET tests detect an
             * unnecessary write even though the MMIO store itself completes. */
            uint32_t *reject_count =
                test_fake_reg(hw, TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET);
            if (reject_count != NULL) {
                *reject_count += 1u;
            }
            return;
        }
        hw->replay_rearm_pulses += 1u;
        *replay &= ~(TCSR_REPLAY_STATUS_PENDING_MASK |
                     TCSR_REPLAY_STATUS_REARM_REQUIRED_MASK);
        if (!hw->replay_rearm_leave_retained_state) {
            *replay &= ~(TCSR_REPLAY_STATUS_LAST_ACCEPT_MASK |
                         TCSR_REPLAY_STATUS_LAST_REJECT_MASK |
                         TCSR_REPLAY_STATUS_ERROR_MASK);
        }
        if (hw->replay_rearm_epoch_increment) {
            const uint32_t epoch = ((*replay & TCSR_REPLAY_STATUS_RESULT_EPOCH_MASK) >>
                                    TCSR_REPLAY_STATUS_RESULT_EPOCH_LSB) +
                                   1u;
            *replay &= ~TCSR_REPLAY_STATUS_RESULT_EPOCH_MASK;
            *replay |= (epoch << TCSR_REPLAY_STATUS_RESULT_EPOCH_LSB) &
                       TCSR_REPLAY_STATUS_RESULT_EPOCH_MASK;
        }
    }
    if ((value & TCSR_REPLAY_CONTROL_START_MASK) == 0u) {
        return;
    }
    hw->replay_start_pulses += 1u;
    *replay &= ~(TCSR_REPLAY_STATUS_PENDING_MASK |
                 TCSR_REPLAY_STATUS_LAST_ACCEPT_MASK |
                 TCSR_REPLAY_STATUS_LAST_REJECT_MASK);
    if (hw->replay_decision == TEST_REPLAY_TIMEOUT) {
        *replay |= TCSR_REPLAY_STATUS_PENDING_MASK;
        return;
    }
    const uint32_t epoch = ((*replay & TCSR_REPLAY_STATUS_RESULT_EPOCH_MASK) >>
                            TCSR_REPLAY_STATUS_RESULT_EPOCH_LSB) +
                           1u;
    *replay &= ~TCSR_REPLAY_STATUS_RESULT_EPOCH_MASK;
    *replay |= (epoch << TCSR_REPLAY_STATUS_RESULT_EPOCH_LSB) &
               TCSR_REPLAY_STATUS_RESULT_EPOCH_MASK;
    if (hw->replay_decision == TEST_REPLAY_ACCEPT) {
        *replay |= TCSR_REPLAY_STATUS_LAST_ACCEPT_MASK;
        if (hw->replay_accept_counter_increment) {
            uint32_t *reject_count =
                test_fake_reg(hw, TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET);
            if (reject_count != NULL) {
                *reject_count += 1u;
            }
        }
    } else {
        uint32_t *reject_count = test_fake_reg(hw, TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET);
        *replay |= TCSR_REPLAY_STATUS_LAST_REJECT_MASK;
        if (reject_count != NULL) {
            *reject_count += 1u;
        }
    }
}

static trecap_csr_status_t test_fake_write32(void *context,
                                             const trecap_csr_window_t *csr,
                                             uint32_t offset,
                                             uint32_t value)
{
    (void)csr;
    test_fake_hw_t *hw = (test_fake_hw_t *)context;
    if (hw == NULL) {
        return TRECAP_CSR_ERR_NULL;
    }
    hw->write_calls += 1u;
    if (hw->write_calls <= TEST_MAX_WRITES) {
        hw->writes[hw->write_calls - 1u].offset = offset;
        hw->writes[hw->write_calls - 1u].value = value;
    }
    if (hw->fail_write_call != 0u && hw->write_calls == hw->fail_write_call) {
        return TRECAP_CSR_ERR_IO;
    }
    uint32_t *reg = test_fake_reg(hw, offset);
    if (reg == NULL) {
        return TRECAP_CSR_ERR_RANGE;
    }
    hw->successful_writes += 1u;

    if (hw->reject_write_enabled && offset == hw->reject_write_offset) {
        uint32_t *reject_count = test_fake_reg(hw, TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET);
        if (reject_count != NULL) {
            *reject_count += 1u;
        }
        return TRECAP_CSR_OK;
    }
    switch (offset) {
    case TCSR_CONTROL_OFFSET:
        test_fake_apply_control(hw, value);
        break;
    case TCSR_SOURCE_MODE_COMMIT_OFFSET:
        if ((value & UINT32_C(1)) != 0u) {
            const uint32_t *shadow = test_fake_reg_const(hw, TCSR_SOURCE_MODE_SHADOW_OFFSET);
            if (shadow != NULL) {
                test_fake_set_actual_source(hw, *shadow);
            }
        }
        break;
    case TCSR_THR2_COMMIT_OFFSET: {
        uint32_t *status = test_fake_reg(hw, TCSR_STATUS_OFFSET);
        if (status != NULL) {
            *status &= ~TCSR_STATUS_THR2_COMMIT_PENDING_MASK;
        }
        if (hw->unrelated_reject_on_thr2_commit) {
            uint32_t *reject_count =
                test_fake_reg(hw, TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET);
            if (reject_count != NULL) {
                *reject_count += 1u;
            }
        }
        break;
    }
    case TCSR_COUNTER_CLEAR_OFFSET:
        if ((value & TCSR_COUNTER_CLEAR_TRANSPORT_COUNTERS_MASK) != 0u) {
            const uint32_t counter_offsets[] = {
                TCSR_DMA_DROP_COUNT_OFFSET,
                TCSR_DMA_PACKET_COUNT_OFFSET,
                TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET,
                TCSR_PACKET_FIFO_DROP_COUNT_OFFSET,
            };
            hw->counter_clear_pulses += 1u;
            for (size_t i = 0u; i < sizeof(counter_offsets) / sizeof(counter_offsets[0]); ++i) {
                uint32_t *counter = test_fake_reg(hw, counter_offsets[i]);
                if (counter != NULL) {
                    *counter = 0u;
                }
            }
        }
        break;
    case TCSR_REPLAY_CONTROL_OFFSET:
        test_fake_apply_replay_control(hw, value);
        break;
    default:
        *reg = value;
        break;
    }
    return TRECAP_CSR_OK;
}

static trecap_ring_status_t test_fake_ring_reset(void *context, trecap_ring_reader_t *reader)
{
    test_fake_hw_t *hw = (test_fake_hw_t *)context;
    if (hw == NULL || reader == NULL) {
        return TRECAP_RING_ERR_NULL;
    }
    hw->ring_reset_calls += 1u;
    reader->state = TRECAP_RING_READER_RECONFIG_REQUIRED;
    reader->telemetry_disabled_by_reader = true;
    reader->rd = 0u;
    reader->wr_snapshot = 0u;
    reader->have_last_seq = false;
    test_fake_set_status_controls(hw, false, false);
    *test_fake_reg(hw, TCSR_THR2_LO_OFFSET) = 0u;
    *test_fake_reg(hw, TCSR_THR2_HI_OFFSET) = 0u;
    *test_fake_reg(hw, TCSR_SOURCE_MODE_SHADOW_OFFSET) = TCSR_SOURCE_MODE_BRAM_REPLAY;
    test_fake_set_actual_source(hw, TCSR_SOURCE_MODE_BRAM_REPLAY);
    uint32_t *status = test_fake_reg(hw, TCSR_STATUS_OFFSET);
    if (status != NULL) {
        *status &= ~TCSR_STATUS_RING_CONFIGURED_MASK;
    }
    return TRECAP_RING_OK;
}

static trecap_ring_status_t test_fake_ring_configure(void *context,
                                                     trecap_ring_reader_t *reader,
                                                     uint64_t ring_base_fpga,
                                                     uint32_t ring_size_bytes,
                                                     uint32_t ring_guard_bytes)
{
    test_fake_hw_t *hw = (test_fake_hw_t *)context;
    if (hw == NULL || reader == NULL ||
        ring_base_fpga != TRECAP_HPS_DE1SOC_RING_FPGA_BASE ||
        ring_size_bytes != TRECAP_HPS_DE1SOC_RING_SIZE_BYTES ||
        ring_guard_bytes != (uint32_t)TCSR_RING_GUARD_BYTES_MIN) {
        return TRECAP_RING_ERR_CONFIG;
    }
    hw->ring_configure_calls += 1u;
    reader->state = TRECAP_RING_READER_RD0_REQUIRED;
    reader->cfg.ring_size_bytes = ring_size_bytes;
    reader->cfg.ring_guard_bytes = ring_guard_bytes;
    uint32_t *status = test_fake_reg(hw, TCSR_STATUS_OFFSET);
    if (status != NULL) {
        *status |= TCSR_STATUS_RING_CONFIGURED_MASK |
                   TCSR_STATUS_TRANSPORT_EPOCH_IDLE_MASK;
        *status &= ~TCSR_STATUS_MALFORMED_CONFIG_MASK;
    }
    return TRECAP_RING_OK;
}

static trecap_ring_status_t test_fake_ring_commit(void *context,
                                                  trecap_ring_reader_t *reader,
                                                  uint64_t rd)
{
    test_fake_hw_t *hw = (test_fake_hw_t *)context;
    if (hw == NULL || reader == NULL || rd != 0u ||
        reader->state != TRECAP_RING_READER_RD0_REQUIRED) {
        return TRECAP_RING_ERR_CONFIG;
    }
    hw->ring_commit_calls += 1u;
    reader->rd = 0u;
    reader->state = TRECAP_RING_READER_ACTIVE;
    return TRECAP_RING_OK;
}

static trecap_ring_status_t test_fake_ring_snapshot(void *context,
                                                    trecap_ring_reader_t *reader,
                                                    uint64_t *wr_out)
{
    test_fake_hw_t *hw = (test_fake_hw_t *)context;
    if (hw == NULL || reader == NULL || wr_out == NULL) {
        return TRECAP_RING_ERR_NULL;
    }
    hw->ring_snapshot_calls += 1u;
    *wr_out = hw->ring_wr;
    reader->wr_snapshot = *wr_out;
    return TRECAP_RING_OK;
}

static trecap_command_packet_t test_command(uint16_t version,
                                            uint16_t type,
                                            uint32_t seq,
                                            uint32_t arg0,
                                            uint32_t arg1,
                                            uint32_t arg2)
{
    trecap_command_packet_t cmd;
    cmd.magic = TCMD_COMMAND_MAGIC;
    cmd.version = version;
    cmd.cmd_type = type;
    cmd.seq = seq;
    cmd.arg0 = arg0;
    cmd.arg1 = arg1;
    cmd.arg2 = arg2;
    cmd.crc32 = 0u;
    return cmd;
}

static void test_fixture_init(test_fixture_t *fixture)
{
    memset(fixture, 0, sizeof(*fixture));
    trecap_hps_config_set_defaults(&fixture->cfg);
    fixture->csr.base = (volatile uint8_t *)(volatile void *)fixture->hw.regs;
    fixture->csr.span_bytes = sizeof(fixture->hw.regs);
    fixture->reader.csr = &fixture->csr;
    fixture->reader.state = TRECAP_RING_READER_ACTIVE;
    fixture->reader.cfg.ring_size_bytes = fixture->cfg.ring_size_bytes;
    fixture->reader.cfg.ring_guard_bytes = fixture->cfg.ring_guard_bytes;
    fixture->reader.telemetry_disabled_by_reader = false;
    fixture->transport_enabled = true;
    fixture->active_thr2 = UINT64_C(0x1234);
    fixture->active_packet_enable = TCSR_PACKET_ENABLE_WAVE_EN_MASK;
    fixture->active_wave_decim = 4u;
    fixture->active_spec_mode = TCSR_SPEC_MODE_SPEC64;
    fixture->active_spec_shift = 3u;
    fixture->active_source_mode = TCSR_SOURCE_MODE_BRAM_REPLAY;
    fixture->hw.replay_decision = TEST_REPLAY_ACCEPT;

    *test_fake_reg(&fixture->hw, TCSR_ID_OFFSET) = TCSR_ID_VALUE;
    *test_fake_reg(&fixture->hw, TCSR_VERSION_OFFSET) = TCSR_VERSION_VALUE;
    *test_fake_reg(&fixture->hw, TCSR_STATUS_OFFSET) =
        TCSR_STATUS_TELEMETRY_ENABLED_MASK |
        TCSR_STATUS_RING_WRITER_ENABLED_MASK |
        TCSR_STATUS_RING_CONFIGURED_MASK |
        TCSR_STATUS_CORE_ALIVE_MASK |
        TCSR_STATUS_TRANSPORT_EPOCH_IDLE_MASK;
    test_fake_set_actual_source(&fixture->hw, fixture->active_source_mode);
    *test_fake_reg(&fixture->hw, TCSR_PACKET_ENABLE_OFFSET) =
        fixture->active_packet_enable;
    *test_fake_reg(&fixture->hw, TCSR_THR2_LO_OFFSET) =
        trecap_csr_lo32(fixture->active_thr2);
    *test_fake_reg(&fixture->hw, TCSR_THR2_HI_OFFSET) =
        trecap_csr_hi32(fixture->active_thr2);
    *test_fake_reg(&fixture->hw, TCSR_WAVE_DECIM_OFFSET) = fixture->active_wave_decim;
    *test_fake_reg(&fixture->hw, TCSR_SPEC_MODE_OFFSET) = fixture->active_spec_mode;
    *test_fake_reg(&fixture->hw, TCSR_SPEC_SHIFT_OFFSET) = fixture->active_spec_shift;
    *test_fake_reg(&fixture->hw, TCSR_REPLAY_STATUS_OFFSET) =
        TCSR_REPLAY_STATUS_START_READY_MASK;

    trecap_command_bridge_bindings_t bindings;
    memset(&bindings, 0, sizeof(bindings));
    bindings.csr = &fixture->csr;
    bindings.ring_reader = &fixture->reader;
    bindings.runtime_config = &fixture->cfg;
    bindings.command_counters = &fixture->command_counters;
    bindings.udp_counters = &fixture->udp_counters;
    bindings.transport_enabled = &fixture->transport_enabled;
    bindings.active_thr2 = &fixture->active_thr2;
    bindings.active_packet_enable = &fixture->active_packet_enable;
    bindings.active_wave_decim = &fixture->active_wave_decim;
    bindings.active_spec_mode = &fixture->active_spec_mode;
    bindings.active_spec_shift = &fixture->active_spec_shift;
    bindings.active_source_mode = &fixture->active_source_mode;
    bindings.records_consumed = &fixture->records_consumed;
    bindings.records_sent_or_dropped = &fixture->records_sent_or_dropped;

    trecap_command_bridge_ops_t ops;
    ops.read32 = test_fake_read32;
    ops.write32 = test_fake_write32;
    ops.ring_reset = test_fake_ring_reset;
    ops.ring_configure = test_fake_ring_configure;
    ops.ring_commit_rd = test_fake_ring_commit;
    ops.ring_snapshot_wr = test_fake_ring_snapshot;
    const trecap_command_bridge_status_t init_status =
        trecap_command_bridge_init(&fixture->bridge, &bindings, &ops, &fixture->hw);
    if (init_status != TRECAP_COMMAND_BRIDGE_OK) {
        fprintf(stderr, "fatal fixture bridge init failure: %d\n", (int)init_status);
    }
    fixture->bridge.poll_limit = 4u;
}

static trecap_command_bridge_status_t test_handle(test_fixture_t *fixture,
                                                  const trecap_command_packet_t *cmd,
                                                  trecap_command_bridge_outcome_t *outcome)
{
    char err_buf[160];
    err_buf[0] = '\0';
    return trecap_command_bridge_handle_v2(&fixture->bridge,
                                           cmd,
                                           outcome,
                                           err_buf,
                                           sizeof(err_buf));
}

static bool test_wire_contract_and_validation(void)
{
    TEST_CHECK(TCMD_VERSION_V1 == 1u);
    TEST_CHECK(TCMD_VERSION_V2 == 2u);
    TEST_CHECK(TCMD_VERSION_CURRENT == 2u);
    TEST_CHECK(TCMD_RESULT_BYTES == 32u);
    TEST_CHECK(TCMD_TYPE_SET_SPEC_MODE == UINT16_C(0x0008));
    TEST_CHECK(TCMD_TYPE_READ_STATUS_VERSION == UINT16_C(0x000e));

    uint8_t request[TCMD_PACKET_BYTES];
    memset(request, 0, sizeof(request));
    trecap_cmd_store_le32(&request[TCMD_MAGIC_OFFSET], TCMD_COMMAND_MAGIC);
    trecap_cmd_store_le16(&request[TCMD_VERSION_OFFSET], (uint16_t)TCMD_VERSION_V2);
    trecap_cmd_store_le16(&request[TCMD_CMD_TYPE_OFFSET], TCMD_TYPE_READ_STATUS_VERSION);
    trecap_cmd_store_le32(&request[TCMD_SEQ_OFFSET], UINT32_C(0x89abcdef));
    trecap_command_packet_t parsed;
    TEST_CHECK(trecap_command_packet_parse(request, sizeof(request), &parsed));
    TEST_CHECK(parsed.magic == TCMD_COMMAND_MAGIC);
    TEST_CHECK(parsed.version == (uint16_t)TCMD_VERSION_V2);
    TEST_CHECK(parsed.cmd_type == TCMD_TYPE_READ_STATUS_VERSION);
    TEST_CHECK(parsed.seq == UINT32_C(0x89abcdef));
    TEST_CHECK(trecap_command_packet_validate_fields(&parsed) == TRECAP_CMD_REJECT_NONE);

    trecap_command_packet_t ping =
        test_command((uint16_t)TCMD_VERSION_V2,
                     TCMD_TYPE_PING,
                     0u,
                     UINT32_C(0x11111111),
                     UINT32_C(0x22222222),
                     UINT32_C(0x33333333));
    TEST_CHECK(trecap_command_packet_validate_fields(&ping) == TRECAP_CMD_REJECT_NONE);
    ping.version = (uint16_t)TCMD_VERSION_V1;
    TEST_CHECK(trecap_command_packet_validate_fields(&ping) == TRECAP_CMD_REJECT_NONE);

    trecap_command_packet_t bad = test_command((uint16_t)TCMD_VERSION_V2,
                                               TCMD_TYPE_SET_SPEC_MODE,
                                               1u,
                                               3u,
                                               0u,
                                               0u);
    TEST_CHECK(trecap_command_packet_validate_args(&bad) == TRECAP_CMD_REJECT_RANGE);
    bad.arg0 = 1u;
    bad.arg2 = 1u;
    TEST_CHECK(trecap_command_packet_validate_args(&bad) ==
               TRECAP_CMD_REJECT_RESERVED_ARGUMENT);
    bad.version = (uint16_t)TCMD_VERSION_V1;
    TEST_CHECK(trecap_command_packet_validate_envelope(&bad) ==
               TRECAP_CMD_REJECT_UNSUPPORTED_TYPE);

    trecap_command_v2_result_packet_t result;
    trecap_command_v2_result_init(&result,
                                  TCMD_TYPE_SET_SPEC_MODE,
                                  UINT32_C(0x10203040),
                                  TRECAP_CMD_DISPOSITION_REJECTED,
                                  TRECAP_CMD_REJECT_UNSAFE_STATE,
                                  UINT32_C(0x55667788),
                                  UINT32_C(0x00010008));
    uint8_t wire[TCMD_RESULT_BYTES];
    TEST_CHECK(trecap_command_v2_result_encode(&result, wire, sizeof(wire)));
    TEST_CHECK(trecap_cmd_load_le32(&wire[0]) == UINT32_C(0x54524352));
    TEST_CHECK(trecap_cmd_load_le16(&wire[4]) == 2u);
    TEST_CHECK(trecap_cmd_load_le16(&wire[6]) == TCMD_TYPE_SET_SPEC_MODE);
    TEST_CHECK(trecap_cmd_load_le32(&wire[8]) == UINT32_C(0x10203040));
    TEST_CHECK(trecap_cmd_load_le32(&wire[12]) == TCMD_DISPOSITION_REJECTED);
    TEST_CHECK(trecap_cmd_load_le32(&wire[16]) == TCMD_REJECT_UNSAFE_STATE);
    TEST_CHECK(trecap_cmd_load_le32(&wire[20]) == UINT32_C(0x55667788));
    TEST_CHECK(trecap_cmd_load_le32(&wire[24]) == UINT32_C(0x00010008));
    TEST_CHECK(trecap_cmd_load_le32(&wire[28]) == 0u);

    trecap_hps_runtime_config_t cfg;
    trecap_hps_config_set_defaults(&cfg);
    TEST_CHECK(strcmp(cfg.hps_static_ip, "192.168.10.2") == 0);
    TEST_CHECK(cfg.command_listen_port == 5006u);
    TEST_CHECK(strcmp(cfg.trusted_command_peer, "192.168.10.1") == 0);
    TEST_CHECK(cfg.trusted_command_peer_port == 5007u);
    TEST_CHECK(cfg.transport_version_minor == 8u);
    TEST_CHECK(trecap_hps_config_validate(&cfg, NULL, 0u) == TRECAP_HPS_CONFIG_OK);
    cfg.trusted_command_peer_port = 5008u;
    TEST_CHECK(trecap_hps_config_validate(&cfg, NULL, 0u) ==
               TRECAP_HPS_CONFIG_ERR_BAD_VALUE);
    return true;
}

static bool test_exact_peer_learning_and_response(void)
{
    trecap_command_server_t server;
    memset(&server, 0, sizeof(server));
    server.cfg.require_trusted_peer = true;
    TEST_CHECK(trecap_command_peer_from_ipv4("192.168.10.1",
                                            5007u,
                                            &server.trusted_peer,
                                            NULL,
                                            0u) == TRECAP_CMD_OK);
    struct sockaddr_in exact = server.trusted_peer.addr;
    struct sockaddr_in wrong_port = exact;
    wrong_port.sin_port = htons(5008u);
    trecap_command_result_t receive_result;
    trecap_command_result_init(&receive_result);
    trecap_command_packet_t ping =
        test_command((uint16_t)TCMD_VERSION_V2, TCMD_TYPE_PING, 0u, 9u, 8u, 7u);
    TEST_CHECK(trecap_command_server_source_allowed(&server,
                                                   &exact,
                                                   &ping,
                                                   &receive_result));
    TEST_CHECK(!trecap_command_server_source_allowed(&server,
                                                    &wrong_port,
                                                    &ping,
                                                    &receive_result));
    TEST_CHECK(receive_result.reject_reason == TRECAP_CMD_REJECT_BAD_SOURCE);
    server.cfg.accept_any_source_for_lab_debug = true;
    TEST_CHECK(!trecap_command_server_source_allowed(&server,
                                                    &wrong_port,
                                                    &ping,
                                                    &receive_result));
    server.cfg.accept_any_source_for_lab_debug = false;

    trecap_command_server_t learner;
    memset(&learner, 0, sizeof(learner));
    learner.cfg.require_trusted_peer = true;
    learner.cfg.learn_trusted_peer_on_valid_ping = true;
    struct sockaddr_in learned_source;
    memset(&learned_source, 0, sizeof(learned_source));
    learned_source.sin_family = AF_INET;
    learned_source.sin_port = htons(61000u);
    TEST_CHECK(inet_pton(AF_INET, "127.0.0.4", &learned_source.sin_addr) == 1);
    trecap_command_packet_t mutation =
        test_command((uint16_t)TCMD_VERSION_V2, TCMD_TYPE_READ_STATUS_VERSION, 1u, 0u, 0u, 0u);
    TEST_CHECK(!trecap_command_server_source_allowed(&learner,
                                                    &learned_source,
                                                    &mutation,
                                                    &receive_result));
    trecap_command_result_init(&receive_result);
    TEST_CHECK(trecap_command_server_source_allowed(&learner,
                                                   &learned_source,
                                                   &ping,
                                                   &receive_result));
    TEST_CHECK(receive_result.trusted_peer_learned);
    TEST_CHECK(learner.learned_peer);
    TEST_CHECK(learner.trusted_peer.port == 61000u);
    learned_source.sin_port = htons(61001u);
    TEST_CHECK(!trecap_command_server_source_allowed(&learner,
                                                    &learned_source,
                                                    &ping,
                                                    &receive_result));

    memset(&g_send_capture, 0, sizeof(g_send_capture));
    server.fd = 77;
    server.open = true;
    trecap_command_v2_result_packet_t response;
    trecap_command_v2_result_init(&response,
                                  TCMD_TYPE_READ_STATUS_VERSION,
                                  12u,
                                  TRECAP_CMD_DISPOSITION_NOOP,
                                  TRECAP_CMD_REJECT_NONE,
                                  UINT32_C(0x12345678),
                                  TCSR_VERSION_VALUE);
    TEST_CHECK(trecap_command_server_send_v2_result(&server,
                                                   &response,
                                                   &exact,
                                                   NULL,
                                                   0u) == TRECAP_CMD_OK);
    TEST_CHECK(g_send_capture.calls == 1u);
    TEST_CHECK(g_send_capture.fd == 77);
    TEST_CHECK(g_send_capture.byte_count == TCMD_RESULT_BYTES);
    TEST_CHECK(g_send_capture.destination.sin_addr.s_addr == exact.sin_addr.s_addr);
    TEST_CHECK(g_send_capture.destination.sin_port == exact.sin_port);
    TEST_CHECK(trecap_command_server_send_v2_result(&server,
                                                   &response,
                                                   &wrong_port,
                                                   NULL,
                                                   0u) == TRECAP_CMD_ERR_SEND);
    TEST_CHECK(g_send_capture.calls == 1u);

    trecap_command_server_config_t invalid_cfg;
    trecap_command_server_config_set_defaults(&invalid_cfg, NULL);
    invalid_cfg.accept_any_source_for_lab_debug = true;
    trecap_command_server_t unopened;
    TEST_CHECK(trecap_command_server_open(&invalid_cfg,
                                         &unopened,
                                         NULL,
                                         0u) == TRECAP_CMD_ERR_BAD_ARG);
    invalid_cfg.accept_any_source_for_lab_debug = false;
    invalid_cfg.require_trusted_peer = false;
    TEST_CHECK(trecap_command_server_open(&invalid_cfg,
                                         &unopened,
                                         NULL,
                                         0u) == TRECAP_CMD_ERR_BAD_ARG);
    return true;
}

static bool test_identity_and_diagnostic_exception(void)
{
    test_fixture_t fixture;
    test_fixture_init(&fixture);
    *test_fake_reg(&fixture.hw, TCSR_VERSION_OFFSET) = UINT32_C(0x00010007);
    trecap_command_packet_t read =
        test_command((uint16_t)TCMD_VERSION_V2, TCMD_TYPE_READ_STATUS_VERSION, 1u, 0u, 0u, 0u);
    trecap_command_bridge_outcome_t outcome;
    TEST_CHECK(test_handle(&fixture, &read, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(outcome.disposition == TRECAP_CMD_DISPOSITION_NOOP);
    TEST_CHECK(outcome.result_packet.csr_version == UINT32_C(0x00010007));
    TEST_CHECK(fixture.hw.write_calls == 0u);

    test_fixture_init(&fixture);
    *test_fake_reg(&fixture.hw, TCSR_VERSION_OFFSET) = UINT32_C(0x00010007);
    fixture.active_thr2 = UINT64_C(0x11223344);
    trecap_command_packet_t noop_mutation =
        test_command((uint16_t)TCMD_VERSION_V2,
                     TCMD_TYPE_SET_THR2,
                     1u,
                     UINT32_C(0x11223344),
                     0u,
                     0u);
    TEST_CHECK(test_handle(&fixture, &noop_mutation, &outcome) ==
               TRECAP_COMMAND_BRIDGE_FAILED);
    TEST_CHECK(outcome.disposition == TRECAP_CMD_DISPOSITION_FAILED);
    TEST_CHECK(outcome.reject_reason == TRECAP_CMD_REJECT_VERSION_MISMATCH);
    TEST_CHECK(fixture.hw.write_calls == 0u);
    TEST_CHECK(!fixture.bridge.reset_required);
    return true;
}

static bool test_stop_and_wait_cache(void)
{
    test_fixture_t fixture;
    test_fixture_init(&fixture);
    trecap_command_bridge_outcome_t outcome;
    trecap_command_packet_t read =
        test_command((uint16_t)TCMD_VERSION_V2, TCMD_TYPE_READ_STATUS_VERSION, 10u, 0u, 0u, 0u);
    TEST_CHECK(test_handle(&fixture, &read, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(outcome.disposition == TRECAP_CMD_DISPOSITION_NOOP);
    trecap_command_v2_result_packet_t cached = outcome.result_packet;
    *test_fake_reg(&fixture.hw, TCSR_STATUS_OFFSET) ^= TCSR_STATUS_CORE_ALIVE_MASK;
    TEST_CHECK(test_handle(&fixture, &read, &outcome) == TRECAP_COMMAND_BRIDGE_DUPLICATE);
    TEST_CHECK(outcome.duplicate);
    TEST_CHECK(memcmp(&outcome.result_packet, &cached, sizeof(cached)) == 0);
    TEST_CHECK(fixture.hw.write_calls == 0u);

    trecap_command_packet_t conflict = read;
    conflict.arg0 = 1u;
    TEST_CHECK(test_handle(&fixture, &conflict, &outcome) == TRECAP_COMMAND_BRIDGE_REJECTED);
    TEST_CHECK(outcome.reject_reason == TRECAP_CMD_REJECT_SEQUENCE_CONFLICT);
    TEST_CHECK(fixture.bridge.last_seq == 10u);
    TEST_CHECK(test_handle(&fixture, &read, &outcome) == TRECAP_COMMAND_BRIDGE_DUPLICATE);

    trecap_command_packet_t stale = read;
    stale.seq = 9u;
    TEST_CHECK(test_handle(&fixture, &stale, &outcome) == TRECAP_COMMAND_BRIDGE_REJECTED);
    TEST_CHECK(outcome.reject_reason == TRECAP_CMD_REJECT_SEQUENCE_STALE);
    stale.seq = UINT32_C(0x8000000a);
    TEST_CHECK(test_handle(&fixture, &stale, &outcome) == TRECAP_COMMAND_BRIDGE_REJECTED);
    TEST_CHECK(outcome.reject_reason == TRECAP_CMD_REJECT_SEQUENCE_STALE);

    trecap_command_packet_t fresh = read;
    fresh.seq = 11u;
    TEST_CHECK(test_handle(&fixture, &fresh, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(outcome.result_packet.fpga_status != cached.fpga_status);

    trecap_command_bridge_reset_peer_session(&fixture.bridge);
    fresh.seq = UINT32_MAX;
    TEST_CHECK(test_handle(&fixture, &fresh, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    fresh.seq = 0u;
    TEST_CHECK(test_handle(&fixture, &fresh, &outcome) == TRECAP_COMMAND_BRIDGE_OK);

    trecap_command_packet_t range =
        test_command((uint16_t)TCMD_VERSION_V2, TCMD_TYPE_SET_SPEC_MODE, 1u, 3u, 0u, 0u);
    trecap_command_bridge_reset_peer_session(&fixture.bridge);
    TEST_CHECK(test_handle(&fixture, &range, &outcome) == TRECAP_COMMAND_BRIDGE_REJECTED);
    TEST_CHECK(outcome.reject_reason == TRECAP_CMD_REJECT_RANGE);
    cached = outcome.result_packet;
    TEST_CHECK(test_handle(&fixture, &range, &outcome) == TRECAP_COMMAND_BRIDGE_DUPLICATE);
    TEST_CHECK(memcmp(&cached, &outcome.result_packet, sizeof(cached)) == 0);
    return true;
}

static bool test_safe_config_order_and_v1(void)
{
    test_fixture_t fixture;
    test_fixture_init(&fixture);
    trecap_command_packet_t shift =
        test_command((uint16_t)TCMD_VERSION_V2, TCMD_TYPE_SET_SPEC_SHIFT, 1u, 7u, 0u, 0u);
    trecap_command_bridge_outcome_t outcome;
    TEST_CHECK(test_handle(&fixture, &shift, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(outcome.disposition == TRECAP_CMD_DISPOSITION_APPLIED);
    TEST_CHECK(fixture.active_spec_shift == 7u);
    TEST_CHECK(fixture.transport_enabled);
    TEST_CHECK(fixture.hw.write_calls == 4u);
    TEST_CHECK(fixture.hw.writes[0].offset == TCSR_CONTROL_OFFSET);
    TEST_CHECK(fixture.hw.writes[0].value == 0u);
    TEST_CHECK(fixture.hw.writes[1].offset == TCSR_SPEC_SHIFT_OFFSET);
    TEST_CHECK(fixture.hw.writes[1].value == 7u);
    TEST_CHECK(fixture.hw.writes[2].offset == TCSR_CONTROL_OFFSET);
    TEST_CHECK(fixture.hw.writes[2].value == TCSR_CONTROL_RING_WRITER_ENABLE_MASK);
    TEST_CHECK(fixture.hw.writes[3].offset == TCSR_CONTROL_OFFSET);
    TEST_CHECK(fixture.hw.writes[3].value ==
               (TCSR_CONTROL_RING_WRITER_ENABLE_MASK |
                TCSR_CONTROL_TELEMETRY_ENABLE_MASK));
    TEST_CHECK(*test_fake_reg(&fixture.hw, TCSR_SPEC_MODE_OFFSET) ==
               TCSR_SPEC_MODE_SPEC64);

    test_fixture_init(&fixture);
    trecap_command_packet_t noop =
        test_command((uint16_t)TCMD_VERSION_V2,
                     TCMD_TYPE_SET_SPEC_SHIFT,
                     1u,
                     fixture.active_spec_shift,
                     0u,
                     0u);
    TEST_CHECK(test_handle(&fixture, &noop, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(outcome.disposition == TRECAP_CMD_DISPOSITION_NOOP);
    TEST_CHECK(fixture.hw.write_calls == 0u);

    test_fixture_init(&fixture);
    trecap_command_packet_t v1 =
        test_command((uint16_t)TCMD_VERSION_V1,
                     TCMD_TYPE_SET_PACKET_ENABLE,
                     99u,
                     TCSR_PACKET_ENABLE_SPEC_EN_MASK,
                     0u,
                     0u);
    TEST_CHECK(trecap_command_bridge_apply_v1(&fixture.bridge,
                                             &v1,
                                             &outcome,
                                             NULL,
                                             0u) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(!outcome.has_result);
    TEST_CHECK(!fixture.bridge.ledger_valid);
    TEST_CHECK(fixture.hw.writes[0].offset == TCSR_CONTROL_OFFSET);
    TEST_CHECK(fixture.hw.writes[1].offset == TCSR_PACKET_ENABLE_OFFSET);
    return true;
}

typedef struct test_config_case {
    uint16_t cmd_type;
    uint32_t requested;
    uint32_t *mirror;
} test_config_case_t;

static bool test_restore_failure_rolls_back_all_config_mirrors(void)
{
    const uint16_t types[] = {
        TCMD_TYPE_SET_SOURCE_MODE,
        TCMD_TYPE_SET_PACKET_ENABLE,
        TCMD_TYPE_SET_WAVE_DECIM,
        TCMD_TYPE_SET_SPEC_MODE,
        TCMD_TYPE_SET_SPEC_SHIFT,
    };
    const uint32_t values[] = {
        TCSR_SOURCE_MODE_ADC_LIVE,
        TCSR_PACKET_ENABLE_SPEC_EN_MASK,
        8u,
        TCSR_SPEC_MODE_SPEC129,
        9u,
    };
    for (size_t index = 0u; index < sizeof(types) / sizeof(types[0]); ++index) {
        test_fixture_t fixture;
        test_fixture_init(&fixture);
        const uint32_t old_packet = fixture.active_packet_enable;
        const uint32_t old_decim = fixture.active_wave_decim;
        const uint32_t old_mode = fixture.active_spec_mode;
        const uint32_t old_shift = fixture.active_spec_shift;
        const uint32_t old_source = fixture.active_source_mode;
        fixture.hw.suppress_control_write_number = 2u;
        trecap_command_packet_t cmd = test_command((uint16_t)TCMD_VERSION_V2,
                                                   types[index],
                                                   1u,
                                                   values[index],
                                                   0u,
                                                   0u);
        trecap_command_bridge_outcome_t outcome;
        TEST_CHECK(test_handle(&fixture, &cmd, &outcome) == TRECAP_COMMAND_BRIDGE_FAILED);
        TEST_CHECK(outcome.disposition == TRECAP_CMD_DISPOSITION_FAILED);
        TEST_CHECK(outcome.fail_closed);
        TEST_CHECK(outcome.hardware_disable_verified);
        TEST_CHECK(fixture.bridge.reset_required);
        TEST_CHECK(!fixture.transport_enabled);
        TEST_CHECK(fixture.active_packet_enable == old_packet);
        TEST_CHECK(fixture.active_wave_decim == old_decim);
        TEST_CHECK(fixture.active_spec_mode == old_mode);
        TEST_CHECK(fixture.active_spec_shift == old_shift);
        TEST_CHECK(fixture.active_source_mode == old_source);
        const uint32_t status = *test_fake_reg(&fixture.hw, TCSR_STATUS_OFFSET);
        TEST_CHECK((status & (TCSR_STATUS_TELEMETRY_ENABLED_MASK |
                              TCSR_STATUS_RING_WRITER_ENABLED_MASK)) == 0u);
    }
    return true;
}

static bool test_rejected_config_stays_disabled(void)
{
    test_fixture_t fixture;
    test_fixture_init(&fixture);
    fixture.hw.reject_write_enabled = true;
    fixture.hw.reject_write_offset = TCSR_PACKET_ENABLE_OFFSET;
    const uint32_t old_value = fixture.active_packet_enable;
    trecap_command_packet_t cmd =
        test_command((uint16_t)TCMD_VERSION_V2,
                     TCMD_TYPE_SET_PACKET_ENABLE,
                     1u,
                     TCSR_PACKET_ENABLE_SPEC_EN_MASK,
                     0u,
                     0u);
    trecap_command_bridge_outcome_t outcome;
    TEST_CHECK(test_handle(&fixture, &cmd, &outcome) == TRECAP_COMMAND_BRIDGE_REJECTED);
    TEST_CHECK(outcome.disposition == TRECAP_CMD_DISPOSITION_REJECTED);
    TEST_CHECK(outcome.reject_reason == TRECAP_CMD_REJECT_CSR);
    TEST_CHECK(!fixture.transport_enabled);
    TEST_CHECK(fixture.active_packet_enable == old_value);
    TEST_CHECK(fixture.hw.control_write_calls == 1u);
    const uint32_t status = *test_fake_reg(&fixture.hw, TCSR_STATUS_OFFSET);
    TEST_CHECK((status & (TCSR_STATUS_TELEMETRY_ENABLED_MASK |
                          TCSR_STATUS_RING_WRITER_ENABLED_MASK)) == 0u);
    return true;
}

static bool test_unverified_hardware_disable(void)
{
    test_fixture_t fixture;
    test_fixture_init(&fixture);
    fixture.hw.fail_write_call = 2u;
    fixture.hw.suppress_all_control_levels = true;
    trecap_command_packet_t cmd =
        test_command((uint16_t)TCMD_VERSION_V2,
                     TCMD_TYPE_SET_THR2,
                     1u,
                     UINT32_C(0x55667788),
                     0u,
                     0u);
    trecap_command_bridge_outcome_t outcome;
    TEST_CHECK(test_handle(&fixture, &cmd, &outcome) == TRECAP_COMMAND_BRIDGE_FAILED);
    TEST_CHECK(outcome.fail_closed);
    TEST_CHECK(!outcome.hardware_disable_verified);
    TEST_CHECK(outcome.hardware_disable_status == TRECAP_CSR_ERR_BAD_VALUE);
    TEST_CHECK(fixture.bridge.reset_required);
    TEST_CHECK(fixture.reader.state == TRECAP_RING_READER_RESET_REQUIRED);
    TEST_CHECK(!fixture.transport_enabled);
    const uint32_t status = *test_fake_reg(&fixture.hw, TCSR_STATUS_OFFSET);
    TEST_CHECK((status & TCSR_STATUS_TELEMETRY_ENABLED_MASK) != 0u);
    TEST_CHECK((status & TCSR_STATUS_RING_WRITER_ENABLED_MASK) != 0u);
    return true;
}

static bool test_uncorrelated_reject_counter_is_not_command_ack(void)
{
    test_fixture_t fixture;
    test_fixture_init(&fixture);
    fixture.hw.unrelated_reject_on_thr2_commit = true;
    trecap_command_packet_t thr2 =
        test_command((uint16_t)TCMD_VERSION_V2,
                     TCMD_TYPE_SET_THR2,
                     1u,
                     UINT32_C(0x55667788),
                     UINT32_C(0x00112233),
                     0u);
    trecap_command_bridge_outcome_t outcome;
    TEST_CHECK(test_handle(&fixture, &thr2, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(outcome.disposition == TRECAP_CMD_DISPOSITION_APPLIED);
    TEST_CHECK(fixture.active_thr2 == UINT64_C(0x0011223355667788));
    TEST_CHECK(*test_fake_reg(&fixture.hw, TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET) == 1u);
    TEST_CHECK(!fixture.bridge.reset_required);

    test_fixture_init(&fixture);
    fixture.hw.unrelated_reject_on_clear_metrics = true;
    trecap_command_packet_t clear =
        test_command((uint16_t)TCMD_VERSION_V2,
                     TCMD_TYPE_CLEAR_METRICS,
                     1u,
                     0u,
                     0u,
                     0u);
    TEST_CHECK(test_handle(&fixture, &clear, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(outcome.disposition == TRECAP_CMD_DISPOSITION_APPLIED);
    TEST_CHECK(*test_fake_reg(&fixture.hw, TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET) == 1u);
    TEST_CHECK(!fixture.bridge.reset_required);
    const uint32_t status = *test_fake_reg(&fixture.hw, TCSR_STATUS_OFFSET);
    TEST_CHECK((status & TCSR_STATUS_TELEMETRY_ENABLED_MASK) != 0u);
    TEST_CHECK((status & TCSR_STATUS_RING_WRITER_ENABLED_MASK) != 0u);
    return true;
}

static bool test_reset_configure_enable_lifecycle(void)
{
    test_fixture_t fixture;
    test_fixture_init(&fixture);
    trecap_command_bridge_outcome_t outcome;
    trecap_command_packet_t cmd =
        test_command((uint16_t)TCMD_VERSION_V2, TCMD_TYPE_RESET_TRANSPORT, 1u, 0u, 0u, 0u);
    TEST_CHECK(test_handle(&fixture, &cmd, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(outcome.disposition == TRECAP_CMD_DISPOSITION_APPLIED);
    TEST_CHECK(fixture.hw.ring_reset_calls == 1u);
    TEST_CHECK(fixture.hw.replay_rearm_write_attempts == 0u);
    TEST_CHECK(fixture.hw.replay_rearm_pulses == 0u);
    TEST_CHECK(*test_fake_reg(&fixture.hw, TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET) == 0u);
    TEST_CHECK(fixture.reader.state == TRECAP_RING_READER_RECONFIG_REQUIRED);
    TEST_CHECK(!fixture.transport_enabled);

    cmd = test_command((uint16_t)TCMD_VERSION_V2,
                       TCMD_TYPE_CONFIGURE_DDR_RING,
                       2u,
                       0u,
                       0u,
                       0u);
    TEST_CHECK(test_handle(&fixture, &cmd, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(fixture.hw.ring_configure_calls == 1u);
    TEST_CHECK(fixture.hw.ring_commit_calls == 1u);
    TEST_CHECK(fixture.hw.ring_snapshot_calls == 1u);
    TEST_CHECK(fixture.reader.state == TRECAP_RING_READER_ACTIVE);
    TEST_CHECK(!fixture.transport_enabled);

    cmd = test_command((uint16_t)TCMD_VERSION_V2,
                       TCMD_TYPE_SET_TELEMETRY_ENABLE,
                       3u,
                       1u,
                       0u,
                       0u);
    TEST_CHECK(test_handle(&fixture, &cmd, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(outcome.disposition == TRECAP_CMD_DISPOSITION_APPLIED);
    TEST_CHECK(fixture.transport_enabled);
    TEST_CHECK(!fixture.reader.telemetry_disabled_by_reader);

    cmd.arg0 = 0u;
    cmd.seq = 4u;
    TEST_CHECK(test_handle(&fixture, &cmd, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(!fixture.transport_enabled);
    TEST_CHECK(fixture.reader.telemetry_disabled_by_reader);

    /* A retained failed epoch is the one legal RESET-time REARM case. */
    test_fixture_init(&fixture);
    const uint32_t failed_epoch = UINT32_C(0x005a0000);
    *test_fake_reg(&fixture.hw, TCSR_REPLAY_STATUS_OFFSET) =
        failed_epoch | TCSR_REPLAY_STATUS_LAST_REJECT_MASK |
        TCSR_REPLAY_STATUS_ERROR_MASK | TCSR_REPLAY_STATUS_REARM_REQUIRED_MASK;
    cmd = test_command((uint16_t)TCMD_VERSION_V2,
                       TCMD_TYPE_RESET_TRANSPORT,
                       1u,
                       0u,
                       0u,
                       0u);
    TEST_CHECK(test_handle(&fixture, &cmd, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(outcome.disposition == TRECAP_CMD_DISPOSITION_APPLIED);
    TEST_CHECK(fixture.hw.replay_rearm_write_attempts == 1u);
    TEST_CHECK(fixture.hw.replay_rearm_pulses == 1u);
    TEST_CHECK((*test_fake_reg(&fixture.hw, TCSR_REPLAY_STATUS_OFFSET) &
                (TCSR_REPLAY_STATUS_REARM_REQUIRED_MASK |
                 TCSR_REPLAY_STATUS_ERROR_MASK)) == 0u);
    TEST_CHECK((*test_fake_reg(&fixture.hw, TCSR_REPLAY_STATUS_OFFSET) &
                TCSR_REPLAY_STATUS_RESULT_EPOCH_MASK) == failed_epoch);

    /* RESET is not allowed to turn an active replay into an implicit abort. */
    test_fixture_init(&fixture);
    *test_fake_reg(&fixture.hw, TCSR_REPLAY_STATUS_OFFSET) =
        TCSR_REPLAY_STATUS_REPLAY_ACTIVE_MASK |
        TCSR_REPLAY_STATUS_REARM_REQUIRED_MASK;
    cmd = test_command((uint16_t)TCMD_VERSION_V2,
                       TCMD_TYPE_RESET_TRANSPORT,
                       1u,
                       0u,
                       0u,
                       0u);
    TEST_CHECK(test_handle(&fixture, &cmd, &outcome) == TRECAP_COMMAND_BRIDGE_FAILED);
    TEST_CHECK(outcome.disposition == TRECAP_CMD_DISPOSITION_FAILED);
    TEST_CHECK(fixture.bridge.reset_required);
    TEST_CHECK(fixture.hw.replay_rearm_write_attempts == 0u);

    /* Accepted REARM is not complete until all retained result/error state is
     * read back clear; clearing only REARM_REQUIRED must fail closed. */
    test_fixture_init(&fixture);
    fixture.hw.replay_rearm_leave_retained_state = true;
    *test_fake_reg(&fixture.hw, TCSR_REPLAY_STATUS_OFFSET) =
        TCSR_REPLAY_STATUS_LAST_REJECT_MASK |
        TCSR_REPLAY_STATUS_ERROR_MASK | TCSR_REPLAY_STATUS_REARM_REQUIRED_MASK;
    cmd = test_command((uint16_t)TCMD_VERSION_V2,
                       TCMD_TYPE_RESET_TRANSPORT,
                       1u,
                       0u,
                       0u,
                       0u);
    TEST_CHECK(test_handle(&fixture, &cmd, &outcome) == TRECAP_COMMAND_BRIDGE_FAILED);
    TEST_CHECK(outcome.disposition == TRECAP_CMD_DISPOSITION_FAILED);
    TEST_CHECK(outcome.reject_reason == TRECAP_CMD_REJECT_TIMEOUT);
    TEST_CHECK(fixture.bridge.reset_required);
    TEST_CHECK(fixture.hw.replay_rearm_write_attempts == 1u);
    TEST_CHECK(fixture.hw.replay_rearm_pulses == 1u);
    return true;
}

static bool test_failed_config_reset_reconciles_hardware(void)
{
    test_fixture_t fixture;
    test_fixture_init(&fixture);
    const uint32_t committed_packet_enable = fixture.active_packet_enable;
    fixture.hw.suppress_control_write_number = 2u;
    trecap_command_packet_t mutate =
        test_command((uint16_t)TCMD_VERSION_V2,
                     TCMD_TYPE_SET_PACKET_ENABLE,
                     1u,
                     TCSR_PACKET_ENABLE_SPEC_EN_MASK,
                     0u,
                     0u);
    trecap_command_bridge_outcome_t outcome;
    TEST_CHECK(test_handle(&fixture, &mutate, &outcome) == TRECAP_COMMAND_BRIDGE_FAILED);
    TEST_CHECK(fixture.bridge.reset_required);
    TEST_CHECK(fixture.active_packet_enable == committed_packet_enable);
    TEST_CHECK(*test_fake_reg(&fixture.hw, TCSR_PACKET_ENABLE_OFFSET) ==
               TCSR_PACKET_ENABLE_SPEC_EN_MASK);

    fixture.hw.suppress_control_write_number = 0u;
    trecap_command_packet_t reset =
        test_command((uint16_t)TCMD_VERSION_V2, TCMD_TYPE_RESET_TRANSPORT, 2u, 0u, 0u, 0u);
    TEST_CHECK(test_handle(&fixture, &reset, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(outcome.disposition == TRECAP_CMD_DISPOSITION_APPLIED);
    TEST_CHECK(!fixture.bridge.reset_required);
    TEST_CHECK(*test_fake_reg(&fixture.hw, TCSR_PACKET_ENABLE_OFFSET) ==
               committed_packet_enable);
    TEST_CHECK(*test_fake_reg(&fixture.hw, TCSR_THR2_LO_OFFSET) ==
               trecap_csr_lo32(fixture.active_thr2));
    TEST_CHECK(*test_fake_reg(&fixture.hw, TCSR_THR2_HI_OFFSET) ==
               trecap_csr_hi32(fixture.active_thr2));
    TEST_CHECK(fixture.reader.state == TRECAP_RING_READER_RECONFIG_REQUIRED);
    TEST_CHECK(!fixture.transport_enabled);

    trecap_command_packet_t configure =
        test_command((uint16_t)TCMD_VERSION_V2,
                     TCMD_TYPE_CONFIGURE_DDR_RING,
                     3u,
                     0u,
                     0u,
                     0u);
    TEST_CHECK(test_handle(&fixture, &configure, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    trecap_command_packet_t enable =
        test_command((uint16_t)TCMD_VERSION_V2,
                     TCMD_TYPE_SET_TELEMETRY_ENABLE,
                     4u,
                     1u,
                     0u,
                     0u);
    TEST_CHECK(test_handle(&fixture, &enable, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(fixture.transport_enabled);
    TEST_CHECK(fixture.active_packet_enable == committed_packet_enable);
    TEST_CHECK(*test_fake_reg(&fixture.hw, TCSR_PACKET_ENABLE_OFFSET) ==
               committed_packet_enable);

    test_fixture_init(&fixture);
    fixture.bridge.reset_required = true;
    fixture.reader.state = TRECAP_RING_READER_RESET_REQUIRED;
    *test_fake_reg(&fixture.hw, TCSR_PACKET_ENABLE_OFFSET) =
        TCSR_PACKET_ENABLE_SPEC_EN_MASK;
    fixture.hw.reject_write_enabled = true;
    fixture.hw.reject_write_offset = TCSR_PACKET_ENABLE_OFFSET;
    reset = test_command((uint16_t)TCMD_VERSION_V2,
                         TCMD_TYPE_RESET_TRANSPORT,
                         1u,
                         0u,
                         0u,
                         0u);
    TEST_CHECK(test_handle(&fixture, &reset, &outcome) == TRECAP_COMMAND_BRIDGE_FAILED);
    TEST_CHECK(fixture.bridge.reset_required);
    TEST_CHECK(fixture.reader.state == TRECAP_RING_READER_RESET_REQUIRED);
    TEST_CHECK(!fixture.transport_enabled);
    return true;
}

static bool test_clear_counters_preserves_transport_state(void)
{
    test_fixture_t fixture;
    test_fixture_init(&fixture);
    *test_fake_reg(&fixture.hw, TCSR_DMA_DROP_COUNT_OFFSET) = 5u;
    *test_fake_reg(&fixture.hw, TCSR_DMA_PACKET_COUNT_OFFSET) = 6u;
    *test_fake_reg(&fixture.hw, TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET) = 7u;
    *test_fake_reg(&fixture.hw, TCSR_PACKET_FIFO_DROP_COUNT_OFFSET) = 8u;
    fixture.command_counters.datagrams_received = 10u;
    fixture.command_counters.commands_applied = 11u;
    fixture.reader.counters.records_seen = 12u;
    fixture.udp_counters.datagrams_sent = 13u;
    fixture.reader.rd = UINT64_C(0x1000);
    fixture.reader.wr_snapshot = UINT64_C(0x2000);
    fixture.reader.last_seq = 44u;
    fixture.reader.have_last_seq = true;
    fixture.records_consumed = 15u;
    fixture.records_sent_or_dropped = 16u;

    trecap_command_packet_t clear =
        test_command((uint16_t)TCMD_VERSION_V2, TCMD_TYPE_CLEAR_COUNTERS, 100u, 0u, 0u, 0u);
    trecap_command_bridge_outcome_t outcome;
    TEST_CHECK(test_handle(&fixture, &clear, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(outcome.counters_cleared);
    TEST_CHECK(fixture.hw.counter_clear_pulses == 1u);
    TEST_CHECK(fixture.command_counters.datagrams_received == 0u);
    TEST_CHECK(fixture.command_counters.commands_applied == 0u);
    TEST_CHECK(fixture.reader.counters.records_seen == 0u);
    TEST_CHECK(fixture.udp_counters.datagrams_sent == 0u);
    TEST_CHECK(fixture.records_consumed == 0u);
    TEST_CHECK(fixture.records_sent_or_dropped == 0u);
    TEST_CHECK(fixture.reader.rd == UINT64_C(0x1000));
    TEST_CHECK(fixture.reader.wr_snapshot == UINT64_C(0x2000));
    TEST_CHECK(fixture.reader.last_seq == 44u);
    TEST_CHECK(fixture.reader.have_last_seq);
    TEST_CHECK(fixture.bridge.ledger_valid && fixture.bridge.last_seq == 100u);
    trecap_command_v2_result_packet_t cached = outcome.result_packet;
    TEST_CHECK(test_handle(&fixture, &clear, &outcome) == TRECAP_COMMAND_BRIDGE_DUPLICATE);
    TEST_CHECK(fixture.hw.counter_clear_pulses == 1u);
    TEST_CHECK(memcmp(&cached, &outcome.result_packet, sizeof(cached)) == 0);
    return true;
}

static bool test_replay_accept_reject_and_timeout(void)
{
    test_fixture_t fixture;
    test_fixture_init(&fixture);
    trecap_command_packet_t start =
        test_command((uint16_t)TCMD_VERSION_V2,
                     TCMD_TYPE_START_BRAM_REPLAY,
                     1u,
                     0u,
                     0u,
                     0u);
    trecap_command_bridge_outcome_t outcome;
    TEST_CHECK(test_handle(&fixture, &start, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(outcome.disposition == TRECAP_CMD_DISPOSITION_APPLIED);
    TEST_CHECK(fixture.hw.replay_start_pulses == 1u);
    TEST_CHECK(!fixture.bridge.reset_required);

    test_fixture_init(&fixture);
    fixture.hw.replay_decision = TEST_REPLAY_ACCEPT;
    fixture.hw.replay_accept_counter_increment = true;
    *test_fake_reg(&fixture.hw, TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET) = 21u;
    TEST_CHECK(test_handle(&fixture, &start, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(outcome.disposition == TRECAP_CMD_DISPOSITION_APPLIED);
    TEST_CHECK(*test_fake_reg(&fixture.hw, TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET) == 22u);
    TEST_CHECK(!fixture.bridge.reset_required);

    test_fixture_init(&fixture);
    fixture.hw.replay_decision = TEST_REPLAY_REJECT;
    *test_fake_reg(&fixture.hw, TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET) = 9u;
    TEST_CHECK(test_handle(&fixture, &start, &outcome) == TRECAP_COMMAND_BRIDGE_REJECTED);
    TEST_CHECK(outcome.disposition == TRECAP_CMD_DISPOSITION_REJECTED);
    TEST_CHECK(outcome.reject_reason == TRECAP_CMD_REJECT_UNSAFE_STATE);
    TEST_CHECK(fixture.hw.replay_start_pulses == 1u);
    TEST_CHECK(*test_fake_reg(&fixture.hw, TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET) == 10u);
    TEST_CHECK(!fixture.bridge.reset_required);
    TEST_CHECK(fixture.reader.state == TRECAP_RING_READER_ACTIVE);
    TEST_CHECK(fixture.transport_enabled);
    trecap_command_packet_t read =
        test_command((uint16_t)TCMD_VERSION_V2, TCMD_TYPE_READ_STATUS_VERSION, 2u, 0u, 0u, 0u);
    TEST_CHECK(test_handle(&fixture, &read, &outcome) == TRECAP_COMMAND_BRIDGE_OK);

    test_fixture_init(&fixture);
    fixture.hw.replay_decision = TEST_REPLAY_ACCEPT;
    *test_fake_reg(&fixture.hw, TCSR_REPLAY_STATUS_OFFSET) |=
        TCSR_REPLAY_STATUS_REARM_REQUIRED_MASK;
    TEST_CHECK(test_handle(&fixture, &start, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(fixture.hw.replay_rearm_pulses == 1u);
    TEST_CHECK(fixture.hw.replay_start_pulses == 1u);

    test_fixture_init(&fixture);
    fixture.hw.replay_rearm_leave_retained_state = true;
    *test_fake_reg(&fixture.hw, TCSR_REPLAY_STATUS_OFFSET) =
        TCSR_REPLAY_STATUS_LAST_REJECT_MASK |
        TCSR_REPLAY_STATUS_ERROR_MASK | TCSR_REPLAY_STATUS_REARM_REQUIRED_MASK;
    TEST_CHECK(test_handle(&fixture, &start, &outcome) == TRECAP_COMMAND_BRIDGE_FAILED);
    TEST_CHECK(outcome.reject_reason == TRECAP_CMD_REJECT_TIMEOUT);
    TEST_CHECK(outcome.fail_closed);
    TEST_CHECK(fixture.hw.replay_rearm_pulses == 1u);
    TEST_CHECK(fixture.hw.replay_start_pulses == 0u);

    test_fixture_init(&fixture);
    *test_fake_reg(&fixture.hw, TCSR_REPLAY_STATUS_OFFSET) =
        TCSR_REPLAY_STATUS_REPLAY_ACTIVE_MASK |
        TCSR_REPLAY_STATUS_REARM_REQUIRED_MASK;
    TEST_CHECK(test_handle(&fixture, &start, &outcome) == TRECAP_COMMAND_BRIDGE_REJECTED);
    TEST_CHECK(outcome.reject_reason == TRECAP_CMD_REJECT_UNSAFE_STATE);
    TEST_CHECK(!outcome.fail_closed);
    TEST_CHECK(fixture.hw.replay_rearm_write_attempts == 0u);
    TEST_CHECK(fixture.hw.replay_start_pulses == 0u);

    test_fixture_init(&fixture);
    *test_fake_reg(&fixture.hw, TCSR_REPLAY_STATUS_OFFSET) =
        TCSR_REPLAY_STATUS_PENDING_MASK;
    TEST_CHECK(test_handle(&fixture, &start, &outcome) == TRECAP_COMMAND_BRIDGE_REJECTED);
    TEST_CHECK(outcome.reject_reason == TRECAP_CMD_REJECT_UNSAFE_STATE);
    TEST_CHECK(fixture.hw.replay_start_pulses == 0u);
    TEST_CHECK(!fixture.bridge.reset_required);

    test_fixture_init(&fixture);
    fixture.hw.replay_rearm_epoch_increment = true;
    *test_fake_reg(&fixture.hw, TCSR_REPLAY_STATUS_OFFSET) |=
        TCSR_REPLAY_STATUS_REARM_REQUIRED_MASK;
    TEST_CHECK(test_handle(&fixture, &start, &outcome) == TRECAP_COMMAND_BRIDGE_FAILED);
    TEST_CHECK(outcome.fail_closed);
    TEST_CHECK(fixture.hw.replay_rearm_pulses == 1u);
    TEST_CHECK(fixture.hw.replay_start_pulses == 0u);

    test_fixture_init(&fixture);
    fixture.hw.replay_decision = TEST_REPLAY_TIMEOUT;
    fixture.bridge.poll_limit = 2u;
    TEST_CHECK(test_handle(&fixture, &start, &outcome) == TRECAP_COMMAND_BRIDGE_FAILED);
    TEST_CHECK(outcome.reject_reason == TRECAP_CMD_REJECT_TIMEOUT);
    TEST_CHECK(outcome.fail_closed);
    TEST_CHECK(outcome.hardware_disable_verified);
    TEST_CHECK(fixture.bridge.reset_required);
    return true;
}

static bool test_async_malformed_gate(void)
{
    test_fixture_t fixture;
    test_fixture_init(&fixture);
    fixture.reader.state = TRECAP_RING_READER_MALFORMED_LATCHED;
    fixture.bridge.reset_required = false;
    trecap_command_packet_t mutation =
        test_command((uint16_t)TCMD_VERSION_V2,
                     TCMD_TYPE_SET_SPEC_SHIFT,
                     1u,
                     8u,
                     0u,
                     0u);
    trecap_command_bridge_outcome_t outcome;
    TEST_CHECK(test_handle(&fixture, &mutation, &outcome) == TRECAP_COMMAND_BRIDGE_REJECTED);
    TEST_CHECK(outcome.reject_reason == TRECAP_CMD_REJECT_RESET_REQUIRED);
    TEST_CHECK(fixture.bridge.reset_required);
    TEST_CHECK(fixture.hw.write_calls == 0u);

    trecap_command_packet_t read =
        test_command((uint16_t)TCMD_VERSION_V2, TCMD_TYPE_READ_STATUS_VERSION, 2u, 0u, 0u, 0u);
    TEST_CHECK(test_handle(&fixture, &read, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(outcome.disposition == TRECAP_CMD_DISPOSITION_NOOP);
    TEST_CHECK(fixture.hw.write_calls == 0u);

    trecap_command_packet_t reset =
        test_command((uint16_t)TCMD_VERSION_V2, TCMD_TYPE_RESET_TRANSPORT, 3u, 0u, 0u, 0u);
    TEST_CHECK(test_handle(&fixture, &reset, &outcome) == TRECAP_COMMAND_BRIDGE_OK);
    TEST_CHECK(fixture.hw.ring_reset_calls == 1u);
    TEST_CHECK(!fixture.bridge.reset_required);
    return true;
}

typedef bool (*test_function_t)(void);

typedef struct test_case {
    const char *name;
    test_function_t function;
} test_case_t;

int main(void)
{
    const test_case_t tests[] = {
        {"wire_contract_and_validation", test_wire_contract_and_validation},
        {"exact_peer_learning_and_response", test_exact_peer_learning_and_response},
        {"identity_and_diagnostic_exception", test_identity_and_diagnostic_exception},
        {"stop_and_wait_cache", test_stop_and_wait_cache},
        {"safe_config_order_and_v1", test_safe_config_order_and_v1},
        {"restore_failure_rolls_back_all_config_mirrors",
         test_restore_failure_rolls_back_all_config_mirrors},
        {"rejected_config_stays_disabled", test_rejected_config_stays_disabled},
        {"unverified_hardware_disable", test_unverified_hardware_disable},
        {"uncorrelated_reject_counter_is_not_command_ack",
         test_uncorrelated_reject_counter_is_not_command_ack},
        {"reset_configure_enable_lifecycle", test_reset_configure_enable_lifecycle},
        {"failed_config_reset_reconciles_hardware",
         test_failed_config_reset_reconciles_hardware},
        {"clear_counters_preserves_transport_state",
         test_clear_counters_preserves_transport_state},
        {"replay_accept_reject_and_timeout", test_replay_accept_reject_and_timeout},
        {"async_malformed_gate", test_async_malformed_gate},
    };
    size_t passed = 0u;
    for (size_t i = 0u; i < sizeof(tests) / sizeof(tests[0]); ++i) {
        if (!tests[i].function()) {
            fprintf(stderr, "Step-14 HPS test failed: %s\n", tests[i].name);
            return 1;
        }
        passed += 1u;
        printf("PASS %s\n", tests[i].name);
    }
    printf("Step-14 HPS command-path tests: PASS (%zu/%zu)\n",
           passed,
           sizeof(tests) / sizeof(tests[0]));
    return 0;
}

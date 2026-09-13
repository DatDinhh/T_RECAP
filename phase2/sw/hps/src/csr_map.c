/* SPDX-License-Identifier: MIT
 * T-RECAP Phase 2 HPS CSR access implementation.
 * File class: [1] hand-written.
 *
 * This file provides the HPS userspace MMIO wrapper for the generated CSR contract.
 * It does not duplicate CSR offsets, bit positions, packet IDs, payload sizes, or
 * transport-version constants. All register names and masks are consumed from
 * sw/hps/include/generated/trecap_csr.h through csr_map.h.
 */

#ifndef _FILE_OFFSET_BITS
#define _FILE_OFFSET_BITS 64
#endif

#include "csr_map.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <unistd.h>

#define TRECAP_CSR_DEV_MEM_PATH "/dev/mem"
#define TRECAP_CSR_MAX_WAIT_POLLS 1000000u

static void trecap_csr_io_fence(void)
{
#if defined(__GNUC__) || defined(__clang__)
    __sync_synchronize();
#endif
}

static trecap_csr_status_t trecap_csr_validate_window(const trecap_csr_window_t *csr,
                                                       uint32_t offset)
{
    if (csr == NULL || csr->base == NULL) {
        return TRECAP_CSR_ERR_NULL;
    }
    if (!trecap_csr_offset_is_aligned(offset)) {
        return TRECAP_CSR_ERR_ALIGN;
    }
    if (!trecap_csr_offset_in_range(csr, offset)) {
        return TRECAP_CSR_ERR_RANGE;
    }
    return TRECAP_CSR_OK;
}

static bool trecap_csr_span_is_valid(size_t span_bytes)
{
    const size_t min_span = (size_t)TCSR_REPLAY_STATUS_OFFSET + sizeof(uint32_t);
    return span_bytes >= min_span && (span_bytes % sizeof(uint32_t)) == 0u;
}

static long trecap_csr_page_size(void)
{
    long page_size = sysconf(_SC_PAGESIZE);
    if (page_size <= 0L) {
        page_size = 4096L;
    }
    return page_size;
}

const char *trecap_csr_status_string(trecap_csr_status_t status)
{
    switch (status) {
    case TRECAP_CSR_OK:
        return "TRECAP_CSR_OK";
    case TRECAP_CSR_ERR_NULL:
        return "TRECAP_CSR_ERR_NULL";
    case TRECAP_CSR_ERR_RANGE:
        return "TRECAP_CSR_ERR_RANGE";
    case TRECAP_CSR_ERR_ALIGN:
        return "TRECAP_CSR_ERR_ALIGN";
    case TRECAP_CSR_ERR_VERSION:
        return "TRECAP_CSR_ERR_VERSION";
    case TRECAP_CSR_ERR_BAD_VALUE:
        return "TRECAP_CSR_ERR_BAD_VALUE";
    case TRECAP_CSR_ERR_IO:
        return "TRECAP_CSR_ERR_IO";
    case TRECAP_CSR_ERR_TIMEOUT:
        return "TRECAP_CSR_ERR_TIMEOUT";
    default:
        return "TRECAP_CSR_ERR_UNKNOWN";
    }
}

trecap_csr_status_t trecap_csr_map_physical(uint64_t csr_base_phys,
                                            size_t span_bytes,
                                            trecap_csr_window_t *csr)
{
    if (csr == NULL) {
        return TRECAP_CSR_ERR_NULL;
    }
    csr->base = NULL;
    csr->span_bytes = 0u;

    if (!trecap_csr_span_is_valid(span_bytes)) {
        return TRECAP_CSR_ERR_RANGE;
    }

    const long page_size_long = trecap_csr_page_size();
    const uint64_t page_size = (uint64_t)page_size_long;
    if ((csr_base_phys % page_size) != 0u) {
        return TRECAP_CSR_ERR_ALIGN;
    }
    if (csr_base_phys > (uint64_t)INT64_MAX) {
        return TRECAP_CSR_ERR_RANGE;
    }

    const int fd = open(TRECAP_CSR_DEV_MEM_PATH, O_RDWR | O_SYNC | O_CLOEXEC);
    if (fd < 0) {
        return TRECAP_CSR_ERR_IO;
    }

    void *mapping = mmap(NULL,
                         span_bytes,
                         PROT_READ | PROT_WRITE,
                         MAP_SHARED,
                         fd,
                         (off_t)csr_base_phys);
    const int saved_errno = errno;
    (void)close(fd);
    errno = saved_errno;

    if (mapping == MAP_FAILED) {
        return TRECAP_CSR_ERR_IO;
    }

    csr->base = (volatile uint8_t *)mapping;
    csr->span_bytes = span_bytes;
    return TRECAP_CSR_OK;
}

void trecap_csr_unmap(trecap_csr_window_t *csr)
{
    if (csr == NULL || csr->base == NULL || csr->span_bytes == 0u) {
        if (csr != NULL) {
            csr->base = NULL;
            csr->span_bytes = 0u;
        }
        return;
    }

    void *base = (void *)(uintptr_t)csr->base;
    (void)munmap(base, csr->span_bytes);
    csr->base = NULL;
    csr->span_bytes = 0u;
}

trecap_csr_status_t trecap_csr_read32(const trecap_csr_window_t *csr,
                                      uint32_t offset,
                                      uint32_t *value)
{
    if (value == NULL) {
        return TRECAP_CSR_ERR_NULL;
    }

    trecap_csr_status_t status = trecap_csr_validate_window(csr, offset);
    if (status != TRECAP_CSR_OK) {
        return status;
    }

    trecap_csr_io_fence();
    *value = trecap_csr_read32_raw(csr, offset);
    trecap_csr_io_fence();
    return TRECAP_CSR_OK;
}

trecap_csr_status_t trecap_csr_write32(const trecap_csr_window_t *csr,
                                       uint32_t offset,
                                       uint32_t value)
{
    trecap_csr_status_t status = trecap_csr_validate_window(csr, offset);
    if (status != TRECAP_CSR_OK) {
        return status;
    }

    trecap_csr_io_fence();
    trecap_csr_write32_raw(csr, offset, value);
    trecap_csr_io_fence();
    return TRECAP_CSR_OK;
}

trecap_csr_status_t trecap_csr_require_id_version(const trecap_csr_window_t *csr,
                                                  uint32_t *id_out,
                                                  uint32_t *version_out)
{
    uint32_t id_value = 0u;
    uint32_t version_value = 0u;

    trecap_csr_status_t status = trecap_csr_read32(csr, TCSR_ID_OFFSET, &id_value);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    status = trecap_csr_read32(csr, TCSR_VERSION_OFFSET, &version_value);
    if (status != TRECAP_CSR_OK) {
        return status;
    }

    if (id_out != NULL) {
        *id_out = id_value;
    }
    if (version_out != NULL) {
        *version_out = version_value;
    }

    if (id_value != TCSR_ID_VALUE) {
        return TRECAP_CSR_ERR_VERSION;
    }
    if (version_value != TCSR_VERSION_VALUE || !trecap_csr_version_supported(version_value)) {
        return TRECAP_CSR_ERR_VERSION;
    }
    return TRECAP_CSR_OK;
}

trecap_csr_status_t trecap_csr_require_control_levels(const trecap_csr_window_t *csr,
                                                      bool telemetry_enable,
                                                      bool ring_writer_enable)
{
    uint32_t status_word = 0u;
    trecap_csr_status_t status = trecap_csr_read32(csr, TCSR_STATUS_OFFSET, &status_word);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    const bool telemetry_active =
        (status_word & TCSR_STATUS_TELEMETRY_ENABLED_MASK) != 0u;
    const bool writer_active =
        (status_word & TCSR_STATUS_RING_WRITER_ENABLED_MASK) != 0u;
    return telemetry_active == telemetry_enable && writer_active == ring_writer_enable
               ? TRECAP_CSR_OK
               : TRECAP_CSR_ERR_BAD_VALUE;
}

trecap_csr_status_t trecap_csr_require_ring_configured(const trecap_csr_window_t *csr)
{
    uint32_t status_word = 0u;
    trecap_csr_status_t status = trecap_csr_read32(csr, TCSR_STATUS_OFFSET, &status_word);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    if ((status_word & TCSR_STATUS_MALFORMED_CONFIG_MASK) != 0u ||
        (status_word & TCSR_STATUS_RING_CONFIGURED_MASK) == 0u) {
        return TRECAP_CSR_ERR_BAD_VALUE;
    }
    return TRECAP_CSR_OK;
}

trecap_csr_status_t trecap_csr_set_control_levels(const trecap_csr_window_t *csr,
                                                  bool telemetry_enable,
                                                  bool ring_writer_enable)
{
    const uint32_t control = trecap_csr_make_control_word(telemetry_enable, ring_writer_enable);
    return trecap_csr_write32(csr, TCSR_CONTROL_OFFSET, control);
}

trecap_csr_status_t trecap_csr_pulse_control(const trecap_csr_window_t *csr,
                                             uint32_t w1p_mask)
{
    const uint32_t legal_w1p = TCSR_CONTROL_TELEMETRY_SOFT_RESET_MASK |
                               TCSR_CONTROL_CLEAR_METRICS_MASK;
    if ((w1p_mask & ~legal_w1p) != 0u || w1p_mask == 0u) {
        return TRECAP_CSR_ERR_BAD_VALUE;
    }
    return trecap_csr_write32(csr, TCSR_CONTROL_OFFSET, w1p_mask);
}

trecap_csr_status_t trecap_csr_set_thr2(const trecap_csr_window_t *csr, uint64_t thr2)
{
    if (!trecap_csr_thr2_is_valid(thr2)) {
        return TRECAP_CSR_ERR_BAD_VALUE;
    }

    trecap_csr_status_t status = trecap_csr_write32(csr,
                                                    TCSR_THR2_LO_OFFSET,
                                                    trecap_csr_lo32(thr2));
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    status = trecap_csr_write32(csr, TCSR_THR2_HI_OFFSET, trecap_csr_hi32(thr2));
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    return trecap_csr_write32(csr, TCSR_THR2_COMMIT_OFFSET, UINT32_C(1));
}

trecap_csr_status_t trecap_csr_set_source_mode(const trecap_csr_window_t *csr,
                                               uint32_t source_mode)
{
    if (!trecap_csr_source_mode_is_valid(source_mode)) {
        return TRECAP_CSR_ERR_BAD_VALUE;
    }

    trecap_csr_status_t status = trecap_csr_write32(csr,
                                                    TCSR_SOURCE_MODE_SHADOW_OFFSET,
                                                    source_mode);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    return trecap_csr_write32(csr, TCSR_SOURCE_MODE_COMMIT_OFFSET, UINT32_C(1));
}

trecap_csr_status_t trecap_csr_set_packet_enable(const trecap_csr_window_t *csr,
                                                 uint32_t packet_enable)
{
    if (!trecap_csr_packet_enable_is_valid(packet_enable)) {
        return TRECAP_CSR_ERR_BAD_VALUE;
    }
    return trecap_csr_write32(csr, TCSR_PACKET_ENABLE_OFFSET, packet_enable);
}

trecap_csr_status_t trecap_csr_set_wave_decim(const trecap_csr_window_t *csr,
                                              uint32_t wave_decim)
{
    if (!trecap_csr_wave_decim_is_valid(wave_decim)) {
        return TRECAP_CSR_ERR_BAD_VALUE;
    }
    return trecap_csr_write32(csr, TCSR_WAVE_DECIM_OFFSET, wave_decim);
}

trecap_csr_status_t trecap_csr_set_spec_mode_shift(const trecap_csr_window_t *csr,
                                                   uint32_t spec_mode,
                                                   uint32_t spec_shift)
{
    if (!trecap_csr_spec_mode_is_valid(spec_mode) || !trecap_csr_spec_shift_is_valid(spec_shift)) {
        return TRECAP_CSR_ERR_BAD_VALUE;
    }

    trecap_csr_status_t status = trecap_csr_write32(csr, TCSR_SPEC_MODE_OFFSET, spec_mode);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    return trecap_csr_write32(csr, TCSR_SPEC_SHIFT_OFFSET, spec_shift);
}

trecap_csr_status_t trecap_csr_set_spec_mode(const trecap_csr_window_t *csr,
                                             uint32_t spec_mode)
{
    if (!trecap_csr_spec_mode_is_valid(spec_mode)) {
        return TRECAP_CSR_ERR_BAD_VALUE;
    }
    return trecap_csr_write32(csr, TCSR_SPEC_MODE_OFFSET, spec_mode);
}

trecap_csr_status_t trecap_csr_set_spec_shift(const trecap_csr_window_t *csr,
                                              uint32_t spec_shift)
{
    if (!trecap_csr_spec_shift_is_valid(spec_shift)) {
        return TRECAP_CSR_ERR_BAD_VALUE;
    }
    return trecap_csr_write32(csr, TCSR_SPEC_SHIFT_OFFSET, spec_shift);
}

trecap_csr_status_t trecap_csr_configure_ring(const trecap_csr_window_t *csr,
                                              const trecap_csr_ring_config_t *ring)
{
    if (ring == NULL) {
        return TRECAP_CSR_ERR_NULL;
    }
    if (!trecap_csr_ring_base_is_valid(ring->base_fpga) ||
        !trecap_csr_ring_size_is_valid(ring->size_bytes) ||
        ring->guard_bytes < TCSR_RING_GUARD_BYTES_MIN ||
        ring->guard_bytes >= ring->size_bytes ||
        (ring->guard_bytes % TCSR_RING_ALIGNMENT_BYTES) != 0u) {
        return TRECAP_CSR_ERR_BAD_VALUE;
    }

    trecap_csr_status_t status = trecap_csr_write32(csr,
                                                    TCSR_RING_BASE_LO_OFFSET,
                                                    trecap_csr_lo32(ring->base_fpga));
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    status = trecap_csr_write32(csr, TCSR_RING_BASE_HI_OFFSET, trecap_csr_hi32(ring->base_fpga));
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    status = trecap_csr_write32(csr, TCSR_RING_SIZE_BYTES_OFFSET, ring->size_bytes);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    return trecap_csr_write32(csr, TCSR_RING_CONFIG_COMMIT_OFFSET, UINT32_C(1));
}

trecap_csr_status_t trecap_csr_commit_ring_rd(const trecap_csr_window_t *csr, uint64_t rd)
{
    trecap_csr_status_t status = trecap_csr_write32(csr,
                                                    TCSR_RING_RD_LO_SHADOW_OFFSET,
                                                    trecap_csr_lo32(rd));
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    status = trecap_csr_write32(csr, TCSR_RING_RD_HI_SHADOW_OFFSET, trecap_csr_hi32(rd));
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    return trecap_csr_write32(csr, TCSR_RING_RD_COMMIT_OFFSET, UINT32_C(1));
}

trecap_csr_status_t trecap_csr_snapshot_ring_wr(const trecap_csr_window_t *csr,
                                                uint64_t *wr_out)
{
    if (wr_out == NULL) {
        return TRECAP_CSR_ERR_NULL;
    }

    trecap_csr_status_t status = trecap_csr_write32(csr, TCSR_RING_WR_SNAPSHOT_OFFSET, UINT32_C(1));
    if (status != TRECAP_CSR_OK) {
        return status;
    }

    uint32_t lo = 0u;
    uint32_t hi = 0u;
    status = trecap_csr_read32(csr, TCSR_RING_WR_LO_SNAP_OFFSET, &lo);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    status = trecap_csr_read32(csr, TCSR_RING_WR_HI_SNAP_OFFSET, &hi);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    *wr_out = trecap_csr_join_u64(lo, hi);
    return TRECAP_CSR_OK;
}

trecap_csr_status_t trecap_csr_snapshot_core_counts(const trecap_csr_window_t *csr,
                                                    trecap_csr_core_counts_t *counts_out)
{
    if (counts_out == NULL) {
        return TRECAP_CSR_ERR_NULL;
    }

    memset(counts_out, 0, sizeof(*counts_out));
    trecap_csr_status_t status = trecap_csr_write32(csr,
                                                    TCSR_CORE_COUNT_SNAPSHOT_OFFSET,
                                                    UINT32_C(1));
    if (status != TRECAP_CSR_OK) {
        return status;
    }

    uint32_t frame_lo = 0u;
    uint32_t frame_hi = 0u;
    uint32_t sample_lo = 0u;
    uint32_t sample_hi = 0u;
    status = trecap_csr_read32(csr, TCSR_FRAME_COUNT_SNAP_LO_OFFSET, &frame_lo);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    status = trecap_csr_read32(csr, TCSR_FRAME_COUNT_SNAP_HI_OFFSET, &frame_hi);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    status = trecap_csr_read32(csr, TCSR_SAMPLE_COUNT_SNAP_LO_OFFSET, &sample_lo);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    status = trecap_csr_read32(csr, TCSR_SAMPLE_COUNT_SNAP_HI_OFFSET, &sample_hi);
    if (status != TRECAP_CSR_OK) {
        return status;
    }

    counts_out->frame_count = trecap_csr_join_u64(frame_lo, frame_hi);
    counts_out->sample_count = trecap_csr_join_u64(sample_lo, sample_hi);
    return TRECAP_CSR_OK;
}

trecap_csr_status_t trecap_csr_read_counters(const trecap_csr_window_t *csr,
                                             trecap_csr_counters_t *counters_out)
{
    if (counters_out == NULL) {
        return TRECAP_CSR_ERR_NULL;
    }
    memset(counters_out, 0, sizeof(*counters_out));

    trecap_csr_status_t status = trecap_csr_read32(csr,
                                                   TCSR_DMA_DROP_COUNT_OFFSET,
                                                   &counters_out->dma_drop_count);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    status = trecap_csr_read32(csr,
                               TCSR_DMA_PACKET_COUNT_OFFSET,
                               &counters_out->dma_packet_count);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    status = trecap_csr_read32(csr,
                               TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET,
                               &counters_out->csr_command_reject_count);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    return trecap_csr_read32(csr,
                             TCSR_PACKET_FIFO_DROP_COUNT_OFFSET,
                             &counters_out->packet_fifo_drop_count);
}

trecap_csr_status_t trecap_csr_clear_sticky_flags(const trecap_csr_window_t *csr,
                                                  uint32_t clear_mask)
{
    return trecap_csr_write32(csr, TCSR_CLEAR_STICKY_FLAGS_OFFSET, clear_mask);
}

trecap_csr_status_t trecap_csr_clear_transport_counters(const trecap_csr_window_t *csr)
{
    return trecap_csr_write32(csr,
                              TCSR_COUNTER_CLEAR_OFFSET,
                              TCSR_COUNTER_CLEAR_TRANSPORT_COUNTERS_MASK);
}

trecap_csr_status_t trecap_csr_pulse_replay_control(const trecap_csr_window_t *csr,
                                                    uint32_t pulse_mask)
{
    if (pulse_mask != TCSR_REPLAY_CONTROL_START_MASK &&
        pulse_mask != TCSR_REPLAY_CONTROL_REARM_MASK) {
        return TRECAP_CSR_ERR_BAD_VALUE;
    }
    return trecap_csr_write32(csr, TCSR_REPLAY_CONTROL_OFFSET, pulse_mask);
}

trecap_csr_status_t trecap_csr_read_replay_status(const trecap_csr_window_t *csr,
                                                  trecap_csr_replay_status_t *status_out)
{
    if (status_out == NULL) {
        return TRECAP_CSR_ERR_NULL;
    }
    memset(status_out, 0, sizeof(*status_out));
    trecap_csr_status_t status =
        trecap_csr_read32(csr, TCSR_REPLAY_STATUS_OFFSET, &status_out->raw);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    const uint32_t raw = status_out->raw;
    status_out->result_epoch =
        (uint16_t)((raw & TCSR_REPLAY_STATUS_RESULT_EPOCH_MASK) >>
                   TCSR_REPLAY_STATUS_RESULT_EPOCH_LSB);
    status_out->pending = (raw & TCSR_REPLAY_STATUS_PENDING_MASK) != 0u;
    status_out->last_accept = (raw & TCSR_REPLAY_STATUS_LAST_ACCEPT_MASK) != 0u;
    status_out->last_reject = (raw & TCSR_REPLAY_STATUS_LAST_REJECT_MASK) != 0u;
    status_out->start_ready = (raw & TCSR_REPLAY_STATUS_START_READY_MASK) != 0u;
    status_out->replay_active = (raw & TCSR_REPLAY_STATUS_REPLAY_ACTIVE_MASK) != 0u;
    status_out->replay_path_busy =
        (raw & TCSR_REPLAY_STATUS_REPLAY_PATH_BUSY_MASK) != 0u;
    status_out->replay_path_done =
        (raw & TCSR_REPLAY_STATUS_REPLAY_PATH_DONE_MASK) != 0u;
    status_out->e2e_busy = (raw & TCSR_REPLAY_STATUS_E2E_BUSY_MASK) != 0u;
    status_out->e2e_done = (raw & TCSR_REPLAY_STATUS_E2E_DONE_MASK) != 0u;
    status_out->error = (raw & TCSR_REPLAY_STATUS_ERROR_MASK) != 0u;
    status_out->rearm_required =
        (raw & TCSR_REPLAY_STATUS_REARM_REQUIRED_MASK) != 0u;
    return TRECAP_CSR_OK;
}

trecap_csr_status_t trecap_csr_read_status_version(const trecap_csr_window_t *csr,
                                                   uint32_t *status_out,
                                                   uint32_t *version_out)
{
    if (status_out == NULL || version_out == NULL) {
        return TRECAP_CSR_ERR_NULL;
    }
    *status_out = 0u;
    *version_out = 0u;
    trecap_csr_status_t status = trecap_csr_read32(csr, TCSR_STATUS_OFFSET, status_out);
    if (status != TRECAP_CSR_OK) {
        return status;
    }
    return trecap_csr_read32(csr, TCSR_VERSION_OFFSET, version_out);
}
